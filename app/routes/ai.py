import re

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.ai import llm
from app.ai.embeddings import embed_product, embedding_field
from app.auth.dependencies import get_current_admin, get_current_user
from app.database import db
from app.ratelimit import ai_rate_limit

router = APIRouter(prefix="/ai", tags=["ai"])

ORDER_ID_RE = re.compile(r"\b[0-9a-fA-F]{24}\b")
RECENT_ORDERS = 5

SYSTEM_PROMPT = (
    "You are a helpful shop assistant. Answer only from the order data below. "
    "Be brief. If the answer isn't in the data, say so. "
    "Reply in plain text only: no markdown, no ** or bullet symbols. "
    "Never show raw order IDs; refer to orders by their date and items instead.\n\n"
    "Order data:\n{context}"
)


DESCRIBE_PROMPT = (
    "You write product descriptions for an online shop. Write a short, appealing "
    "description of 2-3 sentences. Use only the details provided. Do not invent "
    "specifications, materials, features, prices, or claims. Reply with the "
    "description text only."
)


class DescribeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    keywords: str | None = Field(default=None, max_length=500)


class DescribeResponse(BaseModel):
    description: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class ChatResponse(BaseModel):
    reply: str
    orders_used: list[str]


def ai_unavailable() -> HTTPException:
    """Standard 503 for AI endpoints; raise it when llm.* raises AIUnavailableError."""
    return HTTPException(status_code=503, detail="AI service unavailable")


def _has_model(installed: list[str], wanted: str) -> bool:
    # Ollama lists untagged models as "name:latest".
    candidates = {wanted} if ":" in wanted else {wanted, f"{wanted}:latest"}
    return any(name in candidates for name in installed)


@router.get("/health")
async def ai_health():
    """Report the active provider and whether its models are usable.

    Always 200: this is a status report, not an AI call (Gemini is not pinged).
    """
    if config.LLM_PROVIDER == "gemini":
        return {
            "provider": "gemini",
            "configured": bool(config.GEMINI_API_KEY),
            "llm_model": {"name": config.GEMINI_CHAT_MODEL},
            "embed_model": {"name": config.GEMINI_EMBED_MODEL},
            "embedding_field": embedding_field(),
        }
    try:
        installed = await llm.list_models()
    except llm.AIUnavailableError:
        installed = None
    return {
        "provider": "ollama",
        "embedding_field": embedding_field(),
        "ollama": installed is not None,
        "llm_model": {
            "name": config.LLM_MODEL,
            "available": installed is not None and _has_model(installed, config.LLM_MODEL),
        },
        "embed_model": {
            "name": config.EMBED_MODEL,
            "available": installed is not None and _has_model(installed, config.EMBED_MODEL),
        },
    }


@router.post("/products/reindex", dependencies=[Depends(ai_rate_limit)])
async def reindex_products(admin: dict = Depends(get_current_admin)):
    """(Re)generate embeddings for every product (admin only)."""
    indexed = 0
    failed = 0
    async for product in db.products.find({}):
        embedding = await embed_product(product)
        if embedding is None:
            failed += 1
            if failed == 1 and indexed == 0:
                raise ai_unavailable()  # Ollama is down; don't grind through every product
            continue
        await db.products.update_one({"_id": product["_id"]}, {"$set": {embedding_field(): embedding}})
        indexed += 1
    return {"indexed": indexed, "failed": failed}


async def load_order_context(user_id: str, message: str) -> list[dict] | None:
    """Fetch the orders the assistant may see; always scoped to `user_id`.

    Returns None when the message names an order id that isn't this user's
    (indistinguishable from a nonexistent one, so nothing leaks).
    """
    match = ORDER_ID_RE.search(message)
    if match:
        order = await db.orders.find_one({"_id": ObjectId(match.group()), "user_id": user_id})
        return [order] if order else None
    return (
        await db.orders.find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(RECENT_ORDERS)
        .to_list(length=None)
    )


async def describe_orders(orders: list[dict]) -> str:
    if not orders:
        return "(This customer has no orders.)"
    def oid(value: str) -> ObjectId | None:
        return ObjectId(value) if ObjectId.is_valid(value) else None

    product_ids = [oid(i["product_id"]) for o in orders for i in o["items"]]
    names = {
        p["_id"]: p["name"]
        async for p in db.products.find({"_id": {"$in": [i for i in product_ids if i]}})
    }
    blocks = []
    for o in orders:
        items = ", ".join(
            f"{names.get(oid(i['product_id']), 'unknown product')} x{i['quantity']}"
            for i in o["items"]
        )
        blocks.append(
            f"Order {o['_id']}: status={o['status']}; date={o['created_at']:%Y-%m-%d}; "
            f"items: {items}; total=${o['total']:.2f}"
        )
    return "\n".join(blocks)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(ai_rate_limit)])
async def chat(body: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Answer questions about the logged-in user's own orders."""
    orders = await load_order_context(str(current_user["_id"]), body.message)
    if orders is None:
        context = "(No order with that id was found for this customer.)"
        orders = []
    else:
        context = await describe_orders(orders)

    try:
        reply = await llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
                {"role": "user", "content": body.message},
            ]
        )
    except llm.AIUnavailableError:
        raise ai_unavailable()
    return ChatResponse(reply=reply, orders_used=[str(o["_id"]) for o in orders])


@router.post(
    "/products/describe", response_model=DescribeResponse, dependencies=[Depends(ai_rate_limit)]
)
async def describe_product(body: DescribeRequest, admin: dict = Depends(get_current_admin)):
    """Draft a product description with the LLM (admin only); the admin edits before saving."""
    details = f"Product name: {body.name}\nCategory: {body.category}"
    if body.keywords and body.keywords.strip():
        details += f"\nKeywords: {body.keywords.strip()}"
    try:
        text = await llm.chat(
            [
                {"role": "system", "content": DESCRIBE_PROMPT},
                {"role": "user", "content": details},
            ]
        )
    except llm.AIUnavailableError:
        raise ai_unavailable()
    return DescribeResponse(description=text.strip())
