import os

# Must be set before importing the app: app.config.require_env() runs at import
# time. Assigned (not setdefault) so a real .env can never leak into tests.
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["MONGO_URI"] = "mongodb://localhost:27017"
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["GEMINI_API_KEY"] = ""

import httpx
import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from app import database, ratelimit
from app.auth import dependencies as auth_dependencies
from app.main import app
from app.routes import ai, auth, cart, orders, products, users

# Every module that does `from app.database import db` holds its own reference,
# so each one has to be patched.
MODULES_USING_DB = [database, auth_dependencies, ai, auth, cart, orders, products, users]


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The limiter is in-memory and global; start every test with a clean slate."""
    ratelimit.reset()


@pytest_asyncio.fixture
async def db(monkeypatch):
    """Fresh in-memory mongomock database for each test (so nothing leaks between tests)."""
    client = AsyncMongoMockClient()
    test_db = client["ecommerce"]
    for module in MODULES_USING_DB:
        monkeypatch.setattr(module, "db", test_db)
    yield test_db
    for name in await test_db.list_collection_names():
        await test_db[name].delete_many({})
    client.close()


@pytest_asyncio.fixture
async def client(db):
    """httpx AsyncClient talking to the FastAPI app in-process, backed by the mock db."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


PASSWORD = "pw12345678"


@pytest_asyncio.fixture
async def make_user(client, db):
    """Factory: register + log in a user, returning (user_dict, auth_headers).

    Pass admin=True to promote the user directly in the db (no public endpoint does this).
    """
    counter = 0

    async def _make(admin: bool = False):
        nonlocal counter
        counter += 1
        email = f"user{counter}@example.com"
        r = await client.post(
            "/auth/register", json={"name": f"User {counter}", "email": email, "password": PASSWORD}
        )
        assert r.status_code == 201, r.text
        user = r.json()
        if admin:
            await db.users.update_one({"email": email}, {"$set": {"role": "admin"}})
        r = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return user, {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _make


@pytest_asyncio.fixture
async def make_product(db):
    """Factory: insert a product straight into the db and return its id as a string."""

    async def _make(name="Widget", price=10.0, stock=5, category="gadgets"):
        result = await db.products.insert_one(
            {"name": name, "description": "d", "price": price, "stock": stock, "category": category}
        )
        return str(result.inserted_id)

    return _make
