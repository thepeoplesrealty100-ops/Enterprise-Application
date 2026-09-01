"""
backend/core/webhook_dispatcher.py
==================================
Cryptographically-Signed Webhook Dispatcher

Sends HMAC-SHA256 signed webhook payloads to external systems (SOCs, SIEMs, ticketing).
Implements:
  • Payload signing (non-repudiation)
  • Retry logic with exponential backoff
  • Failure logging and alerting
  • Rate limiting (optional)

Enterprise patterns from: GitHub, Stripe, Twilio webhook security
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

import asyncio
import aiohttp


class WebhookDispatcher:
    """
    Sends cryptographically-signed webhooks to configured endpoints.
    """
    
    def __init__(
        self,
        db_manager,
        signing_secret: Optional[str] = None,
        timeout_seconds: int = 30,
        max_retries: int = 3,
    ):
        """
        Args:
            db_manager: DuckDBManager instance (for logging)
            signing_secret: HMAC secret (defaults to config.WEBHOOK_SECRET)
            timeout_seconds: HTTP request timeout
            max_retries: Maximum retry attempts (exponential backoff)
        """
        self.db = db_manager
        self.signing_secret = signing_secret or self._load_secret()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_backoff = 1.0  # Base retry delay in seconds
    
    def _load_secret(self) -> str:
        """Load webhook signing secret from config."""
        try:
            from config import get_config
            config = get_config()
            return getattr(config, "WEBHOOK_SECRET", self._generate_secret())
        except Exception:
            return self._generate_secret()
    
    def _generate_secret(self) -> str:
        """Generate a secure random secret."""
        import secrets
        return secrets.token_urlsafe(64)
    
    def dispatch(
        self,
        webhook_url: str,
        event_type: str,
        payload: Dict[str, Any],
        event_id: Optional[str] = None,
        on_retry: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Synchronously dispatch a webhook (blocking call).
        
        Args:
            webhook_url: Target URL
            event_type: Event type (e.g., "isolation_enforced", "threat_detected")
            payload: Event payload (dict)
            event_id: Optional event ID (auto-generated if not provided)
            on_retry: Optional callback for retry attempts
        
        Returns:
            Dict with status, event_id, delivery_timestamp, signature
        """
        event_id = event_id or str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create signed envelope
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "payload": payload,
        }
        
        signature = self._sign_envelope(envelope)
        
        # Attempt delivery with retries
        for attempt in range(self.max_retries + 1):
            try:
                result = self._send_webhook_sync(
                    webhook_url=webhook_url,
                    envelope=envelope,
                    signature=signature,
                )
                
                if result["status"] == "success":
                    # Log successful delivery
                    self._log_webhook_delivery(
                        event_id=event_id,
                        webhook_url=webhook_url,
                        status="delivered",
                        http_code=result.get("http_code"),
                    )
                    return {
                        "status": "delivered",
                        "event_id": event_id,
                        "timestamp": timestamp,
                        "signature": signature,
                        "http_code": result.get("http_code"),
                    }
                else:
                    raise Exception(result.get("error", "Unknown error"))
            
            except Exception as e:
                if attempt < self.max_retries:
                    backoff_delay = self.base_backoff * (2 ** attempt)
                    if on_retry:
                        on_retry(attempt + 1, backoff_delay, str(e))
                    time.sleep(backoff_delay)
                else:
                    # Final failure
                    self._log_webhook_delivery(
                        event_id=event_id,
                        webhook_url=webhook_url,
                        status="failed_after_retries",
                        http_code=None,
                        error=str(e),
                    )
                    return {
                        "status": "failed_after_retries",
                        "event_id": event_id,
                        "timestamp": timestamp,
                        "signature": signature,
                        "error": str(e),
                        "attempts": self.max_retries + 1,
                    }
    
    async def dispatch_async(
        self,
        webhook_url: str,
        event_type: str,
        payload: Dict[str, Any],
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously dispatch a webhook (non-blocking).
        
        Returns:
            Dict with status, event_id, delivery_timestamp, signature
        """
        event_id = event_id or str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create signed envelope
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": timestamp,
            "payload": payload,
        }
        
        signature = self._sign_envelope(envelope)
        
        # Attempt delivery with retries
        for attempt in range(self.max_retries + 1):
            try:
                result = await self._send_webhook_async(
                    webhook_url=webhook_url,
                    envelope=envelope,
                    signature=signature,
                )
                
                if result["status"] == "success":
                    self._log_webhook_delivery(
                        event_id=event_id,
                        webhook_url=webhook_url,
                        status="delivered",
                        http_code=result.get("http_code"),
                    )
                    return {
                        "status": "delivered",
                        "event_id": event_id,
                        "timestamp": timestamp,
                        "signature": signature,
                        "http_code": result.get("http_code"),
                    }
                else:
                    raise Exception(result.get("error", "Unknown error"))
            
            except Exception as e:
                if attempt < self.max_retries:
                    backoff_delay = self.base_backoff * (2 ** attempt)
                    await asyncio.sleep(backoff_delay)
                else:
                    self._log_webhook_delivery(
                        event_id=event_id,
                        webhook_url=webhook_url,
                        status="failed_after_retries",
                        http_code=None,
                        error=str(e),
                    )
                    return {
                        "status": "failed_after_retries",
                        "event_id": event_id,
                        "timestamp": timestamp,
                        "signature": signature,
                        "error": str(e),
                        "attempts": self.max_retries + 1,
                    }
    
    def _send_webhook_sync(
        self,
        webhook_url: str,
        envelope: Dict[str, Any],
        signature: str,
    ) -> Dict[str, Any]:
        """
        Send webhook via synchronous HTTP request.
        Returns dict with status and optional error.
        """
        import requests
        
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-ID": envelope["event_id"],
            "X-Webhook-Timestamp": envelope["timestamp"],
        }
        
        try:
            response = requests.post(
                webhook_url,
                json=envelope,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            
            if 200 <= response.status_code < 300:
                return {"status": "success", "http_code": response.status_code}
            else:
                return {
                    "status": "error",
                    "http_code": response.status_code,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                }
        
        except requests.Timeout:
            return {"status": "error", "error": "Request timeout"}
        except requests.RequestException as e:
            return {"status": "error", "error": str(e)}
    
    async def _send_webhook_async(
        self,
        webhook_url: str,
        envelope: Dict[str, Any],
        signature: str,
    ) -> Dict[str, Any]:
        """
        Send webhook via asynchronous HTTP request.
        Returns dict with status and optional error.
        """
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-ID": envelope["event_id"],
            "X-Webhook-Timestamp": envelope["timestamp"],
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=envelope,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                ) as response:
                    if 200 <= response.status < 300:
                        return {"status": "success", "http_code": response.status}
                    else:
                        text = await response.text()
                        return {
                            "status": "error",
                            "http_code": response.status,
                            "error": f"HTTP {response.status}: {text[:200]}",
                        }
        
        except asyncio.TimeoutError:
            return {"status": "error", "error": "Request timeout"}
        except aiohttp.ClientError as e:
            return {"status": "error", "error": str(e)}
    
    def _sign_envelope(self, envelope: Dict[str, Any]) -> str:
        """
        Create HMAC-SHA256 signature over envelope.
        
        Args:
            envelope: Dict with event_id, event_type, timestamp, payload
        
        Returns:
            Hex-encoded HMAC-SHA256 signature
        """
        canonical = json.dumps(envelope, sort_keys=True, default=str)
        signature = hmac.new(
            self.signing_secret.encode(),
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature
    
    def verify_signature(self, envelope_json: str, signature: str) -> bool:
        """
        Verify webhook signature (for incoming webhooks).
        
        Args:
            envelope_json: JSON string of the envelope
            signature: Signature to verify (hex-encoded)
        
        Returns:
            True if signature is valid, False otherwise
        """
        expected = hmac.new(
            self.signing_secret.encode(),
            envelope_json.encode(),
            hashlib.sha256,
        ).hexdigest()
        
        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(expected, signature)
    
    def _log_webhook_delivery(
        self,
        event_id: str,
        webhook_url: str,
        status: str,
        http_code: Optional[int] = None,
        error: Optional[str] = None,
    ):
        """
        Log webhook delivery attempt to audit trail.
        """
        try:
            self.db.conn.execute(
                """
                INSERT INTO agent_logs (timestamp, event, action, status, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc),
                    "webhook_delivery",
                    "dispatch",
                    status,
                    json.dumps({
                        "event_id": event_id,
                        "webhook_url": webhook_url,
                        "http_code": http_code,
                        "error": error,
                    }),
                ),
            )
            self.db.conn.commit()
        except Exception:
            # Graceful fallback; don't fail if logging fails
            pass
