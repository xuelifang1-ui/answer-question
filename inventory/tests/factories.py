from datetime import timedelta
from itertools import count

from django.utils import timezone

from inventory.models import Cluster, Department, Instance
from inventory.services.crypto import encrypt_password

sequence = count(1)


def make_instance(**overrides):
    number = next(sequence)
    department = overrides.pop("department", None) or Department.objects.create(
        code=f"d{number}", name="研发部"
    )
    cluster = overrides.pop("cluster", None) or Cluster.objects.create(code=f"c{number}", name="开发集群")
    now = timezone.now()
    defaults = {
        "name": f"instance-{number}",
        "department": department,
        "cluster": cluster,
        "host": "127.0.0.1",
        "port": 10000 + number,
        "database": "postgres",
        "username": "managed_user",
        "encrypted_password": encrypt_password("initial-password"),
        "password_changed_at": now,
        "next_rotation_at": now + timedelta(hours=12),
    }
    defaults.update(overrides)
    return Instance.objects.create(**defaults)
