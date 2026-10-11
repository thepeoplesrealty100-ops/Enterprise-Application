"""
backend/tests/test_assistant_generate.py
POST /api/assistant/generate — generic LLM text/JSON generation.

Run: cd backend && python -m pytest tests/test_assistant_generate.py -q

Regression context: index.html previously called Google's Gemini API
directly from the browser via a hardcoded, permanently-empty API key
("apiKey = ''; ... will be populated by the environment" -- leftover
boilerplate from an AI-Studio-style prototype scaffold, never adapted to
this app's real backend LLM configuration). Every one of those requests
403'd; three operator-console features (phishing-training content
generation, a threat "assessment" panel, and the AIP Investigator) had
been silently, permanently broken. This endpoint is what index.html was
rewired to call instead -- services/llm_client.py wraps this platform's
own configured LLM_ENGINE (Claude or Ollama), and the endpoint reports
an honest failure (ok: false + reason) rather than fabricating content
when no backend is usable.

services.llm_client is mocked throughout: this suite must never depend
on a real Claude API key or a running Ollama instance.
"""

import sys
import types
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))


@pytest.fixture(scope="module")
def app():
    from app import app as _app
    return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_generate_reports_honest_failure_when_no_llm_configured(client, monkeypatch):
    """
    In this test environment there is no real Claude key and no Ollama
    instance, so the endpoint must say so plainly -- ok: false with a
    reason -- rather than 500 or return fabricated text.
    """
    import services.llm_client as llm_client

    def raise_unavailable(*a, **kw):
        raise llm_client.LLMUnavailable("no backend configured in test env")
    monkeypatch.setattr(llm_client, "generate", raise_unavailable)

    res = await client.post("/api/assistant/generate",
                            json={"system_prompt": "sys", "user_prompt": "hello"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "error" in body and body["error"]


@pytest.mark.asyncio
async def test_generate_returns_text_from_mocked_backend(client, monkeypatch):
    def fake_generate(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        assert system_prompt == "You are a test assistant."
        assert user_prompt == "Say hi"
        assert json_schema is None
        return {"text": "hi there"}

    import services.llm_client as llm_client
    monkeypatch.setattr(llm_client, "generate", fake_generate)

    res = await client.post("/api/assistant/generate",
                            json={"system_prompt": "You are a test assistant.", "user_prompt": "Say hi"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["text"] == "hi there"


@pytest.mark.asyncio
async def test_generate_with_json_schema_returns_parsed_json(client, monkeypatch):
    import services.llm_client as llm_client

    schema = {"type": "object", "properties": {"analysis": {"type": "string"}},
              "required": ["analysis"]}

    def fake_generate(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        assert json_schema == schema
        return {"text": '{"analysis": "looks fine"}', "json": {"analysis": "looks fine"}}
    monkeypatch.setattr(llm_client, "generate", fake_generate)

    res = await client.post("/api/assistant/generate", json={
        "system_prompt": "analyze", "user_prompt": "evidence here", "json_schema": schema,
    })
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["json"]["analysis"] == "looks fine"


@pytest.mark.asyncio
async def test_generate_when_model_returns_unparseable_json_reports_json_none(client, monkeypatch):
    """services/llm_client.generate() itself returns json: None on a parse
    failure (see its own docstring) -- the endpoint must pass that through
    rather than crash or silently coerce it."""
    import services.llm_client as llm_client

    def fake_generate(system_prompt, user_prompt, json_schema=None, temperature=0.5, max_tokens=1024):
        return {"text": "not actually json", "json": None}
    monkeypatch.setattr(llm_client, "generate", fake_generate)

    res = await client.post("/api/assistant/generate", json={
        "system_prompt": "analyze", "user_prompt": "evidence",
        "json_schema": {"type": "object"},
    })
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["json"] is None
    assert body["text"] == "not actually json"
