from dataclasses import dataclass

from fastapi import Query

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass
class Pagination:
    skip: int
    limit: int


def pagination(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> Pagination:
    """Shared `skip`/`limit` query params for list endpoints."""
    return Pagination(skip=skip, limit=limit)
