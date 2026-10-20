from celery import shared_task
from django.db import OperationalError
from django.db.models import Q
from django.utils import timezone

from .models import Instance, PasswordRotation
from .services.rotation import apply_rotation, prepare_rotation
from .services.statistics import collect_snapshot


class RotationPending(Exception):
    pass


@shared_task(bind=True, max_retries=3)
def rotate_instance_password(self, rotation_id):
    try:
        status = apply_rotation(rotation_id)
    except PasswordRotation.DoesNotExist:
        return "deleted"
    if status == "pending":
        raise self.retry(
            exc=RotationPending("目标密码尚未确认，保留原候选密码重试"),
            countdown=min(60 * (2**self.request.retries), 600),
        )
    return status


@shared_task
def dispatch_due_rotations():
    ids = (
        Instance.objects.filter(
            Q(rotation_enabled=True, next_rotation_at__lte=timezone.now())
            | Q(rotations__status=PasswordRotation.Status.PENDING)
        )
        .order_by("id")
        .values_list("id", flat=True)
        .distinct()
    )
    dispatched = 0
    for instance_id in ids.iterator(chunk_size=200):
        rotation = prepare_rotation(instance_id)
        if rotation:
            # 候选密码事务已提交；队列发送失败也可由下一次巡检恢复。
            rotate_instance_password.delay(str(rotation.id))
            dispatched += 1
    return dispatched


@shared_task(autoretry_for=(OperationalError,), retry_backoff=True, max_retries=3)
def collect_daily_statistics():
    snapshot, created = collect_snapshot()
    return {"snapshot_date": snapshot.snapshot_date.isoformat(), "created": created}
