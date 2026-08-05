from fastapi import FastAPI

app = FastAPI(title="E-commerce Order Management System")


@app.get("/")
def health_check():
    return {"status": "ok"}
