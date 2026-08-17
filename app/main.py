from fastapi import FastAPI

from app.routes import auth, cart, products

app = FastAPI(title="E-commerce Order Management System")

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)


@app.get("/")
def health_check():
    return {"status": "ok"}
