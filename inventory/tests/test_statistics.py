from datetime import UTC, datetime
from unittest.mock import patch

from django.test import TransactionTestCase

from inventory.models import Cluster, DailySnapshot, Department, InstanceStatistic
from inventory.services.statistics import collect_snapshot

from .factories import make_instance


class StatisticsTests(TransactionTestCase):
    def setUp(self):
        self.department = Department.objects.create(code="rd", name="研发部")
        self.cluster = Cluster.objects.create(code="dev", name="开发集群")

    def test_three_dimensions_and_zero_counts(self):
        other_department = Department.objects.create(code="qa", name="测试部")
        other_cluster = Cluster.objects.create(code="qa", name="测试集群")
        for _ in range(2):
            make_instance(department=self.department, cluster=self.cluster)
        make_instance(department=other_department, cluster=self.cluster)
        snapshot, created = collect_snapshot()
        self.assertTrue(created)
        self.assertEqual(snapshot.total_instances, 3)
        self.assertEqual(
            snapshot.statistics.get(dimension="department", department_code="rd").instance_count, 2
        )
        self.assertEqual(snapshot.statistics.get(dimension="cluster", cluster_code="dev").instance_count, 3)
        self.assertEqual(
            snapshot.statistics.get(dimension="cluster", cluster_code=other_cluster.code).instance_count, 0
        )
        self.assertEqual(
            snapshot.statistics.get(
                dimension="department_cluster", department_code="qa", cluster_code="dev"
            ).instance_count,
            1,
        )
        for dimension in ("department", "cluster", "department_cluster"):
            total = sum(
                snapshot.statistics.filter(dimension=dimension).values_list("instance_count", flat=True)
            )
            self.assertEqual(total, snapshot.total_instances)

    def test_repeat_does_not_overwrite_first_snapshot(self):
        first, _ = collect_snapshot()
        make_instance()
        second, created = collect_snapshot()
        self.assertFalse(created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.total_instances, 0)

    def test_beijing_date_at_utc_boundary(self):
        with patch(
            "inventory.services.statistics.timezone.now",
            return_value=datetime(2026, 10, 20, 16, 0, tzinfo=UTC),
        ):
            snapshot, _ = collect_snapshot()
        self.assertEqual(snapshot.snapshot_date.isoformat(), "2026-10-21")

    def test_historical_names_survive_renames_and_deletes(self):
        instance = make_instance(department=self.department, cluster=self.cluster)
        snapshot, _ = collect_snapshot()
        instance.delete()
        self.department.delete()
        self.cluster.delete()
        row = snapshot.statistics.get(dimension="department_cluster")
        self.assertEqual(row.department_name, "研发部")
        self.assertEqual(row.cluster_code, "dev")

    def test_partial_snapshot_is_rolled_back(self):
        with patch.object(InstanceStatistic.objects, "bulk_create", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                collect_snapshot()
        self.assertEqual(DailySnapshot.objects.count(), 0)
        self.assertTrue(collect_snapshot()[1])
