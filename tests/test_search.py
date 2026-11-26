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
    assert len(body) == 1  # the unrelated products fall below SEARCH_MIN_SCORE
    assert body[0]["name"] == "Gaming laptop"
    assert all("embedding" not in p for p in body)


async def test_search_min_score_filters_and_logs(client, make_user, fake_embed, monkeypatch, caplog):
    import logging

    from app import config

    _, headers = await make_user(admin=True)
    for name in ["Trail shoe", "Gaming laptop"]:
        await client.post("/products", json=product_body(name), headers=headers)

    monkeypatch.setattr(config, "SEARCH_MIN_SCORE", -1.0)  # everything passes
    r = await client.get("/products/search", params={"q": "laptop"})
    assert len(r.json()) == 2

    monkeypatch.setattr(config, "SEARCH_MIN_SCORE", 0.5)
    with caplog.at_level(logging.DEBUG, logger="app.routes.products"):
        r = await client.get("/products/search", params={"q": "laptop"})
    assert [p["name"] for p in r.json()] == ["Gaming laptop"]
    assert "score=" in caplog.text and "drop" in caplog.text

    r = await client.get("/products/search", params={"q": "zzz"})  # matches nothing
    assert r.json() == []


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


async def test_empty_vector_search_falls_back_to_cosine(client, db, make_user, fake_embed, monkeypatch):
    from app import config
    from app.routes import products

    _, headers = await make_user(admin=True)
    for name in ["Trail shoe", "Gaming laptop"]:
        await client.post("/products", json=product_body(name), headers=headers)

    calls = []

    class EmptyCursor:
        async def to_list(self, length=None):
            return []

    class ProductsProxy:
        def __init__(self, real):
            self._real = real

        def aggregate(self, pipeline):
            calls.append(pipeline)
            return EmptyCursor()

        def __getattr__(self, name):
            return getattr(self._real, name)

    class DbProxy:
        products = ProductsProxy(db.products)

        def __getattr__(self, name):
            return getattr(db, name)

    monkeypatch.setattr(config, "USE_ATLAS_VECTOR_SEARCH", True)
    monkeypatch.setattr(products, "db", DbProxy())
    r = await client.get("/products/search", params={"q": "laptop", "limit": 2})
    assert calls, "$vectorSearch should have been tried"
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["Gaming laptop"]
