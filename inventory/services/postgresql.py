import psycopg
from django.conf import settings
from psycopg import sql

from .crypto import decrypt_password
from .network import TargetNotAllowed, validate_target


class RemoteRotationError(Exception):
    """只携带可公开的错误代码，避免数据库异常带出连接凭据。"""


def connect_target(instance, password):
    connection = psycopg.connect(
        host=validate_target(instance.host),
        port=instance.port,
        dbname=instance.database,
        user=instance.username,
        password=password,
        connect_timeout=settings.TARGET_CONNECT_TIMEOUT,
        sslmode=settings.TARGET_SSLMODE,
        options="-c statement_timeout=5000 -c lock_timeout=3000",
        autocommit=True,
        application_name="instance_manager_rotation",
    )
    if not connection.pgconn.used_password:
        connection.close()
        raise RemoteRotationError("password_auth_required")
    return connection


def ensure_remote_password(instance, candidate):
    try:
        # 上次可能已改好远端、尚未提交本地事务；先用同一候选密码恢复。
        try:
            with connect_target(instance, candidate):
                return
        except psycopg.Error:
            pass

        with connect_target(instance, decrypt_password(instance.encrypted_password)) as connection:
            # 发送 SCRAM 校验值，避免 ALTER ROLE 语句携带明文密码。
            verifier = connection.pgconn.encrypt_password(
                candidate.encode("utf-8"), instance.username.encode("utf-8"), b"scram-sha-256"
            ).decode("ascii")
            connection.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(instance.username), sql.Literal(verifier)
                )
            )
        with connect_target(instance, candidate):
            pass
    except TargetNotAllowed as exc:
        raise RemoteRotationError("target_not_allowed") from exc
    except psycopg.Error as exc:
        raise RemoteRotationError("target_database_error") from exc
