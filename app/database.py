from motor.motor_asyncio import AsyncIOMotorClient

from app.config import require_env

# Raises a clear error at startup if MONGO_URI is not set
MONGO_URI = require_env("MONGO_URI")

# Create a single async MongoDB client for the app to reuse
client = AsyncIOMotorClient(MONGO_URI)

# Expose the database instance for use across the app (e.g. app.database.db)
# The Atlas URI has no database name in its path, so name it explicitly.
db = client.get_database("ecommerce")


async def test_connection() -> bool:
    """Ping MongoDB to verify the connection is working."""
    try:
        await client.admin.command("ping")
        print("MongoDB connection successful.")
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "not connected"
        print(f"MongoDB connection failed: {exc}")
        return False
