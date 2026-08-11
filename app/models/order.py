from datetime import datetime

from pydantic import BaseModel

from app.models.cart import CartItem


# Fields required to place a new order
class OrderCreate(BaseModel):
    items: list[CartItem]
    shipping_address: str


# Order data returned to clients
class OrderOut(BaseModel):
    id: str
    user_id: str
    items: list[CartItem]
    total: float
    status: str = "pending"
    created_at: datetime
