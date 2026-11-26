"""Thin async client for the active LLM provider (local Ollama or Google Gemini)."""

import logging

import httpx

from app import config

logger = logging.getLogger(__name__)

# Cap replies (descriptions/chat) so responses return quickly.
MAX_OUTPUT_TOKENS = 200


class AIUnavailableError(Exception):
    """The AI provider is unreachable, timed out, rate limited, or returned an unusable response."""


def _provider() -> str:
    return config.LLM_PROVIDER


async def _request(
    method: str,
    path: str,
    *,
    timeout: float,
    json: dict | None = None,
    base_url: str | None = None,
    headers: dict | None = None,
    label: str = "Ollama",
) -> dict:
    try:
        async with httpx.AsyncClient(
            base_url=base_url or config.OLLAMA_BASE_URL, timeout=timeout, headers=headers
        ) as client:
            response = await client.request(method, path, json=json)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            logger.warning("%s call rate limited (429): %s %s", label, method, path)
        else:
            logger.warning("%s call failed: %s %s -> %s", label, method, path, exc.__class__.__name__)
        raise AIUnavailableError(str(exc) or exc.__class__.__name__) from exc


async def _gemini(path: str, body: dict, timeout: float) -> dict:
    if not config.GEMINI_API_KEY:
        raise AIUnavailableError("GEMINI_API_KEY is not set")
    return await _request(
        "POST",
        path,
        timeout=timeout,
        json=body,
        base_url=config.GEMINI_BASE_URL,
        headers={"x-goog-api-key": config.GEMINI_API_KEY},
        label="Gemini",
    )


async def _gemini_chat(messages: list[dict]) -> str:
    system = [m["content"] for m in messages if m.get("role") == "system"]
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m.get("role") != "system"
    ]
    body: dict = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            # Gemini 3 models reject thinkingBudget; "low" is the lowest level all accept.
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    models = [config.GEMINI_CHAT_MODEL]
    if config.GEMINI_CHAT_FALLBACK_MODEL and config.GEMINI_CHAT_FALLBACK_MODEL != config.GEMINI_CHAT_MODEL:
        models.append(config.GEMINI_CHAT_FALLBACK_MODEL)
    data: dict = {}
    for i, model in enumerate(models):
        try:
            data = await _gemini(f"/models/{model}:generateContent", body, 15.0)
            break
        except AIUnavailableError:
            if i == len(models) - 1:
                raise
            logger.warning("Gemini model %s failed; falling back to %s", model, models[i + 1])
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        logger.warning("Gemini generateContent returned an unexpected payload")
        raise AIUnavailableError("Unexpected response from Gemini generateContent") from exc


async def _gemini_embed(text: str) -> list[float]:
    body: dict = {
        "model": f"models/{config.GEMINI_EMBED_MODEL}",
        "content": {"parts": [{"text": text}]},
    }
    if config.GEMINI_EMBED_DIMENSIONS:
        body["outputDimensionality"] = config.GEMINI_EMBED_DIMENSIONS
    data = await _gemini(f"/models/{config.GEMINI_EMBED_MODEL}:embedContent", body, 30.0)
    try:
        return data["embedding"]["values"]
    except (KeyError, TypeError) as exc:
        logger.warning("Gemini embedContent returned an unexpected payload")
        raise AIUnavailableError("Unexpected response from Gemini embedContent") from exc


async def chat(messages: list[dict]) -> str:
    """Send chat messages ([{"role": ..., "content": ...}]) and return the reply text."""
    if _provider() == "gemini":
        return await _gemini_chat(messages)
    data = await _request(
        "POST",
        "/api/chat",
        timeout=120.0,
        json={
            "model": config.LLM_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": MAX_OUTPUT_TOKENS},
        },
    )
    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as exc:
        logger.warning("Ollama /api/chat returned an unexpected payload")
        raise AIUnavailableError("Unexpected response from Ollama /api/chat") from exc


async def embed(text: str) -> list[float]:
    """Return the embedding vector for `text`."""
    if _provider() == "gemini":
        return await _gemini_embed(text)
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
