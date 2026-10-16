"""FastAPI dependencies. Collaborators live on app.state so tests can inject their own."""

from typing import Iterator, Optional

from fastapi import Depends, HTTPException, Request, Response, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from api.keys import hash_api_key

# auto_error=False so a missing key gets the same 401 body as an invalid one.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def require_client(request: Request, x_api_key: Optional[str] = Security(api_key_header)) -> str:
    """Return the client name owning the API key, or reject the request with 401."""
    client = request.app.state.settings.api_keys.get(hash_api_key(x_api_key)) if x_api_key else None
    if client is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_api_key", "message": "Missing or invalid X-API-Key header"},
        )
    return client


def enforce_rate_limit(request: Request, response: Response, client: str = Depends(require_client)) -> str:
    """Count the request against the client's quota; reject with 429 once exceeded."""
    decision = request.app.state.rate_limiter.hit(client)
    headers = {"X-RateLimit-Limit": str(decision.limit), "X-RateLimit-Remaining": str(decision.remaining)}
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limit_exceeded", "message": "Too many requests for this API key"},
            headers={**headers, "Retry-After": str(decision.retry_after_seconds)},
        )
    response.headers.update(headers)
    return client
