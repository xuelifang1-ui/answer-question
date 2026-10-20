import os

from cryptography.fernet import Fernet

os.environ.setdefault("DJANGO_SECRET_KEY", "isolated-test-settings-only")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("DB_PASSWORD", "test-only")
os.environ.setdefault("DB_ENGINE", "sqlite")

from .settings import *  # noqa: E402,F403

if os.getenv("DB_ENGINE") == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
ALLOW_SQLITE_ROTATION_FOR_TESTS = True
LOGGING = {"version": 1, "disable_existing_loggers": True}
