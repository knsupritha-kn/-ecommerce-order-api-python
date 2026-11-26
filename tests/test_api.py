from bson import ObjectId

from tests.conftest import PASSWORD

ADDRESS = {"items": [], "shipping_address": "1 Test St"}


# ---------- auth ----------

async def test_register(client, db):
    r = await client.post(
        "/auth/register", json={"name": "Ann", "email": "ann@example.com", "password": PASSWORD}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "ann@example.com"
    assert body["role"] == "user"
    stored = await db.users.find_one({"email": "ann@example.com"})
    assert stored["password"] != PASSWORD  # hashed


async def test_login(client, make_user):
    user, _ = await make_user()
    r = await client.post("/auth/login", json={"email": user["email"], "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert r.json()["access_token"]


async def test_login_wrong_password(client, make_user):
    user, _ = await make_user()
    r = await client.post("/auth/login", json={"email": user["email"], "password": "wrong-password"})
    assert r.status_code == 401


# ---------- products / cart ----------

async def test_list_products(client, make_product):
    await make_product(name="Alpha")
    await make_product(name="Beta")
    r = await client.get("/products")
    assert r.status_code == 200
    assert {p["name"] for p in r.json()} == {"Alpha", "Beta"}


async def test_add_to_cart(client, make_user, make_product):
    _, headers = await make_user()
    pid = await make_product(price=10.0, stock=5)
    r = await client.post("/cart", json={"product_id": pid, "quantity": 2}, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["items"] == [{"product_id": pid, "quantity": 2}]
    assert body["total"] == 20.0


# ---------- orders ----------

async def test_place_order(client, db, make_user, make_product):
    user, headers = await make_user()
    pid = await make_product(price=10.0, stock=5)
    await client.post("/cart", json={"product_id": pid, "quantity": 2}, headers=headers)

    r = await client.post("/orders", json=ADDRESS, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["user_id"] == user["id"]
    assert body["total"] == 20.0
    assert body["status"] == "pending"
    assert (await db.products.find_one({"_id": ObjectId(pid)}))["stock"] == 3
    assert await db.cart.count_documents({}) == 0  # cart cleared


async def test_order_fails_when_stock_too_low(client, db, make_user, make_product):
    _, headers = await make_user()
    pid = await make_product(stock=5)
    await client.post("/cart", json={"product_id": pid, "quantity": 3}, headers=headers)
    # Stock drops after the item was carted
    await db.products.update_one({"_id": ObjectId(pid)}, {"$set": {"stock": 1}})

    r = await client.post("/orders", json=ADDRESS, headers=headers)
    assert r.status_code == 400
    assert await db.orders.count_documents({}) == 0


async def test_stock_never_goes_negative(client, db, make_user, make_product):
    _, h1 = await make_user()
    _, h2 = await make_user()
    pid = await make_product(stock=5)
    # Both carts are valid individually (3 <= 5), but together they oversell.
    await client.post("/cart", json={"product_id": pid, "quantity": 3}, headers=h1)
    await client.post("/cart", json={"product_id": pid, "quantity": 3}, headers=h2)

    assert (await client.post("/orders", json=ADDRESS, headers=h1)).status_code == 201
    assert (await client.post("/orders", json=ADDRESS, headers=h2)).status_code == 400

    assert (await db.products.find_one({"_id": ObjectId(pid)}))["stock"] == 2
    assert await db.orders.count_documents({}) == 1


async def test_user_cannot_see_another_users_order(client, make_user, make_product):
    _, owner = await make_user()
    _, other = await make_user()
    pid = await make_product()
    await client.post("/cart", json={"product_id": pid, "quantity": 1}, headers=owner)
    order_id = (await client.post("/orders", json=ADDRESS, headers=owner)).json()["id"]

    assert (await client.get(f"/orders/{order_id}", headers=owner)).status_code == 200
    assert (await client.get(f"/orders/{order_id}", headers=other)).status_code == 403
    assert (await client.get("/orders", headers=other)).json() == []


async def test_non_admin_cannot_update_order_status(client, make_user, make_product):
    _, headers = await make_user()
    _, admin_headers = await make_user(admin=True)
    pid = await make_product()
    await client.post("/cart", json={"product_id": pid, "quantity": 1}, headers=headers)
    order_id = (await client.post("/orders", json=ADDRESS, headers=headers)).json()["id"]

    r = await client.put(f"/orders/{order_id}/status", json={"status": "shipped"}, headers=headers)
    assert r.status_code == 403
    assert (await client.get(f"/orders/{order_id}", headers=headers)).json()["status"] == "pending"

    # Sanity check: an admin can do it
    r = await client.put(
        f"/orders/{order_id}/status", json={"status": "shipped"}, headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "shipped"
