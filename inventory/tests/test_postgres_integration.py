import os
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

import psycopg
from django.db import OperationalError, connection, connections
from django.test import TransactionTestCase
from psycopg import sql

from inventory.models import Instance, PasswordRotation
from inventory.services.crypto import decrypt_password, encrypt_password
from inventory.services.rotation import apply_rotation, prepare_rotation
from inventory.services.statistics import collect_snapshot

from .factories import make_instance


def in_separate_connection(barrier, operation):
    connections.close_all()
    try:
        barrier.wait(timeout=10)
        return operation()
    finally:
        connections.close_all()


class PostgreSQLConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("需要 PostgreSQL 管理库")

    def run_twice(self, operation):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(in_separate_connection, barrier, operation) for _ in range(2)]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_preparation_has_one_candidate(self):
        instance = make_instance()
        ids = self.run_twice(lambda: prepare_rotation(instance.id, force=True).id)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(PasswordRotation.objects.count(), 1)

    def test_concurrent_execution_changes_remote_only_once(self):
        instance = make_instance()
        rotation = prepare_rotation(instance.id, force=True)
        with patch(
            "inventory.services.rotation.ensure_remote_password", side_effect=lambda *_: time.sleep(0.1)
        ) as remote:
            results = self.run_twice(lambda: apply_rotation(rotation.id))
        self.assertEqual(results, ["succeeded", "succeeded"])
        self.assertEqual(remote.call_count, 1)

    def test_concurrent_snapshot_has_one_complete_result(self):
        make_instance()
        results = self.run_twice(lambda: (lambda result: (result[0].id, result[1]))(collect_snapshot()))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sum(created for _, created in results), 1)


@skipUnless(
    os.getenv("RUN_POSTGRES_INTEGRATION") == "1", "设置 RUN_POSTGRES_INTEGRATION=1 后执行真实目标库测试"
)
class RealPasswordRotationTests(TransactionTestCase):
    def setUp(self):
        self.admin_dsn = os.environ["TEST_TARGET_DSN"]
        self.role = f"managed_test_{uuid.uuid4().hex[:16]}"
        self.old_password = secrets.token_urlsafe(32)
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(self.role), sql.Literal(self.old_password)
                )
            )
            self.target_args = {
                "host": admin.info.host,
                "port": admin.info.port,
                "dbname": admin.info.dbname,
                "user": self.role,
                "sslmode": "disable",
                "connect_timeout": 3,
            }
        self.addCleanup(self.drop_role)
        with psycopg.connect(**self.target_args, password=self.old_password) as target:
            self.assertTrue(target.pgconn.used_password, "目标测试库必须开启密码认证，不能使用 trust")
        self.instance = make_instance(
            host=self.target_args["host"],
            port=self.target_args["port"],
            database=self.target_args["dbname"],
            username=self.role,
            encrypted_password=encrypt_password(self.old_password),
        )

    def drop_role(self):
        with psycopg.connect(self.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(self.role)))

    def assert_password_active(self, password):
        with psycopg.connect(**self.target_args, password=password) as target:
            self.assertEqual(target.execute("SELECT 1").fetchone(), (1,))

    def test_real_role_password_changes_and_old_password_stops_working(self):
        rotation = prepare_rotation(self.instance.id, force=True)
        self.assertEqual(apply_rotation(rotation.id), "succeeded")
        self.instance.refresh_from_db()
        self.assert_password_active(decrypt_password(self.instance.encrypted_password))
        with self.assertRaises(psycopg.OperationalError):
            psycopg.connect(**self.target_args, password=self.old_password)

    def test_real_remote_change_survives_local_failure(self):
        rotation = prepare_rotation(self.instance.id, force=True)
        candidate = decrypt_password(rotation.encrypted_password)
        with patch.object(Instance, "save", side_effect=OperationalError("simulated local failure")):
            with self.assertRaises(OperationalError):
                apply_rotation(rotation.id)
        self.assert_password_active(candidate)
        self.instance.refresh_from_db()
        self.assertEqual(decrypt_password(self.instance.encrypted_password), self.old_password)
        rotation.refresh_from_db()
        self.assertEqual(rotation.status, "pending")
        self.assertEqual(apply_rotation(rotation.id), "succeeded")
        self.instance.refresh_from_db()
        self.assertEqual(decrypt_password(self.instance.encrypted_password), candidate)
