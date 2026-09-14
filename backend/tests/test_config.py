from app.config import get_settings


async def test_settings_use_the_async_postgres_driver():
    """A plain postgresql:// URL silently breaks the async engine at runtime."""
    assert str(get_settings().database_url).startswith("postgresql+asyncpg://")
