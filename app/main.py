from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import auth, cart, orders, products

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="E-commerce Order Management System")

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(orders.router)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/")
def serve_index():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/{page_name}.html")
def serve_page(page_name: str):
    return FileResponse(BASE_DIR / "templates" / f"{page_name}.html")
