"""
NIRMAN AI — MongoDB Atlas Connection Tester
Run after setting MONGODB_URI in your .env file:
    python scripts/test_mongodb.py
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

# Load .env from project root
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)
    print(f"[.env] Loaded from {env_path}")
else:
    print("[.env] No .env file found — using environment variables")

MONGO_URI = os.getenv("MONGODB_URI", "")
MONGO_DB  = os.getenv("MONGODB_DB", "nirman_ai")

if not MONGO_URI:
    print("\n[ERROR] MONGODB_URI is not set in .env")
    print("  Add this line to your .env file:")
    print('  MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/?retryWrites=true&w=majority')
    sys.exit(1)

# Mask password in displayed URI
def mask_uri(uri: str) -> str:
    try:
        if "@" in uri:
            prefix, rest = uri.split("@", 1)
            if ":" in prefix.split("//", 1)[-1]:
                proto_user, _ = prefix.rsplit(":", 1)
                return f"{proto_user}:****@{rest}"
    except Exception:
        pass
    return uri[:30] + "..."

print(f"\n[MongoDB] Connecting to: {mask_uri(MONGO_URI)}")
print(f"[MongoDB] Database:      {MONGO_DB}\n")


async def run_tests():
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    db     = client[MONGO_DB]
    col    = db["connection_test"]

    # 1. Ping
    try:
        await client.admin.command("ping")
        print("[PASS] 1/4  Ping successful")
    except Exception as e:
        print(f"[FAIL] 1/4  Ping failed: {e}")
        print("\n  Common fixes:")
        print("  - Make sure your IP is in Atlas > Network Access (add 0.0.0.0/0 for dev)")
        print("  - Check your username/password in the connection string")
        client.close()
        sys.exit(1)

    # 2. Insert
    try:
        result = await col.insert_one({"_test": True, "source": "nirman_ai_test"})
        print(f"[PASS] 2/4  Insert OK (id={result.inserted_id})")
    except Exception as e:
        print(f"[FAIL] 2/4  Insert failed: {e}")
        client.close(); sys.exit(1)

    # 3. Find
    try:
        doc = await col.find_one({"_test": True})
        assert doc is not None
        print("[PASS] 3/4  Find OK")
    except Exception as e:
        print(f"[FAIL] 3/4  Find failed: {e}")
        client.close(); sys.exit(1)

    # 4. Delete (cleanup)
    try:
        await col.delete_many({"_test": True})
        print("[PASS] 4/4  Cleanup OK")
    except Exception as e:
        print(f"[WARN] 4/4  Cleanup failed (not critical): {e}")

    client.close()
    print(f"\n[SUCCESS] MongoDB Atlas is connected and working!")
    print(f"          Database '{MONGO_DB}' is ready for NIRMAN AI.\n")


if __name__ == "__main__":
    asyncio.run(run_tests())
