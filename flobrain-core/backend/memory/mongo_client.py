import os

from pymongo import MongoClient

host = os.environ.get("MONGO_HOST", "localhost")
port = os.environ.get("MONGO_PORT", "27017")


def mongo_timeout_ms() -> int:
    """Selection and connect timeout. Default 2s so a missing Mongo does not stall health."""
    raw = os.environ.get("MONGO_TIMEOUT_MS", "2000").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 2000
    return value if value > 0 else 2000


_timeout = mongo_timeout_ms()
client = MongoClient(
    f"mongodb://{host}:{port}/",
    serverSelectionTimeoutMS=_timeout,
    connectTimeoutMS=_timeout,
)
db = client["flobrain"]
