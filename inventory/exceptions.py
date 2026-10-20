from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler


class Conflict(APIException):
    status_code = 409
    default_detail = "当前状态不允许此操作"
    default_code = "conflict"


def api_exception_handler(exc, context):
    if isinstance(exc, ProtectedError):
        return Response({"detail": "仍有实例引用该记录，请先迁移或删除实例"}, status=409)
    if isinstance(exc, IntegrityError):
        return Response({"detail": "记录与现有数据冲突，请检查编号或实例地址"}, status=409)
    return exception_handler(exc, context)
