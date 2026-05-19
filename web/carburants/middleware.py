import logging
import time

logger = logging.getLogger("carburants.requests")


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000)

        raw_qs = request.META.get("QUERY_STRING", "")
        qs = f"?{raw_qs}" if raw_qs else ""
        ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "-"))
        logger.info(
            "%s %s%s → %d (%dms) [%s]",
            request.method,
            request.path,
            qs,
            response.status_code,
            duration_ms,
            ip,
        )
        return response
