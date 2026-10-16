"""FastAPI dependencies. Collaborators live on app.state so tests can inject their own."""

from typing import Iterator, Optional

from fastapi import Header, HTTPException, Request
from sqlalchemy.orm import Session

from api.keys import hash_api_key


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def require_client(
    request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")
) -> str:
    """Return the client name owning the API key, or reject the request with 401."""
    client = request.app.state.settings.api_keys.get(hash_api_key(x_api_key)) if x_api_key else None
    if client is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_api_key", "message": "Missing or invalid X-API-Key header"},
        )
    return client
