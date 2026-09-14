"""FastAPI application factory."""

from fastapi import FastAPI

from app.api import health
from app.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="Jenie",
        version="0.1.0",
        summary="Hierarchical delegation engine",
    )
    app.include_router(health.router)
    return app


app = create_app()
