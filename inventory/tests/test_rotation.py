from datetime import timedelta
from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone

from inventory.models import Instance
from inventory.services.crypto import decrypt_password
from inventory.services.postgresql import RemoteRotationError
from inventory.services.rotation import RotationBackendError, apply_rotation, prepare_rotation
from inventory.tasks import dispatch_due_rotations

from .factories import make_instance


class RotationTests(TestCase):
    def test_not_due_or_disabled_is_skipped(self):
        instance = make_instance()
        self.assertIsNone(prepare_rotation(instance.id))
        Instance.objects.filter(pk=instance.id).update(
            rotation_enabled=False, next_rotation_at=timezone.now()
        )
        self.assertIsNone(prepare_rotation(instance.id))

    def test_due_instance_creates_encrypted_candidate(self):
        instance = make_instance(next_rotation_at=timezone.now() - timedelta(seconds=1))
        rotation = prepare_rotation(instance.id)
        self.assertEqual(len(decrypt_password(rotation.encrypted_password)), 32)
        self.assertNotEqual(rotation.encrypted_password, instance.encrypted_password)

    def test_pending_rotation_reuses_candidate(self):
        instance = make_instance()
        first = prepare_rotation(instance.id, force=True)
        second = prepare_rotation(instance.id, force=True)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.encrypted_password, second.encrypted_password)

    def test_success_updates_next_due_by_12_hours(self):
        instance = make_instance()
        rotation = prepare_rotation(instance.id, force=True)
        with patch("inventory.services.rotation.ensure_remote_password") as remote:
            self.assertEqual(apply_rotation(rotation.id), "succeeded")
        instance.refresh_from_db()
        rotation.refresh_from_db()
        remote.assert_called_once()
        self.assertEqual(instance.encrypted_password, rotation.encrypted_password)
        self.assertEqual(instance.next_rotation_at - instance.password_changed_at, timedelta(hours=12))
        self.assertEqual(rotation.status, "succeeded")

    def test_redelivery_after_success_does_not_change_password_again(self):
        instance = make_instance()
        rotation = prepare_rotation(instance.id, force=True)
        with patch("inventory.services.rotation.ensure_remote_password") as remote:
            apply_rotation(rotation.id)
            apply_rotation(rotation.id)
        self.assertEqual(remote.call_count, 1)

    def test_remote_failure_preserves_current_password_and_pending_candidate(self):
        instance = make_instance()
        old_cipher = instance.encrypted_password
        rotation = prepare_rotation(instance.id, force=True)
        with patch(
            "inventory.services.rotation.ensure_remote_password",
            side_effect=RemoteRotationError("target_database_error"),
        ):
            self.assertEqual(apply_rotation(rotation.id), "pending")
        instance.refresh_from_db()
        rotation.refresh_from_db()
        self.assertEqual(instance.encrypted_password, old_cipher)
        self.assertEqual(rotation.status, "pending")
        self.assertEqual(rotation.attempts, 1)
        self.assertEqual(rotation.last_error, "target_database_error")

    def test_local_failure_after_remote_change_can_recover(self):
        instance = make_instance()
        rotation = prepare_rotation(instance.id, force=True)
        remote_passwords = []
        with patch(
            "inventory.services.rotation.ensure_remote_password",
            side_effect=lambda _, password: remote_passwords.append(password),
        ):
            with patch.object(
                Instance, "save", side_effect=OperationalError("simulated local commit failure")
            ):
                with self.assertRaises(OperationalError):
                    apply_rotation(rotation.id)
            rotation.refresh_from_db()
            self.assertEqual(rotation.status, "pending")
            self.assertEqual(apply_rotation(rotation.id), "succeeded")
        self.assertEqual(remote_passwords[0], remote_passwords[1])

    def test_sweep_dispatches_due_and_pending_but_not_future_instances(self):
        due = make_instance(next_rotation_at=timezone.now())
        pending = make_instance(rotation_enabled=False)
        prepare_rotation(pending.id, force=True)
        make_instance()
        with patch("inventory.tasks.rotate_instance_password.delay") as enqueue:
            self.assertEqual(dispatch_due_rotations(), 2)
        self.assertEqual(enqueue.call_count, 2)
        self.assertEqual(due.rotations.count(), 1)

    def test_missing_instance_is_ignored(self):
        self.assertIsNone(prepare_rotation(999999, force=True))

    @override_settings(ALLOW_SQLITE_ROTATION_FOR_TESTS=False)
    def test_sqlite_worker_is_refused(self):
        from django.db import connection

        if connection.vendor == "postgresql":
            self.skipTest("当前使用 PostgreSQL")
        with self.assertRaises(RotationBackendError):
            prepare_rotation(1)
