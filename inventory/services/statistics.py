from collections import Counter

from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import Count
from django.utils import timezone

from inventory.models import Cluster, DailySnapshot, Department, Instance, InstanceStatistic


def collect_snapshot():
    captured_at = timezone.now()
    snapshot_date = timezone.localdate(captured_at)
    try:
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            existing = DailySnapshot.objects.filter(snapshot_date=snapshot_date).first()
            if existing:
                return existing, False
            departments = {row.id: row for row in Department.objects.all()}
            clusters = {row.id: row for row in Cluster.objects.all()}
            groups = list(
                Instance.objects.order_by()
                .values("department_id", "cluster_id")
                .annotate(instance_count=Count("id"))
            )
            snapshot = DailySnapshot.objects.create(
                snapshot_date=snapshot_date,
                captured_at=captured_at,
                total_instances=sum(group["instance_count"] for group in groups),
            )
            department_counts, cluster_counts = Counter(), Counter()
            statistics = []
            for group in groups:
                department = departments[group["department_id"]]
                cluster = clusters[group["cluster_id"]]
                count = group["instance_count"]
                department_counts[department.id] += count
                cluster_counts[cluster.id] += count
                statistics.append(
                    InstanceStatistic(
                        snapshot=snapshot,
                        dimension=InstanceStatistic.Dimension.DEPARTMENT_CLUSTER,
                        department_code=department.code,
                        department_name=department.name,
                        cluster_code=cluster.code,
                        cluster_name=cluster.name,
                        instance_count=count,
                    )
                )
            for department in departments.values():
                statistics.append(
                    InstanceStatistic(
                        snapshot=snapshot,
                        dimension=InstanceStatistic.Dimension.DEPARTMENT,
                        department_code=department.code,
                        department_name=department.name,
                        instance_count=department_counts[department.id],
                    )
                )
            for cluster in clusters.values():
                statistics.append(
                    InstanceStatistic(
                        snapshot=snapshot,
                        dimension=InstanceStatistic.Dimension.CLUSTER,
                        cluster_code=cluster.code,
                        cluster_name=cluster.name,
                        instance_count=cluster_counts[cluster.id],
                    )
                )
            InstanceStatistic.objects.bulk_create(statistics)
            return snapshot, True
    except (IntegrityError, OperationalError):
        # 并发插入同一天快照时，让已经成功的事务成为唯一结果。
        existing = DailySnapshot.objects.filter(snapshot_date=snapshot_date).first()
        if existing:
            return existing, False
        raise
