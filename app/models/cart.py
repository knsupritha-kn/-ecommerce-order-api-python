from pydantic import BaseModel


# A single product line within a cart or order
class CartItem(BaseModel):
    product_id: str
    quantity: int


# A user's cart, returned to clients with the computed total
class CartOut(BaseModel):
    user_id: str
    items: list[CartItem]
    total: float
