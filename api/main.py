"""ZANO valuation API.

Run locally:
    uvicorn api.main:create_app --factory --port 8000
"""

from typing import Callable, Optional

from fastapi import FastAPI
from sqlalchemy.orm import Session

from api.routes import router
from api.settings import ApiSettings, load_settings


def create_app(
    settings: Optional[ApiSettings] = None,
    session_factory: Optional[Callable[[], Session]] = None,
) -> FastAPI:
    if session_factory is None:
        from db.database import SessionLocal

        session_factory = SessionLocal

    app = FastAPI(
        title="ZANO Valuation API",
        version="1.0.0",
        description="Market asking-value estimates for Argentine properties, based on comparable listings.",
    )
    app.state.settings = settings or load_settings()
    app.state.session_factory = session_factory
    app.include_router(router)
    return app
