"""
backend/middleware.py
JAKAL API middleware — timing headers and security response headers.
"""

import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class TimingAndSecurityMiddleware(BaseHTTPMiddleware):
    """Adds processing-time measurement and hardened response headers."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response
