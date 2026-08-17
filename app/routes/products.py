from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_admin
from app.database import db
from app.models.product import ProductCreate, ProductOut

router = APIRouter(prefix="/products", tags=["products"])


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
async def list_products(category: Optional[str] = None, search: Optional[str] = None):
    """List products, optionally filtered by category and/or name search."""
    query = {}
    if category:
        query["category"] = category
    if search:
        query["name"] = {"$regex": search, "$options": "i"}

    products = await db.products.find(query).to_list(length=None)
    return [product_to_out(p) for p in products]


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: str):
    """Get a single product by id."""
    product = await get_product_or_404(product_id)
    return product_to_out(product)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(product: ProductCreate, admin: dict = Depends(get_current_admin)):
    """Create a new product (admin only)."""
    result = await db.products.insert_one(product.model_dump())
    created = await db.products.find_one({"_id": result.inserted_id})
    return product_to_out(created)


@router.put("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: str, product: ProductCreate, admin: dict = Depends(get_current_admin)
):
    """Replace an existing product's fields (admin only)."""
    await get_product_or_404(product_id)

    await db.products.update_one(
        {"_id": ObjectId(product_id)}, {"$set": product.model_dump()}
    )
    updated = await db.products.find_one({"_id": ObjectId(product_id)})
    return product_to_out(updated)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(product_id: str, admin: dict = Depends(get_current_admin)):
    """Delete a product by id (admin only)."""
    await get_product_or_404(product_id)
    await db.products.delete_one({"_id": ObjectId(product_id)})
