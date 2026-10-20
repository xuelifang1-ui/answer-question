from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from kombu.exceptions import OperationalError as BrokerError
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from inventory.models import Cluster, Department, Instance, PasswordRotation
from inventory.services.crypto import decrypt_password
from inventory.services.rotation import prepare_rotation

from .factories import make_instance


class ApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="operator", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.department = Department.objects.create(code="rd", name="研发部")
        self.cluster = Cluster.objects.create(code="dev", name="开发集群")
        self.payload = {
            "name": "业务实例",
            "department": self.department.id,
            "cluster": self.cluster.id,
            "host": "127.0.0.1",
            "port": 5432,
            "database": "postgres",
            "username": "managed_app",
            "password": "  original-password  ",
        }

    def test_staff_token_authentication(self):
        self.client.force_authenticate(None)
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get("/api/instances/").status_code, 200)

    def test_anonymous_and_nonstaff_are_rejected(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/instances/").status_code, 401)
        self.client.force_authenticate(get_user_model().objects.create_user(username="ordinary"))
        self.assertEqual(self.client.get("/api/instances/").status_code, 403)

    def test_department_crud(self):
        created = self.client.post("/api/departments/", {"code": "qa", "name": "测试部"})
        self.assertEqual(created.status_code, 201)
        url = f"/api/departments/{created.data['id']}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            self.client.put(url, {"code": "qa", "name": "质量部"}, format="json").status_code, 200
        )
        self.assertEqual(self.client.patch(url, {"name": "质量保障部"}).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_cluster_crud(self):
        created = self.client.post("/api/clusters/", {"code": "staging", "name": "预发集群"})
        self.assertEqual(created.status_code, 201)
        url = f"/api/clusters/{created.data['id']}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"description": "预发环境"}).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_instance_crud_and_no_password_echo(self):
        created = self.client.post("/api/instances/", self.payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        instance = Instance.objects.get(pk=created.data["id"])
        self.assertEqual(decrypt_password(instance.encrypted_password), self.payload["password"])
        for content in (created.content, self.client.get("/api/instances/").content):
            self.assertNotIn(b'"password"', content)
            self.assertNotIn(b"encrypted_password", content)
            self.assertNotIn(self.payload["password"].encode(), content)
        url = f"/api/instances/{instance.id}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"name": "新名称"}).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_duplicate_codes_and_endpoints_are_rejected(self):
        self.assertEqual(
            self.client.post("/api/departments/", {"code": "rd", "name": "重复"}).status_code, 400
        )
        self.client.post("/api/instances/", self.payload, format="json")
        self.assertEqual(self.client.post("/api/instances/", self.payload, format="json").status_code, 400)

    def test_creation_requires_password(self):
        self.payload.pop("password")
        self.assertEqual(self.client.post("/api/instances/", self.payload, format="json").status_code, 400)

    def test_port_and_ip_validation(self):
        for port in (0, -1, 65536):
            with self.subTest(port=port):
                self.payload["port"] = port
                self.assertEqual(
                    self.client.post("/api/instances/", self.payload, format="json").status_code, 400
                )
        self.payload.update(port=5432, host="169.254.169.254")
        self.assertEqual(self.client.post("/api/instances/", self.payload, format="json").status_code, 400)

    def test_identifier_byte_length_and_nul(self):
        for field, value in (
            ("username", "医" * 22),
            ("database", "bad\x00name"),
            ("password", "bad\x00password"),
        ):
            with self.subTest(field=field):
                payload = {**self.payload, field: value}
                self.assertEqual(self.client.post("/api/instances/", payload, format="json").status_code, 400)

    def test_deleting_used_department_or_cluster_returns_conflict(self):
        self.client.post("/api/instances/", self.payload, format="json")
        for url in (f"/api/departments/{self.department.id}/", f"/api/clusters/{self.cluster.id}/"):
            self.assertEqual(self.client.delete(url).status_code, 409)

    def test_invalid_foreign_key(self):
        self.payload["department"] = 99999
        self.assertEqual(self.client.post("/api/instances/", self.payload, format="json").status_code, 400)

    def test_connection_change_requires_new_credentials(self):
        instance = make_instance()
        url = f"/api/instances/{instance.id}/"
        self.assertEqual(self.client.patch(url, {"port": 6543}).status_code, 400)
        response = self.client.patch(url, {"port": 6543, "password": "registered-password"})
        self.assertEqual(response.status_code, 200)
        instance.refresh_from_db()
        self.assertEqual(decrypt_password(instance.encrypted_password), "registered-password")
        self.assertEqual(self.client.patch(url, {"password": "only-local"}).status_code, 400)

    def test_pending_rotation_prevents_edit_and_delete(self):
        instance = make_instance()
        prepare_rotation(instance.id, force=True)
        url = f"/api/instances/{instance.id}/"
        self.assertEqual(self.client.patch(url, {"rotation_enabled": False}).status_code, 409)
        self.assertEqual(self.client.delete(url).status_code, 409)

    def test_tcp_action_only_probes_registered_endpoint(self):
        instance = make_instance()
        with patch(
            "inventory.views.probe_tcp", return_value={"reachable": False, "error": "timeout"}
        ) as probe:
            response = self.client.post(f"/api/instances/{instance.id}/probe/", {"host": "8.8.8.8"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["reachable"])
        probe.assert_called_once_with(instance.host, instance.port)

    def test_manual_rotation_returns_202_and_enqueues_only_id(self):
        instance = make_instance()
        with patch("inventory.views.rotate_instance_password.delay") as enqueue:
            response = self.client.post(f"/api/instances/{instance.id}/rotate-password/")
        self.assertEqual(response.status_code, 202)
        enqueue.assert_called_once_with(str(response.data["id"]))
        self.assertNotIn(b"encrypted_password", response.content)

    def test_broker_failure_preserves_recoverable_journal(self):
        instance = make_instance()
        with patch("inventory.views.rotate_instance_password.delay", side_effect=BrokerError("unavailable")):
            response = self.client.post(f"/api/instances/{instance.id}/rotate-password/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(instance.rotations.filter(status="pending").count(), 1)

    def test_rotation_history_is_readonly_and_survives_deletion(self):
        instance = make_instance()
        rotation = prepare_rotation(instance.id, force=True)
        rotation.status = PasswordRotation.Status.SUCCEEDED
        rotation.save()
        self.assertEqual(self.client.delete(f"/api/instances/{instance.id}/").status_code, 204)
        rotation.refresh_from_db()
        self.assertIsNone(rotation.instance_id)
        response = self.client.get(f"/api/rotations/{rotation.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"encrypted_password", response.content)
        self.assertEqual(self.client.delete(f"/api/rotations/{rotation.id}/").status_code, 405)

    def test_invalid_query_parameters_return_400(self):
        for url in (
            "/api/instances/?department=no",
            "/api/instances/?rotation_enabled=maybe",
            "/api/statistics/?snapshot_date=bad-date",
            "/api/statistics/?dimension=unknown",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 400)

    def test_request_duration_headers_on_success_and_error(self):
        for url, expected in (("/api/instances/", 200), ("/missing/", 404)):
            response = self.client.get(url)
            self.assertEqual(response.status_code, expected)
            self.assertGreaterEqual(float(response["X-Request-Duration-Ms"]), 0)
            self.assertEqual(len(response["X-Request-ID"]), 32)
