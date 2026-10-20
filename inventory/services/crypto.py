import secrets
import string

from cryptography.fernet import Fernet
from django.conf import settings


def encrypt_password(plaintext):
    return Fernet(settings.FERNET_KEY.encode("ascii")).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_password(ciphertext):
    return Fernet(settings.FERNET_KEY.encode("ascii")).decrypt(ciphertext.encode("ascii")).decode("utf-8")


def generate_password(length=32):
    if length < 16:
        raise ValueError("密码长度至少为 16")
    groups = (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*_-+")
    chars = [secrets.choice(group) for group in groups]
    chars.extend(secrets.choice("".join(groups)) for _ in range(length - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
