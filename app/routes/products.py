
import logging

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import config
from app.ai import llm
from app.ai.embeddings import (
    VECTOR_INDEX,
    cosine,
    embed_product,
    embedding_field,
    query_text,
)
from app.auth.dependencies import get_current_admin
from app.database import db
from app.models.product import ProductCreate, ProductOut
from app.pagination import Pagination, pagination

router = APIRouter(prefix="/products", tags=["products"])
logger = logging.getLogger(__name__)


def product_to_out(product: dict) -> ProductOut:
    """Convert a MongoDB product document into the API response schema."""
    return ProductOut(
        id=str(product["_id"]),
        name=product["name"],
        description=product["description"],
        price=product["price"],
        stock=product["stock"],
        category=product["category"],
    )


async def get_product_or_404(product_id: str) -> dict:
    """Fetch a product by id, raising 404 if it doesn't exist or the id is malformed."""
    try:
        oid = ObjectId(product_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    product = await db.products.find_one({"_id": oid})
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("", response_model=list[ProductOut])
async def list_products(
    category: str | None = None,
    search: str | None = None,
    page: Pagination = Depends(pagination),
):
    """List products (paginated), optionally filtered by category and/or name search."""
    query = {}
    if category:
        query["category"] = category
    if search:
        query["name"] = {"$regex": search, "$options": "i"}

    products = (
        await db.products.find(query)
        .sort("_id", 1)
        .skip(page.skip)
        .limit(page.limit)
        .to_list(length=None)
    )
    return [product_to_out(p) for p in products]


@router.get("/search", response_model=list[ProductOut])
async def search_products(q: str = Query(min_length=1), limit: int = Query(5, ge=1, le=50)):
    """Semantic product search: Atlas $vectorSearch, falling back to in-Python cosine."""
    try:
        query_vector = await llm.embed(query_text(q))
    except llm.AIUnavailableError:
        raise HTTPException(status_code=503, detail="AI service unavailable")

    field = embedding_field()
    results: list[dict] = []
    if config.USE_ATLAS_VECTOR_SEARCH:
        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": VECTOR_INDEX,
                        "path": field,
                        "queryVector": query_vector,
                        "numCandidates": max(limit * 20, 100),
                        "limit": limit,
                    }
                },
                {"$addFields": {"_score": {"$meta": "vectorSearchScore"}}},
                {"$project": {"embedding": 0, "embedding_ollama": 0, "embedding_gemini": 0}},
            ]
            results = await db.products.aggregate(pipeline).to_list(length=limit)
            # Atlas cosine scores are (1 + cos) / 2; convert back to plain cosine.
            scored = [(2 * d.pop("_score", 0.5) - 1, d) for d in results]
        except Exception:  # noqa: BLE001 - missing index / non-Atlas MongoDB
            results = []
            scored = []

    if not results:  # Atlas disabled, errored, or silently returned nothing (e.g. no index)
        docs = await db.products.find({field: {"$exists": True}}).to_list(length=None)
        scored = sorted(
            ((cosine(query_vector, d[field]), d) for d in docs),
            key=lambda pair: pair[0],
            reverse=True,
        )
        scored = scored[:limit]

    min_score = config.SEARCH_MIN_SCORE
    for score, d in scored:
        logger.debug(
            "search q=%r product=%r score=%.4f %s",
            q, d.get("name"), score, "keep" if score >= min_score else "drop",
        )
    return [product_to_out(d) for score, d in scored if score >= min_score]


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: str):
    """Get a single product by id."""
    product = await get_product_or_404(product_id)
    return product_to_out(product)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(product: ProductCreate, admin: dict = Depends(get_current_admin)):
    """Create a new product (admin only)."""
    doc = product.model_dump()
    embedding = await embed_product(doc)
    if embedding is not None:
        doc[embedding_field()] = embedding
    result = await db.products.insert_one(doc)
    created = await db.products.find_one({"_id": result.inserted_id})
    return product_to_out(created)


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: str, product: ProductCreate, admin: dict = Depends(get_current_admin)
):
    """Replace an existing product's fields (admin only)."""
    await get_product_or_404(product_id)

    fields = product.model_dump()
    embedding = await embed_product(fields)
    update = {"$set": fields}
    if embedding is not None:
        fields[embedding_field()] = embedding
    else:
        update["$unset"] = {embedding_field(): ""}  # stale vector no longer matches the text
    await db.products.update_one({"_id": ObjectId(product_id)}, update)
    updated = await db.products.find_one({"_id": ObjectId(product_id)})
    return product_to_out(updated)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: str, admin: dict = Depends(get_current_admin)):
    """Delete a product by id (admin only)."""
    await get_product_or_404(product_id)
    await db.products.delete_one({"_id": ObjectId(product_id)})
