import socket
import string
from unittest.mock import patch

from cryptography.fernet import InvalidToken
from django.test import SimpleTestCase, override_settings

from inventory.services.crypto import decrypt_password, encrypt_password, generate_password
from inventory.services.network import TargetNotAllowed, probe_tcp, validate_target


class CryptoTests(SimpleTestCase):
    def test_password_round_trip_preserves_spaces_and_unicode(self):
        value = "  密码 ' \\ \n测试  "
        first, second = encrypt_password(value), encrypt_password(value)
        self.assertNotEqual(first, second)
        self.assertNotIn(value, first)
        self.assertEqual(decrypt_password(first), value)

    def test_invalid_ciphertext_fails_closed(self):
        with self.assertRaises(InvalidToken):
            decrypt_password("not-a-token")

    def test_generated_password_contains_all_required_categories(self):
        value = generate_password()
        self.assertEqual(len(value), 32)
        for group in (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*_-+"):
            self.assertTrue(set(value) & set(group))

    def test_rejects_short_generated_password(self):
        with self.assertRaises(ValueError):
            generate_password(8)


class NetworkTests(SimpleTestCase):
    @override_settings(TARGET_ALLOWED_CIDRS=["127.0.0.1/32"])
    def test_real_tcp_probe(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            result = probe_tcp("127.0.0.1", listener.getsockname()[1])
        self.assertTrue(result["reachable"])
        self.assertEqual(result["error"], "")
        self.assertGreaterEqual(result["duration_ms"], 0)

    def test_probe_handles_timeout_refusal_and_other_network_errors(self):
        for exception, error in [
            (TimeoutError(), "timeout"),
            (ConnectionRefusedError(), "connection_refused"),
            (OSError(), "network_error"),
        ]:
            with (
                self.subTest(error=error),
                patch("inventory.services.network.socket.create_connection", side_effect=exception),
            ):
                result = probe_tcp("127.0.0.1", 5432)
                self.assertFalse(result["reachable"])
                self.assertEqual(result["error"], error)

    @override_settings(TARGET_ALLOWED_CIDRS=["127.0.0.1/32", "::1/128"])
    def test_rejects_metadata_address_and_hostnames(self):
        for host in ("169.254.169.254", "8.8.8.8", "example.com"):
            with self.subTest(host=host), self.assertRaises(TargetNotAllowed):
                validate_target(host)
        self.assertEqual(validate_target("::1"), "::1")

    @override_settings(TARGET_ALLOWED_CIDRS=["invalid-cidr"])
    def test_invalid_policy_fails_closed(self):
        with self.assertRaises(TargetNotAllowed):
            validate_target("127.0.0.1")

    def test_socket_is_closed(self):
        with patch("inventory.services.network.socket.create_connection") as connect:
            probe_tcp("127.0.0.1", 5432)
            connect.return_value.__exit__.assert_called_once()
