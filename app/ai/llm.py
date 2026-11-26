"""Thin async client for a local Ollama server."""

import logging

import httpx

from app import config

logger = logging.getLogger(__name__)


class AIUnavailableError(Exception):
    """Ollama is unreachable, timed out, or returned an unusable response."""


async def _request(method: str, path: str, *, timeout: float, json: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(base_url=config.OLLAMA_BASE_URL, timeout=timeout) as client:
            response = await client.request(method, path, json=json)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Ollama call failed: %s %s -> %s", method, path, exc.__class__.__name__)
        raise AIUnavailableError(str(exc) or exc.__class__.__name__) from exc


async def chat(messages: list[dict]) -> str:
    """Send chat messages ([{"role": ..., "content": ...}]) and return the reply text."""
    data = await _request(
        "POST",
        "/api/chat",
        timeout=120.0,
        json={"model": config.LLM_MODEL, "messages": messages, "stream": False},
    )
    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as exc:
        logger.warning("Ollama /api/chat returned an unexpected payload")
        raise AIUnavailableError("Unexpected response from Ollama /api/chat") from exc


async def embed(text: str) -> list[float]:
    """Return the embedding vector for `text`."""
    data = await _request(
        "POST",
        "/api/embed",
        timeout=60.0,
        json={"model": config.EMBED_MODEL, "input": text},
    )
    try:
        return data["embeddings"][0]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Ollama /api/embed returned an unexpected payload")
        raise AIUnavailableError("Unexpected response from Ollama /api/embed") from exc


async def list_models() -> list[str]:
    """Names of models installed in Ollama (raises AIUnavailableError if unreachable)."""
    data = await _request("GET", "/api/tags", timeout=5.0)
    return [m.get("name", "") for m in data.get("models", [])]
