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


# --- Optional AI settings (local Ollama). The app runs fine without them. ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip().rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:1.5b").strip()
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text").strip()

# Set true only if an Atlas Vector Search index named "product_vector_index" exists.
USE_ATLAS_VECTOR_SEARCH = os.getenv("USE_ATLAS_VECTOR_SEARCH", "false").strip().lower() in ("1", "true", "yes", "on")
