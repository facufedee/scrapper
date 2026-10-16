"""API configuration, read from environment variables (and .env via config)."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ApiSettings:
    # sha256 hex digest of the API key -> client name. Empty means every request is rejected.
    api_keys: dict[str, str] = field(default_factory=dict)


def parse_api_keys(raw: Optional[str]) -> dict[str, str]:
    """Parse "client:sha256hex,client2:sha256hex" into {sha256hex: client}."""
    keys: dict[str, str] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        client, separator, digest = entry.partition(":")
        if not separator or not client.strip() or not digest.strip():
            raise ValueError(f"Malformed ZANO_API_KEYS entry {entry!r}; expected client:sha256hex")
        keys[digest.strip().lower()] = client.strip()
    return keys


def load_settings() -> ApiSettings:
    import config  # noqa: F401  (loads .env into the environment)

    return ApiSettings(api_keys=parse_api_keys(os.getenv("ZANO_API_KEYS")))
