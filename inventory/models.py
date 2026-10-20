import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Department(TimestampedModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.code} / {self.name}"


class Cluster(TimestampedModel):
    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.code} / {self.name}"


class Instance(TimestampedModel):
    name = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="instances")
    cluster = models.ForeignKey(Cluster, on_delete=models.PROTECT, related_name="instances")
    host = models.GenericIPAddressField()
    port = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(65535)])
    database = models.CharField(max_length=63, default="postgres")
    username = models.CharField(max_length=63)
    encrypted_password = models.TextField(editable=False)
    rotation_enabled = models.BooleanField(default=True)
    password_changed_at = models.DateTimeField()
    next_rotation_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["host", "port"], name="unique_instance_endpoint"),
            models.CheckConstraint(condition=Q(port__gte=1, port__lte=65535), name="valid_tcp_port"),
        ]

    def __str__(self):
        return f"{self.name} ({self.host}:{self.port})"


class PasswordRotation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待完成"
        SUCCEEDED = "succeeded", "已完成"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(Instance, null=True, on_delete=models.SET_NULL, related_name="rotations")
    instance_name = models.CharField(max_length=100)
    endpoint = models.CharField(max_length=100)
    username = models.CharField(max_length=63)
    encrypted_password = models.TextField(editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=64, blank=True)
    requested_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["instance"], condition=Q(status="pending"), name="one_pending_rotation_per_instance"
            ),
        ]


class DailySnapshot(models.Model):
    snapshot_date = models.DateField(unique=True)
    captured_at = models.DateTimeField()
    total_instances = models.PositiveIntegerField()

    class Meta:
        ordering = ["-snapshot_date"]


class InstanceStatistic(models.Model):
    class Dimension(models.TextChoices):
        DEPARTMENT = "department", "部门"
        CLUSTER = "cluster", "集群"
        DEPARTMENT_CLUSTER = "department_cluster", "部门与集群"

    snapshot = models.ForeignKey(DailySnapshot, on_delete=models.CASCADE, related_name="statistics")
    dimension = models.CharField(max_length=24, choices=Dimension.choices)
    department_code = models.CharField(max_length=64, blank=True, default="")
    department_name = models.CharField(max_length=100, blank=True, default="")
    cluster_code = models.CharField(max_length=64, blank=True, default="")
    cluster_name = models.CharField(max_length=100, blank=True, default="")
    instance_count = models.PositiveIntegerField()

    class Meta:
        ordering = ["-snapshot_id", "dimension", "department_code", "cluster_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "dimension", "department_code", "cluster_code"],
                name="unique_daily_dimension",
            )
        ]
