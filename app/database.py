import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment variables from a .env file into the process environment
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

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
    except Exception as exc:
        print(f"MongoDB connection failed: {exc}")
        return False
