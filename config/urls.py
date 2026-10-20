from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from inventory.views import (
    ClusterViewSet,
    DepartmentViewSet,
    InstanceViewSet,
    RotationViewSet,
    SnapshotViewSet,
    StatisticViewSet,
)

router = DefaultRouter()
router.register("departments", DepartmentViewSet)
router.register("clusters", ClusterViewSet)
router.register("instances", InstanceViewSet)
router.register("rotations", RotationViewSet)
router.register("snapshots", SnapshotViewSet)
router.register("statistics", StatisticViewSet)
urlpatterns = [path("admin/", admin.site.urls), path("api/", include(router.urls))]
