from fastapi import FastAPI

from app.routes import auth

app = FastAPI(title="E-commerce Order Management System")

app.include_router(auth.router)


@app.get("/")
def health_check():
    return {"status": "ok"}
