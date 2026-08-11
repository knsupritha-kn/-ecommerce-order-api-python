from pydantic import BaseModel


# Fields required to create a new product
class ProductCreate(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str


# Product data returned to clients, including its id
class ProductOut(ProductCreate):
    id: str
