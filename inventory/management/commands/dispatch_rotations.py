from django.core.management.base import BaseCommand

from inventory.tasks import dispatch_due_rotations


class Command(BaseCommand):
    help = "立即扫描到期实例和未完成轮换，并投递到 Celery 队列"

    def handle(self, *args, **options):
        count = dispatch_due_rotations()
        self.stdout.write(f"dispatched={count}")
