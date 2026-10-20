from django.core.management.base import BaseCommand

from inventory.services.statistics import collect_snapshot


class Command(BaseCommand):
    help = "采集今天的实例快照；已有记录时不覆盖"

    def handle(self, *args, **options):
        snapshot, created = collect_snapshot()
        self.stdout.write(f"{snapshot.snapshot_date}: total={snapshot.total_instances}, created={created}")
