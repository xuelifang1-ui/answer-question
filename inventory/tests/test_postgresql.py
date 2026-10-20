from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psycopg
from django.test import SimpleTestCase

from inventory.services.crypto import encrypt_password
from inventory.services.postgresql import RemoteRotationError, connect_target, ensure_remote_password


class PostgreSQLAdapterTests(SimpleTestCase):
    def setUp(self):
        self.instance = SimpleNamespace(
            host="127.0.0.1",
            port=5432,
            database="postgres",
            username="managed_user",
            encrypted_password=encrypt_password("old-password"),
        )

    def test_trust_authentication_is_not_accepted_as_password_verification(self):
        connection = MagicMock()
        connection.pgconn.used_password = False
        with patch("inventory.services.postgresql.psycopg.connect", return_value=connection):
            with self.assertRaisesRegex(RemoteRotationError, "password_auth_required"):
                connect_target(self.instance, "candidate")
        connection.close.assert_called_once()

    def test_password_authenticated_connection_is_accepted(self):
        connection = MagicMock()
        connection.pgconn.used_password = True
        with patch("inventory.services.postgresql.psycopg.connect", return_value=connection):
            self.assertIs(connect_target(self.instance, "candidate"), connection)

    def test_candidate_already_applied_does_not_execute_another_change(self):
        with patch("inventory.services.postgresql.connect_target") as connect:
            ensure_remote_password(self.instance, "candidate")
        connect.assert_called_once_with(self.instance, "candidate")
        connect.return_value.__enter__.return_value.execute.assert_not_called()

    def test_changes_role_then_verifies_on_a_new_connection(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.pgconn.encrypt_password.return_value = b"SCRAM-SHA-256$test-verifier"
        with patch(
            "inventory.services.postgresql.connect_target",
            side_effect=[
                psycopg.OperationalError("candidate is not active"),
                connection,
                connection,
            ],
        ) as connect:
            ensure_remote_password(self.instance, "candidate")
        self.assertEqual(
            [call.args[1] for call in connect.call_args_list], ["candidate", "old-password", "candidate"]
        )
        connection.pgconn.encrypt_password.assert_called_once_with(
            b"candidate", b"managed_user", b"scram-sha-256"
        )
        connection.execute.assert_called_once()
        self.assertNotIn("candidate", str(connection.execute.call_args))

    def test_target_database_error_is_sanitized(self):
        with patch(
            "inventory.services.postgresql.connect_target",
            side_effect=psycopg.OperationalError("sensitive connection details"),
        ):
            with self.assertRaisesRegex(RemoteRotationError, "^target_database_error$"):
                ensure_remote_password(self.instance, "candidate")

    def test_updated_allowlist_is_enforced_at_execution_time(self):
        self.instance.host = "169.254.169.254"
        with self.assertRaisesRegex(RemoteRotationError, "target_not_allowed"):
            ensure_remote_password(self.instance, "candidate")
