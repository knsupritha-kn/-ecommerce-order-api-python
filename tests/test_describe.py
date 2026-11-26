import pytest

from app.ai import llm


@pytest.fixture
def mock_chat(monkeypatch):
    calls = []

    async def chat(messages):
        calls.append(messages)
        return "  A lovely product.  \n"

    monkeypatch.setattr(llm, "chat", chat)
    return calls


@pytest.fixture
def ai_down(monkeypatch):
    async def chat(messages):
        raise llm.AIUnavailableError("down")

    monkeypatch.setattr(llm, "chat", chat)


async def test_describe_admin_only(client, make_user, mock_chat):
    body = {"name": "Mug", "category": "kitchen"}
    assert (await client.post("/ai/products/describe", json=body)).status_code in (401, 403)
    _, headers = await make_user()
    assert (await client.post("/ai/products/describe", json=body, headers=headers)).status_code == 403
    assert mock_chat == []


async def test_describe_returns_trimmed_description(client, make_user, mock_chat):
    _, headers = await make_user(admin=True)
    body = {"name": "Blue Mug", "category": "kitchen", "keywords": "ceramic, 350ml"}
    r = await client.post("/ai/products/describe", json=body, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"description": "A lovely product."}

    system, user_turn = mock_chat[0]
    assert "2-3 sentences" in system["content"]
    assert "Do not invent" in system["content"]
    assert "Blue Mug" in user_turn["content"]
    assert "kitchen" in user_turn["content"]
    assert "ceramic, 350ml" in user_turn["content"]


async def test_describe_keywords_optional(client, make_user, mock_chat):
    _, headers = await make_user(admin=True)
    r = await client.post(
        "/ai/products/describe", json={"name": "Mug", "category": "kitchen"}, headers=headers
    )
    assert r.status_code == 200
    assert "Keywords" not in mock_chat[0][1]["content"]


async def test_describe_validation(client, make_user, mock_chat):
    _, headers = await make_user(admin=True)
    for body in ({"category": "x"}, {"name": "x"}, {"name": "", "category": "x"}):
        r = await client.post("/ai/products/describe", json=body, headers=headers)
        assert r.status_code == 422


async def test_describe_503_when_ai_down(client, make_user, ai_down):
    _, headers = await make_user(admin=True)
    r = await client.post(
        "/ai/products/describe", json={"name": "Mug", "category": "kitchen"}, headers=headers
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "AI service unavailable"
