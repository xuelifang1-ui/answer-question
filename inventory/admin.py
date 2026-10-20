from django.contrib import admin

from .models import Cluster, DailySnapshot, Department, Instance, InstanceStatistic, PasswordRotation

admin.site.register(Department)
admin.site.register(Cluster)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Instance)
class InstanceAdmin(ReadOnlyAdmin):
    list_display = ("name", "host", "port", "department", "cluster", "next_rotation_at")
    list_filter = ("department", "cluster", "rotation_enabled")
    exclude = ("encrypted_password",)


@admin.register(PasswordRotation)
class PasswordRotationAdmin(ReadOnlyAdmin):
    list_display = ("id", "instance_name", "status", "attempts", "last_error", "created_at")
    exclude = ("encrypted_password",)


@admin.register(DailySnapshot)
class SnapshotAdmin(ReadOnlyAdmin):
    list_display = ("snapshot_date", "captured_at", "total_instances")


@admin.register(InstanceStatistic)
class StatisticAdmin(ReadOnlyAdmin):
    list_display = ("snapshot", "dimension", "department_code", "cluster_code", "instance_count")
