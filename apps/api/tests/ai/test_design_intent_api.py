"""K3 end to end (real API + PostgreSQL, MockAIProvider): natural-language design intent reaches
the stored BuildingModel — checked on the model's walls, windows and rooms."""

import math
from typing import Any

from app.modules.building.appearance import PALETTE
from tests.ai.test_generation_api import _auth, _generate, _project

K3_PROMPT = (
    "Create a realistic two-story modern family house of approximately 220 m². Ground floor: "
    "entrance hall, large living room, open kitchen and dining area, guest WC, utility/laundry "
    "room and attached two-car garage. Second floor: master bedroom with private bathroom, two "
    "additional bedrooms and one shared bathroom. Make the exterior walls yellow. Place large "
    "panoramic windows primarily on the backyard-facing facade. Do not place large panoramic "
    "windows on the front facade. The living room and dining area should face the backyard."
)


def _facade(wall: dict[str, Any]) -> str:
    angle = wall["rotation"]["z"]
    nx, ny = math.sin(angle), -math.cos(angle)
    if abs(ny) >= abs(nx):
        return "front" if ny < 0 else "rear"
    return "left" if nx < 0 else "right"


async def test_design_intent_reaches_the_generated_model(client: Any) -> None:
    h = await _auth(client, "k3@example.com")
    pid = await _project(client, h)
    gen = await _generate(client, h, {"project_id": pid, "prompt": K3_PROMPT})
    assert gen["status"] == "completed", gen["error"]

    spec = gen["specification"]
    assert spec["design"]["facade_color"] == "yellow"
    assert spec["design"]["windows"] == {
        "emphasis": "panoramic",
        "preferred_facades": ["rear"],
        "excluded_facades": ["front"],
    }
    checks = {c["key"]: c for c in gen["checks"]}
    assert checks["facade_color"]["met"], checks["facade_color"]
    assert checks["windows_rear"]["met"] and checks["no_windows_front"]["met"]
    assert checks["faces_living"]["met"] and checks["faces_dining"]["met"]

    version = (
        await client.get(f"/api/v1/projects/{pid}/versions/{gen['version_id']}", headers=h)
    ).json()
    model = version["model"]
    assert version["issues"] == []
    assert model["schema_version"] == "1.2.0"
    assert model["design"]["facade_color"] == {
        "hex": PALETTE["yellow"],
        "name": "yellow",
        "source": "user",
    }
    walls = {el["id"]: el for el in model["elements"] if el["type"] == "wall"}
    exterior = [w for w in walls.values() if w["properties"]["wall_kind"] == "exterior"]
    assert {w["properties"]["finish_right_color"] for w in exterior} == {PALETTE["yellow"]}
    panoramic_facades = set()
    for el in model["elements"]:
        if el["type"] == "window" and el["properties"]["size_class"] == "panoramic":
            host = next(r["target_id"] for r in el["relationships"] if r["kind"] == "hosted_by")
            panoramic_facades.add(_facade(walls[host]))
    assert panoramic_facades == {"rear"}


async def test_design_options_list_drafts_as_unavailable(client: Any) -> None:
    h = await _auth(client, "options@example.com")
    resp = await client.get("/api/v1/design-options", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] == []
    assert {d["id"] for d in body["unavailable"]} == {
        "modern-minimal",
        "contemporary-warm",
        "classic-brick",
        "scandinavian-timber",
    }
    assert all("draft" in d["reason"] for d in body["unavailable"])
    assert {"name": "yellow", "hex": PALETTE["yellow"]} in body["palette"]
    assert (await client.get("/api/v1/design-options")).status_code == 401


async def test_spec_form_refuses_a_draft_design_system(client: Any) -> None:
    h = await _auth(client, "form@example.com")
    pid = await _project(client, h)
    spec = {
        "name": "House",
        "targets": {"storeys": 1},
        "style": {"design_system": "modern-minimal"},
        "rooms": [{"key": "bedroom", "type": "bedroom"}, {"key": "bath", "type": "bathroom"}],
    }
    resp = await client.post(
        f"/api/v1/projects/{pid}/spec/validate", json={"spec": spec}, headers=h
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is False
    assert [i["code"] for i in body["issues"] if i["severity"] == "error"] == [
        "DESIGN_SYSTEM_NOT_APPROVED"
    ]
    resp = await client.post(f"/api/v1/projects/{pid}/generate", json={"spec": spec}, headers=h)
    assert resp.status_code == 422, resp.text
