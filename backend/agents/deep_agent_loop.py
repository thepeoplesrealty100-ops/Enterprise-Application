"""
backend/agents/deep_agent_loop.py — self-correcting deep agent loop.

Wraps services/llm_client.py.generate() (this platform's already-configured
Claude/Ollama client -- never a second, separately-configured LLM client)
with Pydantic schema validation and a bounded, LLM-driven retry: on a
validation failure the loop feeds the concrete error back to the model and
asks for a corrected response, up to `max_retries` times.

Deliberately does NOT retry LLMUnavailable (no backend configured / backend
unreachable) -- that is an infrastructure failure, not a content mistake the
model can correct by trying again, so it is raised immediately rather than
burning retries and eventually reporting a misleading "validation failed".
"""
from __future__ import annotations

import asyncio
import logging
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from services.llm_client import generate

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AgentValidationError(RuntimeError):
    """Retries exhausted without producing output that validates."""


class SelfCorrectingAgent:
    def __init__(self, max_retries: int = 3):
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        self.max_retries = max_retries

    async def execute_with_validation(
        self,
        system_prompt: str,
        user_prompt: str,
        validation_schema: Type[T],
        *,
        temperature: float = 0.5,
        max_tokens: int = 1024,
    ) -> T:
        """
        Calls the LLM, validates its JSON output against `validation_schema`,
        and retries with corrective feedback on failure. Raises
        AgentValidationError if every attempt fails, LLMUnavailable if no
        LLM backend can be reached at all.
        """
        schema_json = validation_schema.model_json_schema()
        prompt = user_prompt
        last_error = "no attempts made"

        for attempt in range(1, self.max_retries + 1):
            result = await asyncio.to_thread(
                generate, system_prompt, prompt, schema_json, temperature, max_tokens,
            )
            raw = result.get("json")
            if raw is None:
                last_error = f"response was not valid JSON: {result.get('text', '')[:300]!r}"
            else:
                try:
                    return validation_schema.model_validate(raw)
                except ValidationError as e:
                    last_error = str(e)

            logger.warning(
                "SelfCorrectingAgent attempt %d/%d failed schema validation: %s",
                attempt, self.max_retries, last_error,
            )
            prompt = (
                f"{user_prompt}\n\n"
                f"Your previous response failed schema validation with this error:\n{last_error}\n\n"
                "Return ONLY corrected JSON matching the required schema exactly -- no prose, "
                "no markdown fences."
            )

        raise AgentValidationError(
            f"Exhausted {self.max_retries} attempts against {validation_schema.__name__}; "
            f"last error: {last_error}"
        )
