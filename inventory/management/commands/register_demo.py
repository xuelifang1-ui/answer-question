import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventory.models import Cluster, Department, Instance
from inventory.services.crypto import encrypt_password
from inventory.services.network import validate_target
from inventory.services.rotation import ROTATION_INTERVAL


class Command(BaseCommand):
    help = "登记 Compose 演示目标，不会覆盖已登记实例的密码"

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.getenv("DEMO_APP_PASSWORD")
        if not password:
            raise CommandError("缺少 DEMO_APP_PASSWORD，请先生成 .env")
        department, _ = Department.objects.get_or_create(code="rd", defaults={"name": "研发部"})
        cluster, _ = Cluster.objects.get_or_create(code="dev", defaults={"name": "开发集群"})
        now = timezone.now()
        instance, created = Instance.objects.get_or_create(
            host=validate_target(os.getenv("DEMO_TARGET_IP", "172.30.66.10")),
            port=5432,
            defaults={
                "name": "演示 PostgreSQL",
                "department": department,
                "cluster": cluster,
                "database": "demo",
                "username": "managed_app",
                "encrypted_password": encrypt_password(password),
                "password_changed_at": now,
                "next_rotation_at": now + ROTATION_INTERVAL,
            },
        )
        self.stdout.write(f"instance_id={instance.id}, created={created}")
