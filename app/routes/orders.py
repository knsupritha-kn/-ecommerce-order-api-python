import logging
from datetime import UTC, datetime

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_admin, get_current_user
from app.database import db
from app.models.cart import CartItem
from app.models.order import OrderCreate, OrderOut, OrderStatusUpdate
from app.pagination import Pagination, pagination

router = APIRouter(prefix="/orders", tags=["orders"])
logger = logging.getLogger(__name__)


def order_to_out(order: dict) -> OrderOut:
    """Convert a MongoDB order document into the API response schema."""
    return OrderOut(
        id=str(order["_id"]),
        user_id=order["user_id"],
        items=[CartItem(**item) for item in order["items"]],
        total=order["total"],
        status=order["status"],
        created_at=order["created_at"],
    )


@router.get("", response_model=list[OrderOut])
async def list_orders(
    current_user: dict = Depends(get_current_user), page: Pagination = Depends(pagination)
):
    """List the logged-in user's order history (paginated), most recent first."""
    user_id = str(current_user["_id"])
    orders = (
        await db.orders.find({"user_id": user_id})
        .sort("created_at", -1)
        .skip(page.skip)
        .limit(page.limit)
        .to_list(length=None)
    )
    return [order_to_out(o) for o in orders]


@router.get("/admin/all", response_model=list[OrderOut])
async def list_all_orders(
    admin: dict = Depends(get_current_admin), page: Pagination = Depends(pagination)
):
    """List every order from every user (admin only, paginated)."""
    orders = (
        await db.orders.find()
        .sort("created_at", -1)
        .skip(page.skip)
        .limit(page.limit)
        .to_list(length=None)
    )
    return [order_to_out(o) for o in orders]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: str, current_user: dict = Depends(get_current_user)):
    """Get a single order by id, only if it belongs to the logged-in user."""
    try:
        oid = ObjectId(order_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    order = await db.orders.find_one({"_id": oid})
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order["user_id"] != str(current_user["_id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this order")

    return order_to_out(order)


@router.put("/{order_id}/status", response_model=OrderOut)
async def update_order_status(
    order_id: str, status_update: OrderStatusUpdate, admin: dict = Depends(get_current_admin)
):
    """Update an order's status (admin only)."""
    try:
        oid = ObjectId(order_id)
    except InvalidId:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    order = await db.orders.find_one({"_id": oid})
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    await db.orders.update_one({"_id": oid}, {"$set": {"status": status_update.status}})
    order["status"] = status_update.status
    return order_to_out(order)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(order: OrderCreate, current_user: dict = Depends(get_current_user)):
    """Place an order from the logged-in user's current cart."""
    user_id = str(current_user["_id"])

    cart = await db.cart.find_one({"user_id": user_id})
    if cart is None or not cart.get("items"):
        logger.info("order rejected: empty cart (user=%s)", user_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty")

    items = cart["items"]
    products = {}
    total = 0.0
    for item in items:
        product = await db.products.find_one({"_id": ObjectId(item["product_id"])})
        if product is None:
            logger.warning(
                "order rejected: product %s no longer exists (user=%s)", item["product_id"], user_id
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {item['product_id']} no longer exists",
            )
        if item["quantity"] > product["stock"]:
            logger.warning(
                "order rejected: insufficient stock for product %s (wanted=%s, have=%s, user=%s)",
                item["product_id"],
                item["quantity"],
                product["stock"],
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only {product['stock']} units of {product['name']} available in stock",
            )
        products[item["product_id"]] = product
        total += product["price"] * item["quantity"]

    # Atomically reserve stock per item; the filter prevents overselling under concurrency.
    reduced = []
    for item in items:
        pid = ObjectId(item["product_id"])
        qty = item["quantity"]
        result = await db.products.update_one(
            {"_id": pid, "stock": {"$gte": qty}},
            {"$inc": {"stock": -qty}},
        )
        if result.modified_count == 0:
            logger.warning(
                "order failed: stock race on product %s, rolling back %d item(s) (user=%s)",
                item["product_id"],
                len(reduced),
                user_id,
            )
            # Roll back stock for items already reduced.
            for done_pid, done_qty in reduced:
                await db.products.update_one({"_id": done_pid}, {"$inc": {"stock": done_qty}})
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough stock")
        reduced.append((pid, qty))

    created_at = datetime.now(UTC)
    order_doc = {
        "user_id": user_id,
        "items": items,
        "total": total,
        "status": "pending",
        "shipping_address": order.shipping_address,
        "created_at": created_at,
    }
    try:
        result = await db.orders.insert_one(order_doc)
    except Exception:
        logger.exception("order failed: could not save order after reserving stock (user=%s)", user_id)
        for item in items:
            await db.products.update_one(
                {"_id": ObjectId(item["product_id"])}, {"$inc": {"stock": item["quantity"]}}
            )
        raise
    logger.info("order placed: id=%s user=%s total=%.2f", result.inserted_id, user_id, total)

    await db.cart.delete_one({"user_id": user_id})

    return OrderOut(
        id=str(result.inserted_id),
        user_id=user_id,
        items=[CartItem(**item) for item in items],
        total=total,
        status="pending",
        created_at=created_at,
    )
