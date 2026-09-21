"""
backend/llm_energy_core.py
=============================
Q'AIP "Energy Core" — a token-bucket rate limiter that throttles LLM
inference calls so a burst of agent activity can't blow through the
provider's API rate limit and start failing requests.

Deliberately a small, dependency-free, in-memory implementation: no new
external service, no new failure mode. One process-wide instance
(`ENERGY_CORE`) is shared by anything that wants throttling — currently
AIPPayloadGenerator's optional LLM-prioritization step
(payloads/aip_payload_generator.py's _llm_prioritize) — via the
`throttle()` context manager / `allow()` check below.

This does not touch AgentOrchestrator's Claude/Ollama calls in
llm_orchestrator.py — those are unchanged. Wiring the Energy Core there
too is a natural next step but out of scope for a non-disruptive add.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class _Bucket:
    capacity: float
    tokens: float
    refill_per_second: float
    last_refill: float = field(default_factory=time.monotonic)

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
            self.last_refill = now

    def try_consume(self, amount: float = 1.0) -> bool:
        self._refill()
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class EnergyCore:
    """
    Simple token-bucket throttle. Default: 60 requests/minute (1/sec
    refill, burst capacity 10) — generous enough not to bite normal usage,
    tight enough to actually prevent a runaway loop from hammering a
    provider's rate limit.
    """

    def __init__(self, requests_per_minute: int = 60, burst_capacity: int = 10):
        self._bucket = _Bucket(
            capacity=float(burst_capacity),
            tokens=float(burst_capacity),
            refill_per_second=requests_per_minute / 60.0,
        )
        self._lock = threading.Lock()
        self._allowed_count = 0
        self._throttled_count = 0

    def allow(self) -> bool:
        """Non-blocking check: True if a call may proceed right now."""
        with self._lock:
            ok = self._bucket.try_consume(1.0)
            if ok:
                self._allowed_count += 1
            else:
                self._throttled_count += 1
            return ok

    def status(self) -> dict:
        with self._lock:
            self._bucket._refill()
            return {
                "tokens_available": round(self._bucket.tokens, 2),
                "capacity": self._bucket.capacity,
                "refill_per_second": self._bucket.refill_per_second,
                "allowed_count": self._allowed_count,
                "throttled_count": self._throttled_count,
                "load_metric": round(1.0 - (self._bucket.tokens / self._bucket.capacity), 4),
            }


# Process-wide singleton — see module docstring.
ENERGY_CORE = EnergyCore()
