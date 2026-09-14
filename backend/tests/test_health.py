from app.config import get_settings
from app.database.session import get_engine, get_sessionmaker


async def test_health_reports_ok_when_database_is_reachable(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "data": {"status": "ok", "database": "ok"},
        "error": None,
    }


async def test_health_reports_503_when_database_is_unreachable(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:1/nope")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
