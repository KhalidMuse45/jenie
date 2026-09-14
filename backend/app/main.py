"""FastAPI application factory."""

from fastapi import Depends, FastAPI

from app.api import admin, delegation_plans, health, organizations, work_items
from app.api.deps import verify_admin_token
from app.api.errors import register_error_handlers
from app.config import get_settings
from app.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="Jenie",
        version="0.1.0",
        summary="Hierarchical delegation engine",
    )
    register_error_handlers(app)
    app.include_router(health.router)

    # The administrative API is mounted only when a token is configured, so a
    # deployment that never sets one has no administrative surface at all rather
    # than an unprotected one.
    if settings.admin_api_token:
        guarded = [Depends(verify_admin_token)]
        for router in (organizations, work_items, delegation_plans, admin):
            app.include_router(router.router, dependencies=guarded)

    return app


app = create_app()
