"""Shared test fixtures.

DATABASE_URL is redirected at the test database *before* any application module
is imported, so the cached settings never see the development database.
"""

import os

TEST_DATABASE_URL = os.environ.get(
    "JENIE_TEST_DATABASE_URL",
    "postgresql+asyncpg://localhost/jenie_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# The administrative API is only mounted when a token is configured.
ADMIN_TOKEN = "test-administrative-token"
os.environ["ADMIN_API_TOKEN"] = ADMIN_TOKEN

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database.models.base import Base  # noqa: E402
from app.database.session import get_engine, get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
async def isolated_engine():
    """Give every test its own engine, bound to that test's event loop.

    The engine is cached process-wide via lru_cache. Reusing one across tests
    would bind it to the first test's event loop and every later test would fail
    with "attached to a different loop", so the caches are cleared either side.
    """
    _clear_caches()
    try:
        yield
    finally:
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
        _clear_caches()


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture
async def database():
    """Create the schema for a test and drop it afterwards."""
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def session(database):
    async with get_sessionmaker()() as db_session:
        yield db_session


@pytest.fixture
async def client():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def api(database):
    """A client for the administrative API, already holding the token.

    Depends on ``database`` because these requests open their own sessions and
    need the schema to exist.
    """
    transport = ASGITransport(app=create_app())
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Jenie-Admin-Token": ADMIN_TOKEN},
    ) as http_client:
        yield http_client


def acting_as(membership) -> dict[str, str]:
    return {"X-Jenie-Actor": str(membership.id)}
