"""API key generation and hashing.

Only key hashes are stored server-side (ZANO_API_KEYS), so a leaked config file does not
leak usable keys. Generate a key for a new client with:

    python -m api.keys <client-name>
"""

import hashlib
import secrets
import sys

KEY_PREFIX = "zano_"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_api_key(key)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m api.keys <client-name>")
    client = sys.argv[1]
    key, digest = generate_api_key()
    print(f"API key for {client} (give it to the client, it is not stored anywhere):\n  {key}")
    print(f"Add this entry to ZANO_API_KEYS (comma-separated):\n  {client}:{digest}")
