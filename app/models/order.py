from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.cart import CartItem

OrderStatus = Literal["pending", "shipped", "delivered", "cancelled"]


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
    status: OrderStatus = "pending"
    created_at: datetime


# Fields required to update an order's status (admin only)
class OrderStatusUpdate(BaseModel):
    status: OrderStatus
