import uuid
import time
import base64
import json
import logging
import re
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.core.ratelimit import RateLimitStorage
from app.core.config import settings

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Suspicious path patterns – typical bot scanner targets
# ---------------------------------------------------------------------------
SUSPICIOUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"\.env", re.IGNORECASE),
    re.compile(r"\.git", re.IGNORECASE),
    re.compile(r"etc/passwd", re.IGNORECASE),
    re.compile(r"phpunit", re.IGNORECASE),
    re.compile(r"eval-stdin", re.IGNORECASE),
    re.compile(r"cgi-bin", re.IGNORECASE),
    re.compile(r"xmlrpc\.php", re.IGNORECASE),
    re.compile(r"wp-login", re.IGNORECASE),
    re.compile(r"wp-admin", re.IGNORECASE),
    re.compile(r"\.aws", re.IGNORECASE),
    re.compile(r"terraform\.tfstate", re.IGNORECASE),
    re.compile(r"\.well-known/security", re.IGNORECASE),
    re.compile(r"actuator", re.IGNORECASE),
    re.compile(r"vendor/", re.IGNORECASE),
    re.compile(r"index\.php", re.IGNORECASE),
    re.compile(r"containers/json", re.IGNORECASE),
    re.compile(r"\.\.[\\/]", re.IGNORECASE),          # path traversal
    re.compile(r"%2e%2e", re.IGNORECASE),             # encoded path traversal
    re.compile(r"SDK/webLanguage", re.IGNORECASE),
    re.compile(r"/bin/sh", re.IGNORECASE),
]


def _is_suspicious(path: str) -> bool:
    """Return True when *path* matches any known scanner pattern."""
    return any(p.search(path) for p in SUSPICIOUS_PATTERNS)


# ---------------------------------------------------------------------------
# 1) Security Middleware – blocks scanners & bots before they reach the app
# ---------------------------------------------------------------------------
class SecurityMiddleware(BaseHTTPMiddleware):
    """Detects suspicious requests, auto-blocks repeat offenders, and writes
    fail2ban-compatible log lines."""

    def __init__(self, app: ASGIApp, storage: RateLimitStorage):
        super().__init__(app)
        self.storage = storage
        self.threshold = settings.rate_limit_suspicious_threshold
        self.block_seconds = settings.ip_block_duration_hours * 3600

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"

        # Already blocked? → instant 403
        if await self.storage.is_blocked(client_ip):
            log.warning(
                "[SECURITY] BLOCKED",
                ip=client_ip,
                path=request.url.path,
                reason="ip_blocked",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "ip_blocked",
                    "detail": "Your IP has been blocked due to suspicious activity.",
                },
            )

        # Suspicious path? → count strikes
        if _is_suspicious(request.url.path):
            strike_key = f"security:strikes:{client_ip}"
            strikes = await self.storage.hit(strike_key, ttl_seconds=300)  # 5 min window

            log.warning(
                "[SECURITY] SUSPICIOUS",
                ip=client_ip,
                path=request.url.path,
                strikes=strikes,
            )

            if strikes >= self.threshold:
                await self.storage.block_ip(client_ip, self.block_seconds)
                log.warning(
                    "[SECURITY] BLOCKED",
                    ip=client_ip,
                    path=request.url.path,
                    reason="threshold_exceeded",
                    block_hours=settings.ip_block_duration_hours,
                )

            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "suspicious_request",
                    "detail": "Forbidden.",
                },
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# 2) Request-ID Middleware
# ---------------------------------------------------------------------------
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        is_health_check = request.url.path in ["/health", "/health/"]
        is_stream = request.url.path.endswith("/stream")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            req=request_id[:8],
        )

        start_time = time.time()
        try:
             response = await call_next(request)
             process_time = time.time() - start_time

             status_code = response.status_code

             if not is_health_check and not is_stream:
                 log.info("request_finished",
                          method=request.method,
                          path=request.url.path,
                          status=status_code,
                          duration=round(process_time, 3),
                          request_id=request_id)

             response.headers["X-Request-ID"] = request_id
             return response
        except Exception as e:
            process_time = time.time() - start_time
            if not is_health_check:
                log.error("request_failed",
                          method=request.method,
                          path=request.url.path,
                          duration=round(process_time, 3),
                          error=str(e),
                          request_id=request_id)
            raise e


# ---------------------------------------------------------------------------
# 3) Rate-Limit Middleware – normal API rate limiting
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, storage: RateLimitStorage):
        super().__init__(app)
        self.storage = storage
        self.limit = settings.rate_limit_per_minute

    # SSE / streaming endpoints are long-lived single connections —
    # they should not be rate-limited per request.
    _EXEMPT_PATTERNS = ("/stream", "/events/", "/events")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip rate limiting for SSE / streaming endpoints
        if any(pat in path for pat in self._EXEMPT_PATTERNS):
            return await call_next(request)

        user_id = self._get_user_id(request)
        if not user_id:
            user_id = request.client.host if request.client else "unknown"

        key = f"ratelimit:{user_id}:{path}"

        try:
            current_count = await self.storage.hit(key, ttl_seconds=60)
            if current_count > self.limit:
                log.warning(f"Rate limit exceeded for {key}")
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_code": "rate_limit_exceeded",
                        "detail": "Too many requests. Please try again later.",
                        "request_id": getattr(request.state, "request_id", None)
                    }
                )
        except Exception as e:
            log.error(f"Rate limit storage error: {e}")
            pass

        return await call_next(request)

    def _get_user_id(self, request: Request) -> str | None:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header.split(" ")[1]
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += '=' * padding
            payload_json = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_json)
            return payload.get("sub")
        except Exception:
            return None
