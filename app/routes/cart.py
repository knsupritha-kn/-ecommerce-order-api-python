from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.database import db
from app.models.cart import CartItem, CartOut

router = APIRouter(prefix="/cart", tags=["cart"])


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


async def build_cart_out(user_id: str, cart: dict) -> CartOut:
    """Compute the cart total by looking up current product prices."""
    items = cart.get("items", [])
    total = 0.0
    for item in items:
        product = await db.products.find_one({"_id": ObjectId(item["product_id"])})
        if product:
            total += product["price"] * item["quantity"]

    return CartOut(
        user_id=user_id,
        items=[CartItem(**item) for item in items],
        total=total,
    )


@router.get("", response_model=CartOut)
async def get_cart(current_user: dict = Depends(get_current_user)):
    """Get the logged-in user's cart with a calculated total."""
    user_id = str(current_user["_id"])
    cart = await db.cart.find_one({"user_id": user_id})
    if cart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")
    return await build_cart_out(user_id, cart)


@router.post("", response_model=CartOut, status_code=status.HTTP_201_CREATED)
async def add_to_cart(item: CartItem, current_user: dict = Depends(get_current_user)):
    """Add an item to the cart, increasing quantity if it's already present."""
    product = await get_product_or_404(item.product_id)
    user_id = str(current_user["_id"])

    cart = await db.cart.find_one({"user_id": user_id})
    if cart is None:
        if item.quantity > product["stock"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only {product['stock']} units available in stock",
            )
        await db.cart.insert_one({"user_id": user_id, "items": [item.model_dump()]})
    else:
        existing = next(
            (i for i in cart["items"] if i["product_id"] == item.product_id), None
        )
        if existing:
            new_quantity = existing["quantity"] + item.quantity
            if new_quantity > product["stock"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Only {product['stock']} units available in stock",
                )
            await db.cart.update_one(
                {"user_id": user_id, "items.product_id": item.product_id},
                {"$inc": {"items.$.quantity": item.quantity}},
            )
        else:
            if item.quantity > product["stock"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Only {product['stock']} units available in stock",
                )
            await db.cart.update_one(
                {"user_id": user_id}, {"$push": {"items": item.model_dump()}}
            )

    cart = await db.cart.find_one({"user_id": user_id})
    return await build_cart_out(user_id, cart)


@router.put("/{product_id}", response_model=CartOut)
async def update_cart_item(
    product_id: str, item: CartItem, current_user: dict = Depends(get_current_user)
):
    """Update the quantity of a specific item in the cart."""
    product = await get_product_or_404(product_id)
    if item.quantity > product["stock"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only {product['stock']} units available in stock",
        )

    user_id = str(current_user["_id"])

    cart = await db.cart.find_one({"user_id": user_id})
    if cart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")

    result = await db.cart.update_one(
        {"user_id": user_id, "items.product_id": product_id},
        {"$set": {"items.$.quantity": item.quantity}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in cart")

    cart = await db.cart.find_one({"user_id": user_id})
    return await build_cart_out(user_id, cart)


@router.delete("/{product_id}", response_model=CartOut)
async def remove_cart_item(product_id: str, current_user: dict = Depends(get_current_user)):
    """Remove a specific item from the cart."""
    user_id = str(current_user["_id"])

    cart = await db.cart.find_one({"user_id": user_id})
    if cart is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")

    existing = next(
        (i for i in cart["items"] if i["product_id"] == product_id), None
    )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in cart")

    await db.cart.update_one(
        {"user_id": user_id}, {"$pull": {"items": {"product_id": product_id}}}
    )

    cart = await db.cart.find_one({"user_id": user_id})
    return await build_cart_out(user_id, cart)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(current_user: dict = Depends(get_current_user)):
    """Clear the entire cart for the logged-in user."""
    user_id = str(current_user["_id"])
    result = await db.cart.delete_one({"user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found")
