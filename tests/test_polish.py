import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import ratelimit
from app.ai import llm

ADDRESS = {"items": [], "shipping_address": "1 Main St"}


# ---------- pagination ----------


async def test_products_default_limit_is_20_and_returns_a_list(client, make_product):
    for i in range(25):
        await make_product(name=f"P{i}")
    r = await client.get("/products")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) == 20


async def test_products_skip_and_limit(client, make_product):
    for i in range(7):
        await make_product(name=f"P{i}")
    first = (await client.get("/products", params={"limit": 3})).json()
    second = (await client.get("/products", params={"skip": 3, "limit": 3})).json()
    last = (await client.get("/products", params={"skip": 6, "limit": 3})).json()
    names = [p["name"] for p in first + second + last]
    assert names == [f"P{i}" for i in range(7)]  # stable order, no overlap, no gaps
    assert (await client.get("/products", params={"skip": 50})).json() == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"skip": -1}])
async def test_pagination_validation(client, make_user, params):
    _, admin_headers = await make_user(admin=True)
    assert (await client.get("/products", params=params)).status_code == 422
    assert (await client.get("/orders", params=params, headers=admin_headers)).status_code == 422
    r = await client.get("/orders/admin/all", params=params, headers=admin_headers)
    assert r.status_code == 422


async def test_products_max_limit_accepted(client, make_product):
    await make_product()
    assert (await client.get("/products", params={"limit": 100})).status_code == 200


async def insert_orders(db, user_id, count):
    now = datetime.now(UTC)
    for i in range(count):
        await db.orders.insert_one(
            {
                "user_id": user_id,
                "items": [{"product_id": "p", "quantity": 1}],
                "total": float(i),
                "status": "pending",
                "created_at": now - timedelta(minutes=i),  # i=0 is newest
            }
        )


async def test_orders_paginated_newest_first_and_scoped_to_user(client, db, make_user):
    other, _ = await make_user()
    me, headers = await make_user()
    await insert_orders(db, me["id"], 25)
    await insert_orders(db, other["id"], 5)

    page1 = (await client.get("/orders", headers=headers)).json()
    assert len(page1) == 20
    assert [o["total"] for o in page1] == [float(i) for i in range(20)]
    page2 = (await client.get("/orders", params={"skip": 20, "limit": 20}, headers=headers)).json()
    assert [o["total"] for o in page2] == [float(i) for i in range(20, 25)]
    assert all(o["user_id"] == me["id"] for o in page1 + page2)


async def test_admin_all_orders_paginated(client, db, make_user):
    user, _ = await make_user()
    _, admin_headers = await make_user(admin=True)
    await insert_orders(db, user["id"], 30)
    r = await client.get("/orders/admin/all", headers=admin_headers)
    assert len(r.json()) == 20
    r = await client.get("/orders/admin/all", params={"skip": 25, "limit": 10}, headers=admin_headers)
    assert len(r.json()) == 5


# ---------- rate limiting ----------


@pytest.fixture
def mock_chat(monkeypatch):
    async def chat(messages):
        return "ok"

    monkeypatch.setattr(llm, "chat", chat)


async def test_ai_rate_limit_returns_429_after_limit(client, make_user, mock_chat):
    _, headers = await make_user()
    for _ in range(ratelimit.AI_LIMIT):
        r = await client.post("/ai/chat", json={"message": "hi"}, headers=headers)
        assert r.status_code == 200
    r = await client.post("/ai/chat", json={"message": "hi"}, headers=headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


async def test_rate_limit_is_per_user(client, make_user, mock_chat):
    _, a = await make_user()
    _, b = await make_user()
    for _ in range(ratelimit.AI_LIMIT):
        await client.post("/ai/chat", json={"message": "hi"}, headers=a)
    assert (await client.post("/ai/chat", json={"message": "hi"}, headers=a)).status_code == 429
    assert (await client.post("/ai/chat", json={"message": "hi"}, headers=b)).status_code == 200


async def test_rate_limit_is_shared_across_ai_endpoints(client, make_user, mock_chat):
    _, headers = await make_user(admin=True)
    body = {"name": "Mug", "category": "kitchen"}
    for _ in range(ratelimit.AI_LIMIT):
        assert (await client.post("/ai/products/describe", json=body, headers=headers)).status_code == 200
    assert (await client.post("/ai/chat", json={"message": "hi"}, headers=headers)).status_code == 429


async def test_rate_limit_window_expires(client, make_user, mock_chat, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock["now"])
    _, headers = await make_user()
    for _ in range(ratelimit.AI_LIMIT):
        await client.post("/ai/chat", json={"message": "hi"}, headers=headers)
    assert (await client.post("/ai/chat", json={"message": "hi"}, headers=headers)).status_code == 429
    clock["now"] += ratelimit.AI_WINDOW_SECONDS + 1
    assert (await client.post("/ai/chat", json={"message": "hi"}, headers=headers)).status_code == 200


async def test_unauthenticated_requests_do_not_consume_limit_and_health_is_unlimited(
    client, monkeypatch
):
    for _ in range(ratelimit.AI_LIMIT + 2):
        assert (await client.post("/ai/chat", json={"message": "hi"})).status_code in (401, 403)

    real = httpx.AsyncClient

    def handler(request):
        return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    for _ in range(ratelimit.AI_LIMIT + 2):
        assert (await client.get("/ai/health")).status_code == 200


# ---------- logging ----------


async def test_request_is_logged_without_query_or_secrets(client, make_user, caplog):
    _, headers = await make_user()
    caplog.set_level(logging.INFO)
    r = await client.get("/products", params={"search": "secret-term"}, headers=headers)
    assert r.status_code == 200

    messages = [rec.getMessage() for rec in caplog.records if rec.name == "app.request"]
    line = next(m for m in messages if m.startswith("GET /products"))
    assert "-> 200" in line and " ms)" in line
    # (the test client's own httpx logger echoes URLs; only our app's records matter here)
    app_logs = " ".join(rec.getMessage() for rec in caplog.records if rec.name.startswith("app"))
    assert "secret-term" not in app_logs
    assert headers["Authorization"].split()[1] not in caplog.text


async def test_login_logs_no_password(client, make_user, caplog):
    caplog.set_level(logging.DEBUG)
    user, _ = await make_user()
    await client.post("/auth/login", json={"email": user["email"], "password": "pw12345678"})
    assert "pw12345678" not in caplog.text


async def test_order_success_and_empty_cart_are_logged(client, make_user, make_product, caplog):
    _, headers = await make_user()
    pid = await make_product(stock=1)
    await client.post("/cart", json={"product_id": pid, "quantity": 1}, headers=headers)
    caplog.set_level(logging.INFO)
    r = await client.post("/orders", json=ADDRESS, headers=headers)
    assert r.status_code == 201
    assert any("order placed" in rec.getMessage() for rec in caplog.records)

    r = await client.post("/orders", json=ADDRESS, headers=headers)
    assert r.status_code == 400
    assert any("empty cart" in rec.getMessage() for rec in caplog.records)


async def test_insufficient_stock_is_logged(client, db, make_user, make_product, caplog):
    _, headers = await make_user()
    pid = await make_product(stock=5)
    await client.post("/cart", json={"product_id": pid, "quantity": 3}, headers=headers)
    await db.products.update_many({}, {"$set": {"stock": 1}})
    caplog.set_level(logging.INFO)
    r = await client.post("/orders", json=ADDRESS, headers=headers)
    assert r.status_code == 400
    assert any("insufficient stock" in rec.getMessage() for rec in caplog.records)


async def test_ai_failure_is_logged(monkeypatch, caplog):
    def refuse(request):
        raise httpx.ConnectError("refused")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(refuse), **kw)
    )
    caplog.set_level(logging.WARNING)
    with pytest.raises(llm.AIUnavailableError):
        await llm.chat([{"role": "user", "content": "private message"}])
    assert any("Ollama call failed" in rec.getMessage() for rec in caplog.records)
    assert "private message" not in caplog.text
