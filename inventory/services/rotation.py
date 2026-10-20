from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from inventory.models import Instance, PasswordRotation

from .crypto import decrypt_password, encrypt_password, generate_password
from .postgresql import RemoteRotationError, ensure_remote_password

ROTATION_INTERVAL = timedelta(hours=12)


class RotationBackendError(RuntimeError):
    pass


def require_row_locks():
    if connection.vendor != "postgresql" and not getattr(settings, "ALLOW_SQLITE_ROTATION_FOR_TESTS", False):
        raise RotationBackendError("密码轮换需要 PostgreSQL 管理库，请勿使用 SQLite 启动 worker")


def prepare_rotation(instance_id, *, force=False, requested_by="scheduler"):
    require_row_locks()
    with transaction.atomic():
        instance = Instance.objects.select_for_update().filter(pk=instance_id).first()
        if instance is None:
            return None
        pending = instance.rotations.filter(status=PasswordRotation.Status.PENDING).first()
        if pending:
            return pending
        if not force and (not instance.rotation_enabled or instance.next_rotation_at > timezone.now()):
            return None
        endpoint = (
            f"[{instance.host}]:{instance.port}"
            if ":" in instance.host
            else f"{instance.host}:{instance.port}"
        )
        return PasswordRotation.objects.create(
            instance=instance,
            instance_name=instance.name,
            endpoint=endpoint,
            username=instance.username,
            encrypted_password=encrypt_password(generate_password()),
            requested_by=requested_by,
        )


def apply_rotation(rotation_id):
    require_row_locks()
    # 加锁顺序固定为实例 -> 轮换记录，与编辑、删除操作一致。
    instance_id = PasswordRotation.objects.values_list("instance_id", flat=True).get(pk=rotation_id)
    if instance_id is None:
        return "deleted"
    with transaction.atomic():
        instance = Instance.objects.select_for_update().filter(pk=instance_id).first()
        if instance is None:
            return "deleted"
        rotation = PasswordRotation.objects.select_for_update().get(pk=rotation_id)
        if rotation.status == PasswordRotation.Status.SUCCEEDED:
            return "succeeded"
        rotation.attempts += 1
        try:
            ensure_remote_password(instance, decrypt_password(rotation.encrypted_password))
        except RemoteRotationError as exc:
            rotation.last_error = str(exc)
            rotation.save(update_fields=["attempts", "last_error"])
            return "pending"

        now = timezone.now()
        instance.encrypted_password = rotation.encrypted_password
        instance.password_changed_at = now
        instance.next_rotation_at = now + ROTATION_INTERVAL
        instance.save(
            update_fields=["encrypted_password", "password_changed_at", "next_rotation_at", "updated_at"]
        )
        rotation.status = PasswordRotation.Status.SUCCEEDED
        rotation.completed_at = now
        rotation.last_error = ""
        rotation.save(update_fields=["status", "completed_at", "attempts", "last_error"])
        return "succeeded"
