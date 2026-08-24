from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_admin, get_current_user
from app.database import db
from app.models.cart import CartItem
from app.models.order import OrderCreate, OrderOut, OrderStatusUpdate

router = APIRouter(prefix="/orders", tags=["orders"])


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
async def list_orders(current_user: dict = Depends(get_current_user)):
    """List the logged-in user's order history, most recent first."""
    user_id = str(current_user["_id"])
    orders = await db.orders.find({"user_id": user_id}).sort("created_at", -1).to_list(length=None)
    return [order_to_out(o) for o in orders]


@router.get("/admin/all", response_model=list[OrderOut])
async def list_all_orders(admin: dict = Depends(get_current_admin)):
    """List every order from every user (admin only)."""
    orders = await db.orders.find().sort("created_at", -1).to_list(length=None)
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cart is empty")

    items = cart["items"]
    products = {}
    total = 0.0
    for item in items:
        product = await db.products.find_one({"_id": ObjectId(item["product_id"])})
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {item['product_id']} no longer exists",
            )
        if item["quantity"] > product["stock"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only {product['stock']} units of {product['name']} available in stock",
            )
        products[item["product_id"]] = product
        total += product["price"] * item["quantity"]

    for item in items:
        await db.products.update_one(
            {"_id": ObjectId(item["product_id"])},
            {"$inc": {"stock": -item["quantity"]}},
        )

    created_at = datetime.now(timezone.utc)
    order_doc = {
        "user_id": user_id,
        "items": items,
        "total": total,
        "status": "pending",
        "shipping_address": order.shipping_address,
        "created_at": created_at,
    }
    result = await db.orders.insert_one(order_doc)

    await db.cart.delete_one({"user_id": user_id})

    return OrderOut(
        id=str(result.inserted_id),
        user_id=user_id,
        items=[CartItem(**item) for item in items],
        total=total,
        status="pending",
        created_at=created_at,
    )
