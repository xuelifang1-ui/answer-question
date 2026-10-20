from django.utils import timezone
from rest_framework import serializers

from .exceptions import Conflict
from .models import Cluster, DailySnapshot, Department, Instance, InstanceStatistic, PasswordRotation
from .services.crypto import encrypt_password
from .services.network import TargetNotAllowed, validate_target
from .services.rotation import ROTATION_INTERVAL


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "code", "name", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClusterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cluster
        fields = ["id", "code", "name", "description", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class InstanceSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=False, min_length=1, max_length=1024, trim_whitespace=False
    )
    department_name = serializers.CharField(source="department.name", read_only=True)
    cluster_name = serializers.CharField(source="cluster.name", read_only=True)

    class Meta:
        model = Instance
        fields = [
            "id",
            "name",
            "department",
            "department_name",
            "cluster",
            "cluster_name",
            "host",
            "port",
            "database",
            "username",
            "password",
            "rotation_enabled",
            "password_changed_at",
            "next_rotation_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "password_changed_at", "next_rotation_at", "created_at", "updated_at"]

    def validate_host(self, value):
        try:
            return validate_target(value)
        except TargetNotAllowed as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        for field in ("username", "database", "password"):
            value = attrs.get(field)
            if value is not None and "\x00" in value:
                raise serializers.ValidationError({field: "不允许包含空字符"})
            if field != "password" and value is not None and len(value.encode("utf-8")) > 63:
                raise serializers.ValidationError({field: "PostgreSQL 标识符不能超过 63 字节"})
        if self.instance is None:
            if "password" not in attrs:
                raise serializers.ValidationError({"password": "登记实例时必须提供当前密码"})
        else:
            if self.instance.rotations.filter(status=PasswordRotation.Status.PENDING).exists():
                raise Conflict("密码轮换尚未完成，请先处理轮换记录再编辑实例")
            connection_changed = any(
                field in attrs and attrs[field] != getattr(self.instance, field)
                for field in ("host", "port", "database", "username")
            )
            if connection_changed and "password" not in attrs:
                raise serializers.ValidationError({"password": "变更连接信息时必须重新登记当前密码"})
            if not connection_changed and "password" in attrs:
                raise serializers.ValidationError({"password": "请使用 rotate-password 接口修改目标库密码"})
        return attrs

    def _apply_password(self, validated_data):
        password = validated_data.pop("password", None)
        if password is not None:
            now = timezone.now()
            validated_data.update(
                encrypted_password=encrypt_password(password),
                password_changed_at=now,
                next_rotation_at=now + ROTATION_INTERVAL,
            )

    def create(self, validated_data):
        self._apply_password(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._apply_password(validated_data)
        return super().update(instance, validated_data)


class RotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PasswordRotation
        fields = [
            "id",
            "instance",
            "instance_name",
            "endpoint",
            "username",
            "status",
            "attempts",
            "last_error",
            "requested_by",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields


class SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySnapshot
        fields = ["id", "snapshot_date", "captured_at", "total_instances"]
        read_only_fields = fields


class StatisticSerializer(serializers.ModelSerializer):
    snapshot_date = serializers.DateField(source="snapshot.snapshot_date", read_only=True)

    class Meta:
        model = InstanceStatistic
        fields = [
            "id",
            "snapshot",
            "snapshot_date",
            "dimension",
            "department_code",
            "department_name",
            "cluster_code",
            "cluster_name",
            "instance_count",
        ]
        read_only_fields = fields
