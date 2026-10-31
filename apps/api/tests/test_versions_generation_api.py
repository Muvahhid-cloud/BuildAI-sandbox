import json
import uuid
from typing import Any

from app.modules.jobs.runner import job_runner
from tests.building.helpers import SPECS_DIR
from tests.conftest import bearer, register

SPEC = json.loads((SPECS_DIR / "02-compact-bungalow-90.spec.json").read_text(encoding="utf-8"))


async def _auth(client: Any, email: str = "ada@example.com") -> dict[str, str]:
    client.cookies.clear()
    return bearer((await register(client, email=email))["access_token"])


async def _project(client: Any, h: dict[str, str], name: str = "House") -> str:
    resp = await client.post("/api/v1/projects", json={"name": name}, headers=h)
    assert resp.status_code == 201, resp.text
    pid: str = resp.json()["id"]
    return pid


async def _generate(
    client: Any, h: dict[str, str], pid: str, body: dict[str, Any]
) -> dict[str, Any]:
    resp = await client.post(f"/api/v1/projects/{pid}/generate", json=body, headers=h)
    assert resp.status_code == 202, resp.text
    job: dict[str, Any] = resp.json()
    assert job["status"] == "queued" and job["stage"] == "queued"
    await job_runner.drain()
    done = await client.get(f"/api/v1/jobs/{job['id']}", headers=h)
    assert done.status_code == 200
    result: dict[str, Any] = done.json()
    return result


# --- versions -----------------------------------------------------------------------------------


async def test_new_project_has_no_versions(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    resp = await client.get(f"/api/v1/projects/{pid}/versions", headers=h)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


async def test_import_demo_creates_version_and_moves_head(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    resp = await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=h)
    assert resp.status_code == 201, resp.text
    v = resp.json()
    assert v["number"] == 1 and v["source"] == "fixture" and v["spec"] is None
    assert v["model"]["engine_version"] == "fixture@1"
    assert v["summary"]["gross_floor_area_m2"] == 240.0
    assert v["issues"] == []  # demo house: no rules findings, no model warnings
    assert len(v["model_hash"]) == 64
    project = (await client.get(f"/api/v1/projects/{pid}", headers=h)).json()
    assert project["current_version_id"] == v["id"]

    listed = (await client.get(f"/api/v1/projects/{pid}/versions", headers=h)).json()["items"]
    assert [x["number"] for x in listed] == [1]
    assert "model" not in listed[0]  # lists carry summaries only

    again = (await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=h)).json()
    assert again["number"] == 2 and again["parent_version_id"] == v["id"]


async def test_versions_are_private(client: Any) -> None:
    owner = await _auth(client, "owner@example.com")
    pid = await _project(client, owner)
    vid = (await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=owner)).json()["id"]
    intruder = await _auth(client, "intruder@example.com")
    assert (
        await client.get(f"/api/v1/projects/{pid}/versions", headers=intruder)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{pid}/versions/{vid}", headers=intruder)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=intruder)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{pid}/versions/{uuid.uuid4()}", headers=owner)
    ).status_code == 404


# --- spec validation ------------------------------------------------------------------------------


async def test_validate_spec(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    ok = await client.post(f"/api/v1/projects/{pid}/spec/validate", json={"spec": SPEC}, headers=h)
    assert ok.status_code == 200
    assert ok.json() == {"valid": True, "issues": [], "rules_profile": "generic-residential@1"}

    bad = {**SPEC, "rooms": [{"key": "bedroom", "type": "bedroom", "target_area_m2": 5}]}
    resp = await client.post(f"/api/v1/projects/{pid}/spec/validate", json={"spec": bad}, headers=h)
    body = resp.json()
    assert body["valid"] is False
    codes = {i["code"] for i in body["issues"]}
    assert {"SPEC_AREA_BELOW_MINIMUM", "SPEC_NO_BATHROOM"} <= codes


async def test_schema_errors_carry_json_pointers(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    bad = {**SPEC, "targets": {"storeys": 5}}
    resp = await client.post(f"/api/v1/projects/{pid}/spec/validate", json={"spec": bad}, headers=h)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["path"] == "/spec/targets/storeys"


# --- generation --------------------------------------------------------------------------------


async def test_generate_creates_a_version(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    job = await _generate(client, h, pid, {"spec": SPEC, "seed": 3})
    assert job["status"] == "succeeded", job
    assert job["stage"] == "done" and job["progress"] == 1.0
    vid = job["result"]["version_id"]
    assert job["result"]["summary"]["bedrooms"] == 2

    v = (await client.get(f"/api/v1/projects/{pid}/versions/{vid}", headers=h)).json()
    assert v["source"] == "generation"
    assert v["seed"] == 3 and v["model"]["seed"] == 3
    assert v["engine_version"].startswith("layout@")
    assert v["rules_profile"] == "generic-residential@1"
    assert v["spec"]["name"] == SPEC["name"]
    assert v["report"]["metrics"]["candidates_evaluated"] > 0
    assert v["issues"] == []
    project = (await client.get(f"/api/v1/projects/{pid}", headers=h)).json()
    assert project["current_version_id"] == vid

    # Same spec + seed in the same project -> identical model (ids are namespaced by project).
    again = await _generate(client, h, pid, {"spec": SPEC, "seed": 3})
    v2 = (
        await client.get(
            f"/api/v1/projects/{pid}/versions/{again['result']['version_id']}", headers=h
        )
    ).json()
    assert v2["number"] == 2
    assert v2["model_hash"] == v["model_hash"]


async def test_invalid_spec_is_rejected_before_a_job_starts(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    bad = {**SPEC, "rooms": [{"key": "bedroom", "type": "bedroom"}]}
    resp = await client.post(f"/api/v1/projects/{pid}/generate", json={"spec": bad}, headers=h)
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "SPEC_INVALID"
    assert any(d["code"] == "SPEC_NO_BATHROOM" for d in err["details"])


async def test_infeasible_spec_fails_the_job_with_reasons(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    # Valid by the rules, but the plot is far too narrow for any layout.
    spec = {**SPEC, "site": {"plot_width_m": 4.5, "plot_depth_m": 60}}
    job = await _generate(client, h, pid, {"spec": spec})
    assert job["status"] == "failed"
    assert job["error"]["code"] == "LAYOUT_INFEASIBLE"
    assert job["error"]["details"]
    assert (await client.get(f"/api/v1/projects/{pid}/versions", headers=h)).json()["items"] == []


async def test_generation_requires_auth_and_ownership(client: Any) -> None:
    owner = await _auth(client, "owner@example.com")
    pid = await _project(client, owner)
    assert (
        await client.post(f"/api/v1/projects/{pid}/generate", json={"spec": SPEC})
    ).status_code == 401
    job = await _generate(client, owner, pid, {"spec": SPEC})
    intruder = await _auth(client, "intruder@example.com")
    assert (
        await client.post(f"/api/v1/projects/{pid}/generate", json={"spec": SPEC}, headers=intruder)
    ).status_code == 404
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=intruder)).status_code == 404


async def test_one_generation_at_a_time_per_project(client: Any) -> None:
    from app.core.db import get_sessionmaker
    from app.modules.jobs.models import Job

    h = await _auth(client)
    pid = await _project(client, h)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    async with get_sessionmaker()() as session:
        session.add(
            Job(
                project_id=uuid.UUID(pid),
                user_id=uuid.UUID(me["id"]),
                kind="generate",
                status="running",
                stage="layout",
                input={},
            )
        )
        await session.commit()
    resp = await client.post(f"/api/v1/projects/{pid}/generate", json={"spec": SPEC}, headers=h)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "GENERATION_IN_PROGRESS"


async def test_interrupted_jobs_are_failed_on_startup(client: Any) -> None:
    from app.core.db import get_sessionmaker
    from app.modules.jobs.models import Job
    from app.modules.jobs.repository import JobRepository

    h = await _auth(client)
    pid = await _project(client, h)
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    async with get_sessionmaker()() as session:
        job = Job(
            project_id=uuid.UUID(pid),
            user_id=uuid.UUID(me["id"]),
            kind="generate",
            status="queued",
            input={},
        )
        session.add(job)
        await session.commit()
        job_id = job.id
    async with get_sessionmaker()() as session:
        assert await JobRepository(session).fail_interrupted() == 1
        await session.commit()
    body = (await client.get(f"/api/v1/jobs/{job_id}", headers=h)).json()
    assert body["status"] == "failed" and body["error"]["code"] == "JOB_INTERRUPTED"


async def test_legacy_1_0_0_version_is_upgraded_on_read_without_rewriting(client: Any) -> None:
    """A stored BuildingModel 1.0.0 row is served as a valid current (1.2.0) model; the row
    (JSON, schema version, hash) is never rewritten — versions are immutable."""
    from sqlalchemy import select

    from app.core.db import get_sessionmaker
    from app.modules.versions.models import ProjectVersion
    from tests.building.test_migrations import DEMO_V1_0

    h = await _auth(client)
    pid = await _project(client, h)
    created = (await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=h)).json()
    legacy = json.loads(DEMO_V1_0.read_text(encoding="utf-8"))
    async with get_sessionmaker()() as session:
        row = await session.get(ProjectVersion, uuid.UUID(created["id"]))
        assert row is not None
        row.model = legacy  # simulate a row written before schema 1.1.0
        row.schema_version = "1.0.0"
        stored_hash = row.model_hash
        await session.commit()

    resp = await client.get(f"/api/v1/projects/{pid}/versions/{created['id']}", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"]["schema_version"] == "1.2.0"
    assert body["model"]["design"] is None
    assert body["model"]["types"] == [] and body["model"]["assemblies"] == []
    assert all(el["type_ref"] is None for el in body["model"]["elements"])
    assert body["model_hash"] == stored_hash
    assert body["schema_version"] == "1.0.0"  # what is stored, not what is served
    assert body["issues"] == []

    async with get_sessionmaker()() as session:
        stored = (
            await session.execute(
                select(ProjectVersion).where(ProjectVersion.id == uuid.UUID(created["id"]))
            )
        ).scalar_one()
        assert stored.model == legacy and stored.schema_version == "1.0.0"
        assert stored.model_hash == stored_hash
