"""API configuration, read from environment variables (and .env via config)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiSettings:
    pass


def load_settings() -> ApiSettings:
    import config  # noqa: F401  (loads .env into the environment)

    return ApiSettings()
