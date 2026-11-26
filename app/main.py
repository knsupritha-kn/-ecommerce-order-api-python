import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import ai, auth, cart, orders, products, users

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # don't echo outbound URLs
logger = logging.getLogger("app.request")

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="E-commerce Order Management System")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, path, status and duration. Query strings and headers are never logged."""
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %d (%.1f ms)", request.method, request.url.path, status_code, elapsed_ms
        )

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(users.router)
app.include_router(ai.router)

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
