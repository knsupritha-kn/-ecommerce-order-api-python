"""Product embedding helpers shared by the product and AI routes."""

import math

from app.ai import llm

VECTOR_INDEX = "product_vector_index"


def product_text(product: dict) -> str:
    return f"{product['name']} {product['description']} {product['category']}"


# nomic-embed-text works best with task prefixes.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


async def embed_product(product: dict) -> list[float] | None:
    """Embedding for a product's text, or None if the AI service is unavailable."""
    try:
        return await llm.embed(DOCUMENT_PREFIX + product_text(product))
    except llm.AIUnavailableError:
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
