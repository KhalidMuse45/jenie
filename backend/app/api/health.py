"""Liveness and readiness endpoint."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.envelope import fail, ok
from app.database.session import get_sessionmaker

router = APIRouter(tags=["health"])


async def _database_reachable() -> bool:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


@router.get("/health")
async def health() -> JSONResponse:
    """Report process and database health.

    Returns 503 when the database is unreachable so a deploy or process manager
    can tell "running" apart from "actually able to serve".
    """
    if not await _database_reachable():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=fail("database_unavailable", "The database is not reachable."),
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=ok({"status": "ok", "database": "ok"}),
    )
