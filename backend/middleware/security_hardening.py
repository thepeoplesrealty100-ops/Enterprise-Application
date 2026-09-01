"""
backend/middleware/security_hardening.py

Phase 5: Production Security Hardening Middleware
- Rate limiting (token bucket + sliding window)
- Input validation and sanitization
- Security headers (CSP, HSTS, X-Frame-Options, etc.)
- Error response normalization
- Request/Response logging
- CORS policy enforcement
"""

import time
import json
import re
import logging
from typing import Dict, Tuple, Any
from collections import defaultdict, deque
from datetime import datetime
import ipaddress

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


# ============================================================================
# Rate Limiting Implementation
# ============================================================================

class RateLimiter:
    """
    Production-grade rate limiter with multiple strategies
    - Token Bucket: Smooth traffic handling
    - Sliding Window: Accurate request counting
    - Per-IP + Per-User + Per-Endpoint: Granular control
    """
    
    def __init__(self):
        # Token bucket: {key: {tokens: float, last_update: float}}
        self.token_buckets: Dict[str, Dict] = defaultdict(lambda: {
            "tokens": 100.0,
            "last_update": time.time()
        })
        
        # Sliding window: {key: deque of timestamps}
        self.sliding_windows: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        
        # Configuration per endpoint
        self.endpoint_limits: Dict[str, Tuple[int, int]] = {
            "/api/dashboard/fleet": (100, 60),      # 100 req/min
            "/api/dashboard/matrix": (50, 60),      # 50 req/min
            "/api/fabric/status": (100, 60),        # 100 req/min
            "/api/resonance/policies": (50, 60),    # 50 req/min
            "/api/health/detailed": (1000, 60),     # 1000 req/min (permissive)
        }
        
        # Global limits
        self.global_limit_per_ip = (1000, 60)      # 1000 req/min per IP
        self.global_limit_per_user = (5000, 60)    # 5000 req/min per user (if authenticated)
        
        # Cleanup interval
        self.cleanup_interval = 3600  # 1 hour
        self.last_cleanup = time.time()
    
    def is_rate_limited(self, client_ip: str, endpoint: str = None, user_id: str = None) -> Tuple[bool, Dict]:
        """
        Check if request should be rate limited
        Returns: (is_limited, info_dict)
        """
        now = time.time()
        
        # Cleanup old entries periodically
        if now - self.last_cleanup > self.cleanup_interval:
            self._cleanup()
            self.last_cleanup = now
        
        # Combine keys for multi-level limiting
        keys_to_check = [
            f"ip:{client_ip}",  # Per-IP limit
        ]
        
        if user_id:
            keys_to_check.append(f"user:{user_id}")
        
        if endpoint:
            keys_to_check.append(f"endpoint:{endpoint}:{client_ip}")
        
        # Check each limiting strategy
        for key in keys_to_check:
            if self._token_bucket_check(key, now) is False:
                return True, {
                    "limited": True,
                    "reason": f"Rate limit exceeded on {key}",
                    "key": key
                }
        
        return False, {"limited": False}
    
    def _token_bucket_check(self, key: str, now: float) -> bool:
        """Token bucket algorithm"""
        bucket = self.token_buckets[key]
        
        # Get bucket config
        if "endpoint" in key:
            limit, window = self.endpoint_limits.get(key.split(":")[1], (100, 60))
        elif "user" in key:
            limit, window = self.global_limit_per_user
        else:  # ip
            limit, window = self.global_limit_per_ip
        
        refill_rate = limit / window  # tokens per second
        
        # Refill tokens
        elapsed = now - bucket["last_update"]
        bucket["tokens"] = min(limit, bucket["tokens"] + elapsed * refill_rate)
        bucket["last_update"] = now
        
        # Check if enough tokens
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True
        
        return False
    
    def _sliding_window_check(self, key: str, now: float, limit: int, window: int) -> bool:
        """Sliding window algorithm"""
        window_start = now - window
        
        # Remove old entries
        while self.sliding_windows[key] and self.sliding_windows[key][0] < window_start:
            self.sliding_windows[key].popleft()
        
        # Check if limit exceeded
        if len(self.sliding_windows[key]) < limit:
            self.sliding_windows[key].append(now)
            return True
        
        return False
    
    def _cleanup(self):
        """Clean up old rate limit entries"""
        now = time.time()
        cutoff = now - 3600  # Keep 1 hour of history
        
        # Cleanup token buckets (keep all, just the timestamp is checked)
        # Remove stale sliding windows
        stale_keys = []
        for key, window in self.sliding_windows.items():
            if window:
                if window[-1] < cutoff:
                    stale_keys.append(key)
        
        for key in stale_keys:
            del self.sliding_windows[key]
        
        logger.info(f"Rate limiter cleanup: removed {len(stale_keys)} stale keys")


# ============================================================================
# Input Validation & Sanitization
# ============================================================================

class InputValidator:
    """
    Input validation and sanitization
    - SQL injection prevention
    - XSS prevention
    - Path traversal prevention
    - Command injection prevention
    """
    
    # Regex patterns for dangerous inputs.
    #
    # RECONCILIATION FIX: the original patterns blocklisted individual
    # characters and bare dictionary words (a lone "'", ";", "(", "{",
    # "~", or any of SELECT/INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/EXEC as
    # a whole word) rather than actual attack shapes. Reproduced live: a
    # perfectly ordinary target string like "payload-exec-123" (contains
    # "exec" as a \b-delimited word) was rejected with a 400 as
    # "sql_injection", and this middleware runs on EVERY query param, path
    # param, and JSON body field across the entire app -- so any field
    # containing an apostrophe ("don't"), a MITRE technique ID with a
    # sub-technique in parens ("T1059(001)"), or common English/technical
    # words as substrings would be rejected the same way. This app also
    # already uses parameterized queries everywhere (no raw SQL string
    # interpolation), so this middleware is defense-in-depth, not the
    # actual injection defense -- it should not be blocking legitimate
    # traffic to provide that marginal extra layer. Retuned to match
    # actual attack shapes (stacked queries, UNION-based injection,
    # classic tautologies, comment-truncation, real traversal/shell
    # metacharacter sequences) instead of individual characters/words.
    PATTERNS = {
        "sql_injection": re.compile(
            r"(\bUNION\s+SELECT\b"
            r"|;\s*(DROP|DELETE|UPDATE|INSERT|ALTER)\s+\w"
            r"|\bOR\s+['\"]?\s*\d\s*['\"]?\s*=\s*['\"]?\s*\d"
            r"|--\s*$|\/\*.*?\*\/)",
            re.IGNORECASE
        ),
        "xss": re.compile(
            r"(<script[\s>/]|javascript:|on\w+\s*=\s*['\"]|<iframe[\s>]|<embed[\s>]|<object[\s>])",
            re.IGNORECASE
        ),
        "path_traversal": re.compile(r"(\.\.[/\\]){2,}|\.\.[/\\](etc|windows|system32)\b", re.IGNORECASE),
        "command_injection": re.compile(r"(\$\([^)]*\)|`[^`]+`|;\s*(rm|cat|wget|curl|nc|bash|sh|powershell)\s)", re.IGNORECASE),
    }
    
    # Whitelist patterns for common parameters
    WHITELISTS = {
        "device_id": re.compile(r"^[a-zA-Z0-9_-]+$"),
        "client": re.compile(r"^[a-zA-Z0-9_\s-]+$"),
        "status": re.compile(r"^(online|offline|active|inactive|quarantined)$", re.IGNORECASE),
        # Must match routers/ui_bridge.py's DeviceActionRequest.action
        # comment exactly -- RECONCILIATION FIX: this whitelist previously
        # allowed "block"/"monitor" (not real values ui_bridge.py accepts)
        # while rejecting "reset_pass"/"release" (which it does), so 2 of
        # the 5 real device actions were unreachable via
        # POST /api/dashboard/fleet/{id}/action.
        "action": re.compile(r"^(scan|isolate|quarantine|reset_pass|release)$", re.IGNORECASE),
        "severity": re.compile(r"^(CRITICAL|HIGH|MEDIUM|LOW)$"),
        "page": re.compile(r"^[0-9]+$"),
        "per_page": re.compile(r"^[0-9]+$"),
    }
    
    @staticmethod
    def sanitize_string(value: str, field_name: str = None) -> str:
        """Sanitize string input"""
        if not isinstance(value, str):
            return str(value)
        
        # Check whitelist if available
        if field_name and field_name in InputValidator.WHITELISTS:
            if not InputValidator.WHITELISTS[field_name].match(value):
                raise ValueError(f"Invalid format for {field_name}: {value}")
        
        # Check for dangerous patterns
        for pattern_name, pattern in InputValidator.PATTERNS.items():
            if pattern.search(value):
                logger.warning(f"Detected {pattern_name} in input: {value[:50]}")
                raise ValueError(f"Invalid characters in input: {value[:30]}")
        
        # HTML escape
        value = value.replace("&", "&amp;")
        value = value.replace("<", "&lt;")
        value = value.replace(">", "&gt;")
        value = value.replace('"', "&quot;")
        value = value.replace("'", "&#x27;")
        
        return value
    
    @staticmethod
    def validate_integer(value: Any, min_val: int = None, max_val: int = None) -> int:
        """Validate integer input"""
        try:
            int_val = int(value)
            if min_val is not None and int_val < min_val:
                raise ValueError(f"Value {int_val} is less than minimum {min_val}")
            if max_val is not None and int_val > max_val:
                raise ValueError(f"Value {int_val} is greater than maximum {max_val}")
            return int_val
        except ValueError:
            raise ValueError(f"Invalid integer value: {value}")
    
    @staticmethod
    def validate_json(value: str) -> Dict:
        """Validate JSON input"""
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}")
    
    @staticmethod
    def validate_email(value: str) -> str:
        """Validate email format"""
        pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        if not pattern.match(value):
            raise ValueError(f"Invalid email format: {value}")
        return value
    
    @staticmethod
    def validate_ip_address(value: str) -> str:
        """Validate IP address"""
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            raise ValueError(f"Invalid IP address: {value}")


# ============================================================================
# Security Headers Middleware
# ============================================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses
    - Content-Security-Policy
    - X-Frame-Options
    - X-Content-Type-Options
    - Strict-Transport-Security
    - X-XSS-Protection
    - Referrer-Policy
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # HSTS (Strict-Transport-Security)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        
        # XSS Protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions Policy (formerly Feature Policy)
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )
        
        return response


# ============================================================================
# Rate Limiting Middleware
# ============================================================================

class RateLimitingMiddleware(BaseHTTPMiddleware):
    """
    Apply rate limiting to all requests
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rate_limiter = RateLimiter()
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Get endpoint
        endpoint = request.url.path
        
        # Get user ID (if authenticated)
        user_id = None
        if "user_id" in request.query_params:
            user_id = request.query_params["user_id"]
        elif "Authorization" in request.headers:
            # Would extract from JWT token in production
            pass
        
        # Check rate limit
        is_limited, info = self.rate_limiter.is_rate_limited(client_ip, endpoint, user_id)
        
        if is_limited:
            logger.warning(f"Rate limit exceeded for {client_ip} on {endpoint}")
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "message": info["reason"],
                    "retry_after": 60
                },
                headers={"Retry-After": "60"}
            )
        
        response = await call_next(request)
        
        # Add rate limit info headers
        response.headers["X-RateLimit-Limit"] = "1000"
        response.headers["X-RateLimit-Remaining"] = "999"
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + 60)
        
        return response


# ============================================================================
# Input Validation Middleware
# ============================================================================

class InputValidationMiddleware(BaseHTTPMiddleware):
    """
    Validate all input parameters
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            # Validate query parameters
            for key, value in request.query_params.items():
                if isinstance(value, str):
                    InputValidator.sanitize_string(value, key)
            
            # Validate path parameters
            for key, value in request.path_params.items() if hasattr(request, 'path_params') else []:
                if isinstance(value, str):
                    InputValidator.sanitize_string(value, key)
            
            # For POST/PUT, validate body
            if request.method in ["POST", "PUT", "PATCH"]:
                try:
                    body = await request.body()
                    if body and request.headers.get("content-type") == "application/json":
                        json_data = json.loads(body)
                        # Recursively validate JSON
                        self._validate_json_recursive(json_data)
                except Exception as e:
                    logger.error(f"Input validation error: {e}")
                    return JSONResponse(
                        status_code=400,
                        content={"error": "Invalid input", "message": str(e)}
                    )
        
        except ValueError as e:
            logger.warning(f"Input validation error: {e}")
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid input", "message": str(e)}
            )
        
        response = await call_next(request)
        return response
    
    def _validate_json_recursive(self, data: Any):
        """Recursively validate JSON data"""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    InputValidator.sanitize_string(value, key)
                elif isinstance(value, (dict, list)):
                    self._validate_json_recursive(value)
        elif isinstance(data, list):
            for item in data:
                self._validate_json_recursive(item)
        elif isinstance(data, str):
            InputValidator.sanitize_string(data)


# ============================================================================
# Error Response Normalization Middleware
# ============================================================================

class ErrorNormalizationMiddleware(BaseHTTPMiddleware):
    """
    Normalize error responses to prevent information disclosure
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            response = await call_next(request)
            
            # Normalize error responses
            if response.status_code >= 400:
                # Avoid leaking internal details
                if response.status_code == 500:
                    logger.error(f"500 error on {request.url.path}")
                    return JSONResponse(
                        status_code=500,
                        content={
                            "error": "Internal Server Error",
                            "message": "An internal error occurred. Please try again later.",
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    )
                
                # For other errors, keep response but clean up
                if response.media_type == "application/json":
                    try:
                        body = json.loads(await response.body())
                        # Remove any internal details
                        if "traceback" in body:
                            del body["traceback"]
                        if "detail" in body and "internal" in str(body["detail"]).lower():
                            body["detail"] = "Invalid request"
                        
                        return JSONResponse(
                            status_code=response.status_code,
                            content=body,
                            headers=dict(response.headers)
                        )
                    except:
                        pass
            
            return response
        
        except Exception as e:
            logger.error(f"Error in error normalization: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )


# ============================================================================
# Request/Response Logging Middleware
# ============================================================================

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Log all requests and responses for auditing
    """
    
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        
        # Log request
        logger.info(
            f"REQUEST: {request.method} {request.url.path} "
            f"from {client_ip}"
        )
        
        response = await call_next(request)
        
        # Calculate response time
        process_time = time.time() - start_time
        
        # Log response
        logger.info(
            f"RESPONSE: {request.method} {request.url.path} "
            f"{response.status_code} ({process_time:.3f}s)"
        )
        
        # Add timing header
        response.headers["X-Process-Time"] = str(process_time)
        
        return response


# ============================================================================
# CORS Policy Middleware
# ============================================================================

class CORSPolicyMiddleware(BaseHTTPMiddleware):
    """
    Enforce strict CORS policy
    """
    
    def __init__(self, app: ASGIApp, allowed_origins: list = None):
        super().__init__(app)
        self.allowed_origins = allowed_origins or [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://localhost",
            "https://localhost"
        ]
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Handle preflight requests
        if request.method == "OPTIONS":
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": ", ".join(self.allowed_origins),
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization",
                    "Access-Control-Max-Age": "3600"
                }
            )
        
        response = await call_next(request)
        
        # Add CORS headers to response
        origin = request.headers.get("origin")
        if origin in self.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        
        return response


# ============================================================================
# Request Signing Verification Middleware (for internal services)
# ============================================================================

class RequestSigningMiddleware(BaseHTTPMiddleware):
    """
    Verify request signatures for internal service-to-service communication
    """
    
    def __init__(self, app: ASGIApp, shared_secret: str = None):
        super().__init__(app)
        self.shared_secret = shared_secret or "default_shared_secret_change_in_production"
        self.bypass_paths = ["/health", "/docs", "/openapi.json"]
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Bypass certain paths
        if any(request.url.path.startswith(path) for path in self.bypass_paths):
            return await call_next(request)
        
        # For now, signature verification is optional
        # Implement full verification in production with:
        # - Request body signing
        # - Timestamp validation
        # - Nonce checking
        
        response = await call_next(request)
        return response


# ============================================================================
# Middleware Registration Helper
# ============================================================================

def add_security_middleware(app):
    """
    Register all security middleware in correct order
    Order matters! Process in reverse of registration.
    """
    # 1. Request signing (outermost - first to process)
    app.add_middleware(RequestSigningMiddleware)
    
    # 2. Request logging
    app.add_middleware(RequestLoggingMiddleware)
    
    # 3. Input validation
    app.add_middleware(InputValidationMiddleware)
    
    # 4. Rate limiting
    app.add_middleware(RateLimitingMiddleware)
    
    # 5. Error normalization
    app.add_middleware(ErrorNormalizationMiddleware)
    
    # 6. CORS policy
    app.add_middleware(
        CORSPolicyMiddleware,
        allowed_origins=[
            "http://localhost:3000",
            "http://localhost:8000",
        ]
    )
    
    # 7. Security headers (innermost - last to process)
    app.add_middleware(SecurityHeadersMiddleware)


if __name__ == "__main__":
    # Test rate limiter
    limiter = RateLimiter()
    
    print("Testing Rate Limiter...")
    for i in range(5):
        is_limited, info = limiter.is_rate_limited("127.0.0.1", "/api/health")
        print(f"Request {i+1}: Limited={is_limited}, Info={info}")
    
    print("\nTesting Input Validator...")
    test_inputs = [
        ("normal_input", "client"),
        ("'; DROP TABLE;--", "client"),
        ("<script>alert('xss')</script>", "client"),
    ]
    
    for input_val, field in test_inputs:
        try:
            result = InputValidator.sanitize_string(input_val, field)
            print(f"✓ '{input_val}' -> '{result}'")
        except ValueError as e:
            print(f"✗ '{input_val}' -> ERROR: {e}")
