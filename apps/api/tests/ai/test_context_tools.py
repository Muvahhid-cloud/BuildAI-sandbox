import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.db import get_sessionmaker
from app.core.errors import NotFoundError
from app.modules.ai.context import build_project_context
from app.modules.ai.tools import TOOLS, UnknownToolError, load_scope, run_tool
from app.modules.auth.repository import AuthRepository
from app.modules.building.model import BuildingModel
from app.modules.building.requirements import requirement_checks, spec_facts
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import summarize
from tests.ai.helpers import context, profile
from tests.building.helpers import FIXTURE_PATH, SPECS_DIR
from tests.conftest import bearer, register


def demo_model() -> BuildingModel:
    return BuildingModel.model_validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def reference_spec() -> BuildingSpecification:
    path = SPECS_DIR / "01-family-house-280.spec.json"
    return BuildingSpecification.model_validate_json(path.read_text(encoding="utf-8"))


def test_generation_context_reads_minimums_from_the_rules_profile() -> None:
    ctx = context()
    assert ctx.rules_profile == "generic-residential@1"
    by_type = {m.room_type: m for m in ctx.room_minimums}
    assert by_type["bedroom"].min_area_m2 == profile().room("bedroom").min_area_m2
    assert "en_suite" in by_type and "garage" not in by_type


def test_project_context_is_compact_and_references_rooms_by_short_ref() -> None:
    model = demo_model()
    wall = next(el for el in model.elements if el.type == "wall")
    ctx = build_project_context(
        project_id=uuid.uuid4(),
        project_name="Demo",
        region_code="KZ-ALA",
        currency="KZT",
        rules_profile="generic-residential@1",
        model=model,
        selected_id=wall.id,
    )
    assert ctx.summary is not None and ctx.summary.storeys == 2
    assert [r.ref for r in ctx.rooms[:3]] == ["R1", "R2", "R3"]
    assert len(ctx.rooms) == 15
    assert ctx.selected is not None and ctx.selected.type == "wall"
    assert set(ctx.selected.dimensions) == {"length", "thickness", "height"}
    assert len(ctx.model_dump_json()) < len(model.model_dump_json()) / 10


def test_spec_facts_count_en_suites_as_bathrooms() -> None:
    facts = spec_facts(reference_spec())
    assert (facts.bedrooms, facts.bathrooms, facts.wcs) == (4, 3, 1)
    assert facts.garage_cars == 2 and facts.balconies == 1 and not facts.terrace


def test_requirement_checks_compare_request_and_result() -> None:
    spec = reference_spec()
    summary = summarize(demo_model())  # a different house: deviations must show
    checks = {c.key: c for c in requirement_checks(spec, summary, area_tolerance=0.05)}
    assert checks["gross_floor_area_m2"].met is False
    assert checks["gross_floor_area_m2"].requested == "280 m²"
    assert checks["storeys"].met is True
    assert checks["garage"].delivered == "missing" and not checks["garage"].met


async def test_tools_are_read_only_typed_and_ownership_checked(client: Any) -> None:
    owner = await register(client, email="owner@example.com")
    h = bearer(owner["access_token"])
    pid = (await client.post("/api/v1/projects", json={"name": "P"}, headers=h)).json()["id"]
    await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=h)
    client.cookies.clear()
    other = await register(client, email="other@example.com")

    async with get_sessionmaker()() as session:
        repo = AuthRepository(session)
        user = await repo.get_user(uuid.UUID(owner["user"]["id"]))
        intruder = await repo.get_user(uuid.UUID(other["user"]["id"]))
        assert user is not None and intruder is not None
        with pytest.raises(NotFoundError):
            await load_scope(session, intruder, uuid.UUID(pid))
        scope = await load_scope(session, user, uuid.UUID(pid))

    assert set(TOOLS) == {
        "get_project",
        "get_building_summary",
        "get_room",
        "get_selected_object",
        "get_element",
    }
    project = await run_tool(scope, "get_project", {})
    assert project is not None and project["name"] == "P"
    assert project["version"]["source"] == "fixture"
    summary = await run_tool(scope, "get_building_summary", {})
    assert summary is not None and summary["storeys"] == 2
    room = await run_tool(scope, "get_room", {"ref": "R1"})
    assert room is not None and room["ref"] == "R1"
    assert await run_tool(scope, "get_selected_object", {}) is None
    with pytest.raises(ValidationError):
        await run_tool(scope, "get_room", {"ref": "R1", "sql": "DROP TABLE users"})
    with pytest.raises(UnknownToolError):
        await run_tool(scope, "delete_project", {})
