"""FastAPI dependencies. Collaborators live on app.state so tests can inject their own."""

from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session
