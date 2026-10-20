import ipaddress
import socket
import time

from django.conf import settings
from django.utils import timezone


class TargetNotAllowed(ValueError):
    pass


def validate_target(host):
    try:
        address = ipaddress.ip_address(host)
        allowed = any(address in ipaddress.ip_network(cidr) for cidr in settings.TARGET_ALLOWED_CIDRS)
    except ValueError as exc:
        raise TargetNotAllowed("目标地址或允许网段配置无效") from exc
    if not allowed:
        raise TargetNotAllowed("目标地址不在允许访问的网段内")
    return str(address)


def probe_tcp(host, port):
    address = validate_target(host)
    started = time.perf_counter()
    reachable, error = True, ""
    try:
        with socket.create_connection((address, port), timeout=settings.TCP_PROBE_TIMEOUT):
            pass
    except TimeoutError:
        reachable, error = False, "timeout"
    except ConnectionRefusedError:
        reachable, error = False, "connection_refused"
    except OSError:
        reachable, error = False, "network_error"
    return {
        "reachable": reachable,
        "error": error,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "checked_at": timezone.now().isoformat(),
    }
