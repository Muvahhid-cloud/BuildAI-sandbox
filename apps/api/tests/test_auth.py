from typing import Any

from app.modules.auth.router import REFRESH_COOKIE
from tests.conftest import bearer, register


async def test_register_returns_tokens_and_sets_refresh_cookie(client: Any) -> None:
    data = await register(client, email="  Ada@Example.COM ")
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 15 * 60
    assert data["user"]["email"] == "ada@example.com"  # normalized
    assert client.cookies.get(REFRESH_COOKIE)


async def test_register_duplicate_email_conflicts(client: Any) -> None:
    await register(client)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "ADA@example.com", "password": "another-password", "display_name": "A"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


async def test_register_validation_error_has_json_pointer_paths(client: Any) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short", "display_name": ""},
    )
    assert resp.status_code == 422
    paths = {d["path"] for d in resp.json()["error"]["details"]}
    assert {"/email", "/password", "/display_name"} <= paths


async def test_login_and_me(client: Any) -> None:
    await register(client)
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "correct-horse-battery"}
    )
    assert resp.status_code == 200
    me = await client.get("/api/v1/auth/me", headers=bearer(resp.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"


async def test_login_wrong_password(client: Any) -> None:
    await register(client)
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong-password!"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


async def test_me_requires_valid_token(client: Any) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=bearer("garbage"))).status_code == 401


async def test_refresh_rotates_token(client: Any) -> None:
    await register(client)
    first = client.cookies.get(REFRESH_COOKIE)
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    second = client.cookies.get(REFRESH_COOKIE)
    assert second and second != first
    me = await client.get("/api/v1/auth/me", headers=bearer(resp.json()["access_token"]))
    assert me.status_code == 200


async def test_refresh_token_reuse_revokes_family(client: Any) -> None:
    await register(client)
    stolen = client.cookies.get(REFRESH_COOKIE)
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200  # rotates
    current = client.cookies.get(REFRESH_COOKIE)

    client.cookies.set(REFRESH_COOKIE, stolen, path="/api/v1/auth")
    reuse = await client.post("/api/v1/auth/refresh")
    assert reuse.status_code == 401

    # The legitimate latest token is revoked too.
    client.cookies.set(REFRESH_COOKIE, current, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh_token(client: Any) -> None:
    await register(client)
    token = client.cookies.get(REFRESH_COOKIE)
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.set(REFRESH_COOKIE, token, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
