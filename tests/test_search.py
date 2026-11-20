import pytest

from app.ai import llm

KEYWORDS = ["shoe", "laptop", "book"]


def fake_vector(text: str) -> list[float]:
    t = text.lower()
    return [float(t.count(k)) for k in KEYWORDS] + [0.01]


@pytest.fixture
def fake_embed(monkeypatch):
    async def embed(text):
        return fake_vector(text)

    monkeypatch.setattr(llm, "embed", embed)


@pytest.fixture
def ai_down(monkeypatch):
    async def embed(text):
        raise llm.AIUnavailableError("down")

    monkeypatch.setattr(llm, "embed", embed)


def product_body(name, description="d", category="misc"):
    return {"name": name, "description": description, "price": 5.0, "stock": 3, "category": category}


async def test_create_product_stores_embedding_but_hides_it(client, db, make_user, fake_embed):
    _, headers = await make_user(admin=True)
    r = await client.post("/products", json=product_body("Running shoe", "a shoe", "sport"), headers=headers)
    assert r.status_code == 201
    assert "embedding" not in r.json()
    stored = await db.products.find_one({"name": "Running shoe"})
    assert stored["embedding"] == fake_vector("Running shoe a shoe sport")


async def test_create_product_without_ai_still_saves(client, db, make_user, ai_down):
    _, headers = await make_user(admin=True)
    r = await client.post("/products", json=product_body("Plain"), headers=headers)
    assert r.status_code == 201
    assert "embedding" not in await db.products.find_one({"name": "Plain"})


async def test_update_refreshes_and_clears_stale_embedding(client, db, make_user, fake_embed, monkeypatch):
    _, headers = await make_user(admin=True)
    pid = (await client.post("/products", json=product_body("shoe"), headers=headers)).json()["id"]
    r = await client.put(f"/products/{pid}", json=product_body("laptop"), headers=headers)
    assert r.status_code == 200 and "embedding" not in r.json()
    assert (await db.products.find_one({"name": "laptop"}))["embedding"][1] == 1.0

    async def down(text):
        raise llm.AIUnavailableError("down")

    monkeypatch.setattr(llm, "embed", down)
    await client.put(f"/products/{pid}", json=product_body("book"), headers=headers)
    assert "embedding" not in await db.products.find_one({"name": "book"})


async def test_reindex_admin_only(client, make_user, fake_embed):
    _, headers = await make_user()
    assert (await client.post("/ai/products/reindex", headers=headers)).status_code == 403
    assert (await client.post("/ai/products/reindex")).status_code in (401, 403)


async def test_reindex_embeds_existing_products(client, db, make_user, make_product, fake_embed):
    _, headers = await make_user(admin=True)
    await make_product(name="shoe")
    await make_product(name="laptop")
    r = await client.post("/ai/products/reindex", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"indexed": 2, "failed": 0}
    assert await db.products.count_documents({"embedding": {"$exists": True}}) == 2


async def test_reindex_503_when_ai_down(client, make_user, make_product, ai_down):
    _, headers = await make_user(admin=True)
    await make_product()
    r = await client.post("/ai/products/reindex", headers=headers)
    assert r.status_code == 503
    assert r.json()["detail"] == "AI service unavailable"


async def test_search_ranks_by_similarity_and_hides_embedding(client, db, make_user, fake_embed):
    _, headers = await make_user(admin=True)
    for name in ["Trail shoe", "Gaming laptop", "Novel book"]:
        await client.post("/products", json=product_body(name), headers=headers)
    r = await client.get("/products/search", params={"q": "laptop", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["name"] == "Gaming laptop"
    assert all("embedding" not in p for p in body)


async def test_search_skips_products_without_embedding(client, make_product, fake_embed):
    await make_product(name="laptop")  # inserted directly, no embedding
    r = await client.get("/products/search", params={"q": "laptop"})
    assert r.status_code == 200
    assert r.json() == []


async def test_search_validation_and_503(client, ai_down):
    assert (await client.get("/products/search")).status_code == 422
    assert (await client.get("/products/search", params={"q": "x", "limit": 0})).status_code == 422
    r = await client.get("/products/search", params={"q": "x"})
    assert r.status_code == 503


async def test_search_route_not_shadowed_by_product_id(client, fake_embed):
    r = await client.get("/products/search", params={"q": "shoe"})
    assert r.status_code == 200
