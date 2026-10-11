"""
services/llm_client.py — thin generic text-generation client.

Wraps this platform's own already-configured LLM backend (config.LLM_ENGINE:
'claude' or 'ollama' -- the same config llm_orchestrator.py's
AgentOrchestrator uses for pentest reasoning) as a plain
(system_prompt, user_prompt) -> text call, with optional JSON-schema
output.

Exists so operator-facing free-text generation features (a phishing-
training content generator, an investigation-evidence analyzer) ask THIS
platform's own configured LLM, instead of each reinventing a client --
or, as they previously did, calling a third-party API (Google's Gemini)
directly from the browser via a hardcoded, permanently-empty API key.
That call could never succeed; every request it made 403'd. See
index.html's callGeminiApi() removal for the sites this replaced.

Deliberately does not fabricate a response when no backend is usable --
raises LLMUnavailable so the caller can report that honestly rather than
silently returning empty or invented content.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """No configured LLM backend could serve this request."""


def _get_config():
    from config import get_config
    return get_config()


def _schema_suffix(json_schema: Dict[str, Any]) -> str:
    return (
        "\n\nRespond with ONLY a single valid JSON object matching this schema "
        f"-- no prose, no markdown code fences: {json.dumps(json_schema)}"
    )


def generate(system_prompt: str, user_prompt: str,
             json_schema: Optional[Dict[str, Any]] = None,
             temperature: float = 0.5, max_tokens: int = 1024) -> Dict[str, Any]:
    """
    Returns {"text": str} normally, or {"text": str, "json": dict|None}
    when json_schema is given -- json is None if the model's response
    didn't parse as clean JSON (surfaced, not silently coerced).

    Raises LLMUnavailable if the configured backend can't serve this
    request at all (no key, package missing, connection refused).
    """
    cfg = _get_config()
    sys_prompt = system_prompt + (_schema_suffix(json_schema) if json_schema else "")

    if cfg.LLM_ENGINE == "claude":
        text = _call_claude(cfg, sys_prompt, user_prompt, temperature, max_tokens)
    else:
        text = _call_ollama(cfg, sys_prompt, user_prompt, temperature)

    result: Dict[str, Any] = {"text": text}
    if json_schema is not None:
        try:
            result["json"] = json.loads(text)
        except (TypeError, ValueError):
            result["json"] = None
    return result


def _call_claude(cfg, system_prompt: str, user_prompt: str,
                  temperature: float, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise LLMUnavailable("anthropic package not installed") from e
    if not cfg.CLAUDE_API_KEY:
        raise LLMUnavailable("CLAUDE_API_KEY not configured (LLM_ENGINE=claude)")
    try:
        client = anthropic.Anthropic(api_key=cfg.CLAUDE_API_KEY)
        msg = client.messages.create(
            model=cfg.CLAUDE_MODEL, max_tokens=max_tokens, temperature=temperature,
            system=system_prompt, messages=[{"role": "user", "content": user_prompt}],
        )
        return msg.content[0].text
    except LLMUnavailable:
        raise
    except Exception as e:  # noqa: BLE001
        raise LLMUnavailable(f"Claude call failed: {e}") from e


def _call_ollama(cfg, system_prompt: str, user_prompt: str, temperature: float) -> str:
    try:
        resp = requests.post(
            f"{cfg.OLLAMA_BASE_URL}/api/generate",
            json={"model": cfg.OLLAMA_MODEL, "system": system_prompt, "prompt": user_prompt,
                  "stream": False, "temperature": temperature},
            timeout=60,
        )
    except requests.RequestException as e:
        raise LLMUnavailable(f"Ollama unreachable at {cfg.OLLAMA_BASE_URL}: {e}") from e
    if resp.status_code != 200:
        raise LLMUnavailable(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("response", "")
