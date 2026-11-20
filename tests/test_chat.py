from datetime import UTC, datetime, timedelta

import pytest

from app.ai import llm


@pytest.fixture
def mock_chat(monkeypatch):
    calls = []

    async def chat(messages):
        calls.append(messages)
        return "mocked reply"

    monkeypatch.setattr(llm, "chat", chat)
    return calls


@pytest.fixture
def ai_down(monkeypatch):
    async def chat(messages):
        raise llm.AIUnavailableError("down")

    monkeypatch.setattr(llm, "chat", chat)


async def add_order(db, user, product_id, status="pending", total=20.0, age_days=0):
    result = await db.orders.insert_one(
        {
            "user_id": user["id"],
            "items": [{"product_id": product_id, "quantity": 2}],
            "total": total,
            "status": status,
            "created_at": datetime.now(UTC) - timedelta(days=age_days),
        }
    )
    return str(result.inserted_id)


async def test_requires_login(client):
    r = await client.post("/ai/chat", json={"message": "hi"})
    assert r.status_code in (401, 403)


async def test_message_validation(client, make_user, mock_chat):
    _, headers = await make_user()
    assert (await client.post("/ai/chat", json={"message": ""}, headers=headers)).status_code == 422
    r = await client.post("/ai/chat", json={"message": "x" * 501}, headers=headers)
    assert r.status_code == 422
    r = await client.post("/ai/chat", json={"message": "x" * 500}, headers=headers)
    assert r.status_code == 200


async def test_own_order_by_id(client, db, make_user, make_product, mock_chat):
    user, headers = await make_user()
    pid = await make_product(name="Blue Widget")
    oid = await add_order(db, user, pid, status="shipped", total=20.0)
    await add_order(db, user, pid, status="cancelled")  # another own order, must not be used

    r = await client.post("/ai/chat", json={"message": f"status of {oid}?"}, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"reply": "mocked reply", "orders_used": [oid]}

    system, user_turn = mock_chat[0]
    assert system["role"] == "system" and user_turn["role"] == "user"
    assert user_turn["content"] == f"status of {oid}?"
    assert oid in system["content"]
    assert "shipped" in system["content"]
    assert "Blue Widget x2" in system["content"]
    assert "$20.00" in system["content"]
    assert "cancelled" not in system["content"]


async def test_recent_orders_limited_to_five_newest_first(client, db, make_user, make_product, mock_chat):
    user, headers = await make_user()
    pid = await make_product()
    ids = [await add_order(db, user, pid, age_days=d) for d in range(7)]  # ids[0] newest

    r = await client.post("/ai/chat", json={"message": "what did I order?"}, headers=headers)
    assert r.json()["orders_used"] == ids[:5]


async def test_someone_elses_order_does_not_leak(client, db, make_user, make_product, mock_chat):
    owner, _ = await make_user()
    _, headers = await make_user()
    pid = await make_product(name="Secret Gadget")
    foreign = await add_order(db, owner, pid, status="shipped", total=999.0)

    r = await client.post("/ai/chat", json={"message": f"where is {foreign}?"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["orders_used"] == []
    prompt = mock_chat[0][0]["content"]
    for secret in (foreign, "Secret Gadget", "999", "shipped", owner["id"]):
        assert secret not in prompt


async def test_recent_orders_exclude_other_users(client, db, make_user, make_product, mock_chat):
    owner, _ = await make_user()
    me, headers = await make_user()
    pid = await make_product(name="Secret Gadget")
    await add_order(db, owner, pid)
    mine = await add_order(db, me, pid)

    r = await client.post("/ai/chat", json={"message": "my orders?"}, headers=headers)
    assert r.json()["orders_used"] == [mine]


async def test_unknown_order_id_is_handled(client, make_user, mock_chat):
    _, headers = await make_user()
    r = await client.post("/ai/chat", json={"message": "order " + "a" * 24}, headers=headers)
    assert r.status_code == 200
    assert r.json()["orders_used"] == []


async def test_no_orders(client, make_user, mock_chat):
    _, headers = await make_user()
    r = await client.post("/ai/chat", json={"message": "where is my order?"}, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"reply": "mocked reply", "orders_used": []}
    assert "no orders" in mock_chat[0][0]["content"]


async def test_ai_down_returns_503(client, make_user, ai_down):
    _, headers = await make_user()
    r = await client.post("/ai/chat", json={"message": "hi"}, headers=headers)
    assert r.status_code == 503
    assert r.json()["detail"] == "AI service unavailable"
