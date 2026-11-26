import json

import httpx
import pytest
from fastapi import HTTPException

from app.ai import llm
from app.routes import ai as ai_routes


def mock_ollama(monkeypatch, handler):
    """Route every httpx.AsyncClient created in app.ai.llm through a mock transport."""
    real = httpx.AsyncClient

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", factory)


def refuse(request):
    raise httpx.ConnectError("refused")


async def test_chat_returns_reply_and_sends_model(monkeypatch):
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.read())
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hi"}})

    mock_ollama(monkeypatch, handler)
    assert await llm.chat([{"role": "user", "content": "yo"}]) == "hi"
    assert seen["path"] == "/api/chat"
    assert seen["body"]["stream"] is False
    assert seen["body"]["model"] == "qwen2.5:1.5b"


async def test_embed_returns_vector(monkeypatch):
    mock_ollama(monkeypatch, lambda r: httpx.Response(200, json={"embeddings": [[0.1, 0.2]]}))
    assert await llm.embed("text") == [0.1, 0.2]


async def test_unreachable_raises_ai_unavailable(monkeypatch):
    mock_ollama(monkeypatch, refuse)
    with pytest.raises(llm.AIUnavailableError):
        await llm.chat([])
    with pytest.raises(llm.AIUnavailableError):
        await llm.embed("x")


async def test_malformed_response_raises_ai_unavailable(monkeypatch):
    mock_ollama(monkeypatch, lambda r: httpx.Response(200, json={"oops": 1}))
    with pytest.raises(llm.AIUnavailableError):
        await llm.chat([])
    with pytest.raises(llm.AIUnavailableError):
        await llm.embed("x")


async def test_http_error_status_raises_ai_unavailable(monkeypatch):
    mock_ollama(monkeypatch, lambda r: httpx.Response(500))
    with pytest.raises(llm.AIUnavailableError):
        await llm.chat([])


def test_ai_unavailable_helper_is_503():
    exc = ai_routes.ai_unavailable()
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 503
    assert exc.detail == "AI service unavailable"


async def test_health_all_available(client, monkeypatch):
    tags = {"models": [{"name": "qwen2.5:1.5b"}, {"name": "nomic-embed-text:latest"}]}
    mock_ollama(monkeypatch, lambda r: httpx.Response(200, json=tags))
    r = await client.get("/ai/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ollama"] is True
    assert body["llm_model"]["available"] is True
    assert body["embed_model"]["available"] is True


async def test_health_model_missing(client, monkeypatch):
    tags = {"models": [{"name": "qwen2.5:1.5b"}]}
    mock_ollama(monkeypatch, lambda r: httpx.Response(200, json=tags))
    body = (await client.get("/ai/health")).json()
    assert body["ollama"] is True
    assert body["llm_model"]["available"] is True
    assert body["embed_model"]["available"] is False


async def test_health_ollama_down_and_rest_of_app_works(client, monkeypatch):
    mock_ollama(monkeypatch, refuse)
    r = await client.get("/ai/health")
    assert r.status_code == 200
    assert r.json()["ollama"] is False
    assert (await client.get("/health")).json() == {"status": "ok"}
