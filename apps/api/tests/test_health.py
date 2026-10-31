from typing import Any


async def test_health(client: Any) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "not a replacement for licensed" in body["disclaimer"]


async def test_health_db_reports_postgres_version(client: Any) -> None:
    resp = await client.get("/health/db")
    assert resp.status_code == 200, resp.text
    assert resp.json()["postgres"].split(".")[0].isdigit()


async def test_unknown_route_uses_error_envelope(client: Any) -> None:
    resp = await client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"
