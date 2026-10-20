from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from inventory.middleware import RequestTimingMiddleware


class MiddlewareTests(SimpleTestCase):
    def test_uses_monotonic_clock_and_does_not_log_query_or_body(self):
        request = RequestFactory().post("/api/instances/?password=query-secret", {"password": "body-secret"})
        middleware = RequestTimingMiddleware(lambda _: HttpResponse(status=201))
        with patch("inventory.middleware.time.perf_counter", side_effect=[5.0, 5.125, 5.126]):
            with patch("inventory.middleware.logger.info") as log:
                response = middleware(request)
        self.assertEqual(response["X-Request-Duration-Ms"], "125.000")
        self.assertNotIn("secret", str(log.call_args))

    def test_exception_path_is_also_timed(self):
        def fail(_):
            raise ValueError("simulated")

        with patch("inventory.middleware.logger.info") as log:
            with self.assertRaises(ValueError):
                RequestTimingMiddleware(fail)(RequestFactory().get("/failure/"))
        self.assertEqual(log.call_args.args[4], 500)
