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
