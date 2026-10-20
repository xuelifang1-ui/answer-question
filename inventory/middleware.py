import logging
import time
import uuid

logger = logging.getLogger("request.timing")


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        status_code = 500
        try:
            response = self.get_response(request)
            status_code = response.status_code
            response["X-Request-ID"] = request_id
            response["X-Request-Duration-Ms"] = f"{(time.perf_counter() - started) * 1000:.3f}"
            return response
        finally:
            logger.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.3f",
                request_id,
                request.method,
                request.path,
                status_code,
                (time.perf_counter() - started) * 1000,
            )
