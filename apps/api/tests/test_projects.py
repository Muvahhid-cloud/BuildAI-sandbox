import uuid
from typing import Any

from tests.conftest import bearer, register


async def _auth(client: Any, email: str = "ada@example.com") -> dict[str, str]:
    client.cookies.clear()
    return bearer((await register(client, email=email))["access_token"])


async def test_projects_require_auth(client: Any) -> None:
    assert (await client.get("/api/v1/projects")).status_code == 401


async def test_create_uses_kazakhstan_defaults(client: Any) -> None:
    h = await _auth(client)
    resp = await client.post("/api/v1/projects", json={"name": "  Family house "}, headers=h)
    assert resp.status_code == 201, resp.text
    p = resp.json()
    assert p["name"] == "Family house"
    assert p["currency"] == "KZT"
    assert p["region_code"] == "KZ-ALA"
    assert p["rules_profile_id"] == "generic-residential@1"
    assert p["building_type"] == "single_family_house"
    assert p["current_version_id"] is None


async def test_currency_must_be_iso_code(client: Any) -> None:
    h = await _auth(client)
    resp = await client.post("/api/v1/projects", json={"name": "X", "currency": "usd"}, headers=h)
    assert resp.status_code == 422
    ok = await client.post("/api/v1/projects", json={"name": "X", "currency": "USD"}, headers=h)
    assert ok.json()["currency"] == "USD"


async def test_crud_roundtrip(client: Any) -> None:
    h = await _auth(client)
    pid = (await client.post("/api/v1/projects", json={"name": "A"}, headers=h)).json()["id"]

    listed = (await client.get("/api/v1/projects", headers=h)).json()["items"]
    assert [p["id"] for p in listed] == [pid]

    patched = await client.patch(
        f"/api/v1/projects/{pid}", json={"name": "B", "description": "two storeys"}, headers=h
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "B"
    assert patched.json()["description"] == "two storeys"

    assert (await client.delete(f"/api/v1/projects/{pid}", headers=h)).status_code == 204
    assert (await client.get(f"/api/v1/projects/{pid}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/projects", headers=h)).json()["items"] == []


async def test_other_users_cannot_see_project(client: Any) -> None:
    owner = await _auth(client, "owner@example.com")
    pid = (await client.post("/api/v1/projects", json={"name": "Mine"}, headers=owner)).json()["id"]

    intruder = await _auth(client, "intruder@example.com")
    assert (await client.get(f"/api/v1/projects/{pid}", headers=intruder)).status_code == 404
    assert (
        await client.patch(f"/api/v1/projects/{pid}", json={"name": "x"}, headers=intruder)
    ).status_code == 404
    assert (await client.delete(f"/api/v1/projects/{pid}", headers=intruder)).status_code == 404
    assert (await client.get("/api/v1/projects", headers=intruder)).json()["items"] == []


async def test_unknown_project_404(client: Any) -> None:
    h = await _auth(client)
    assert (await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=h)).status_code == 404
