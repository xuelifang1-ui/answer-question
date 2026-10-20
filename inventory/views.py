from django.db import transaction
from kombu.exceptions import OperationalError as BrokerError
from redis.exceptions import RedisError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .exceptions import Conflict
from .models import Cluster, DailySnapshot, Department, Instance, InstanceStatistic, PasswordRotation
from .serializers import (
    ClusterSerializer,
    DepartmentSerializer,
    InstanceSerializer,
    RotationSerializer,
    SnapshotSerializer,
    StatisticSerializer,
)
from .services.network import TargetNotAllowed, probe_tcp
from .services.rotation import RotationBackendError, prepare_rotation
from .tasks import rotate_instance_password


def filter_param(queryset, request, parameter, field, *, lookup=None):
    if parameter not in request.query_params:
        return queryset
    try:
        value = field.run_validation(request.query_params[parameter])
    except serializers.ValidationError as exc:
        raise serializers.ValidationError({parameter: exc.detail}) from exc
    return queryset.filter(**{lookup or parameter: value})


class CrudViewSet(viewsets.ModelViewSet):
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in {"update", "partial_update", "destroy"}:
            queryset = queryset.select_for_update(of=("self",))
        return queryset


class DepartmentViewSet(CrudViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer


class ClusterViewSet(CrudViewSet):
    queryset = Cluster.objects.all()
    serializer_class = ClusterSerializer


class InstanceViewSet(CrudViewSet):
    queryset = Instance.objects.select_related("department", "cluster")
    serializer_class = InstanceSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        for parameter in ("department", "cluster"):
            queryset = filter_param(queryset, self.request, parameter, serializers.IntegerField(min_value=1))
        return filter_param(queryset, self.request, "rotation_enabled", serializers.BooleanField())

    def perform_destroy(self, instance):
        if instance.rotations.filter(status=PasswordRotation.Status.PENDING).exists():
            raise Conflict("密码轮换尚未完成，请先处理轮换记录再删除实例")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="probe")
    def probe(self, request, pk=None):
        instance = self.get_object()
        try:
            result = probe_tcp(instance.host, instance.port)
        except TargetNotAllowed as exc:
            raise serializers.ValidationError({"host": str(exc)}) from exc
        return Response({"instance_id": instance.id, **result})

    @action(detail=True, methods=["post"], url_path="rotate-password")
    def rotate_password(self, request, pk=None):
        instance = self.get_object()
        try:
            rotation = prepare_rotation(instance.id, force=True, requested_by=request.user.get_username())
        except RotationBackendError as exc:
            return Response({"detail": str(exc)}, status=503)
        if rotation is None:
            return Response({"detail": "实例已被删除"}, status=404)
        try:
            rotate_instance_password.delay(str(rotation.id))
        except (BrokerError, RedisError):
            return Response(
                {
                    "detail": "队列暂不可用，轮换记录已保存，巡检任务会继续调度",
                    "rotation_id": str(rotation.id),
                },
                status=503,
            )
        return Response(RotationSerializer(rotation).data, status=status.HTTP_202_ACCEPTED)


class RotationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PasswordRotation.objects.all()
    serializer_class = RotationSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = filter_param(queryset, self.request, "instance", serializers.IntegerField(min_value=1))
        return filter_param(
            queryset, self.request, "status", serializers.ChoiceField(choices=PasswordRotation.Status.choices)
        )


class SnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DailySnapshot.objects.all()
    serializer_class = SnapshotSerializer

    def get_queryset(self):
        return filter_param(super().get_queryset(), self.request, "snapshot_date", serializers.DateField())


class StatisticViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = InstanceStatistic.objects.select_related("snapshot")
    serializer_class = StatisticSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = filter_param(
            queryset, self.request, "snapshot_date", serializers.DateField(), lookup="snapshot__snapshot_date"
        )
        queryset = filter_param(
            queryset,
            self.request,
            "dimension",
            serializers.ChoiceField(choices=InstanceStatistic.Dimension.choices),
        )
        for parameter in ("department_code", "cluster_code"):
            queryset = filter_param(queryset, self.request, parameter, serializers.SlugField(max_length=64))
        return queryset
