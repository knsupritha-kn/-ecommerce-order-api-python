import os

from dotenv import load_dotenv

load_dotenv()


def require_env(name: str) -> str:
    """Return a required environment variable or fail fast with a clear error."""
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your .env file (see .env.example) or the process environment."
        )
    return value


# --- Optional AI settings. The app runs fine without them. ---
# Provider: "ollama" (local, default) or "gemini" (Google REST API, e.g. on Render).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
if LLM_PROVIDER not in ("ollama", "gemini"):
    raise RuntimeError(f'LLM_PROVIDER must be "ollama" or "gemini", got {LLM_PROVIDER!r}')

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
).strip().rstrip("/")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-flash-latest").strip()
# Tried when the primary chat model is overloaded (503) or rate limited (429); empty disables.
GEMINI_CHAT_FALLBACK_MODEL = os.getenv("GEMINI_CHAT_FALLBACK_MODEL", "gemini-flash-lite-latest").strip()
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001").strip()
# Truncate Gemini embeddings (0 = model default, 3072 for gemini-embedding-001).
GEMINI_EMBED_DIMENSIONS = int(os.getenv("GEMINI_EMBED_DIMENSIONS", "768"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:1.5b").strip()
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text").strip()

# Set true only if an Atlas Vector Search index named "product_vector_index" exists.
USE_ATLAS_VECTOR_SEARCH = os.getenv("USE_ATLAS_VECTOR_SEARCH", "false").strip().lower() in ("1", "true", "yes", "on")

# Semantic search: drop results whose cosine similarity is below this (range -1..1).
SEARCH_MIN_SCORE = float(os.getenv("SEARCH_MIN_SCORE", "0.5"))
