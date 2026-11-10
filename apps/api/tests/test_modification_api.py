"""AI-assisted modification API (Phase 5): plan -> answer -> apply as a new version -> restore,
and version comparison. Runs with the offline MockAIProvider."""

from typing import Any

from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.providers import use_ai_provider
from tests.ai.helpers import ScriptedAIProvider
from tests.conftest import bearer, register


async def _demo(client: Any, email: str = "ada@example.com") -> tuple[dict[str, str], str, Any]:
    client.cookies.clear()
    h = bearer((await register(client, email=email))["access_token"])
    pid = (await client.post("/api/v1/projects", json={"name": "House"}, headers=h)).json()["id"]
    resp = await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=h)
    assert resp.status_code == 201, resp.text
    return h, pid, resp.json()


def _url(pid: str, vid: str, what: str) -> str:
    return f"/api/v1/projects/{pid}/versions/{vid}/modify/{what}"


async def test_plan_answer_apply_and_restore(client: Any) -> None:
    h, pid, v1 = await _demo(client)
    prompt = "Rename bedroom 3 to Guest bedroom and make the kitchen 2 metres wider"
    resp = await client.post(_url(pid, v1["id"], "plan"), json={"prompt": prompt}, headers=h)
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["status"] == "needs_clarification"
    assert [c["status"] for c in plan["changes"]] == ["planned", "needs_clarification"]
    question = plan["questions"][0]
    assert question["id"] == "1.target" and "facade" in question["text"]
    assert plan["provider"] == "mock" and plan["prompt_version"] == "building-modification@1"
    # The rename alone is already previewed (nothing stored).
    assert plan["preview"]["valid"] is True
    assert any("Guest bedroom" in line["text"] for line in plan["diff"]["lines"])

    yes = next(o["value"] for o in question["options"] if o["value"] != "skip")
    resp = await client.post(
        _url(pid, v1["id"], "resolve"),
        json={
            "prompt": prompt,
            "draft": plan["draft"],
            "answers": [{"question_id": question["id"], "value": yes}],
        },
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    ready = resp.json()
    assert ready["status"] == "ready" and ready["questions"] == []
    assert [op["op"] for op in ready["operations"]] == ["rename_room", "resize_room"]
    assert ready["preview"]["valid"] is True
    kitchen_line = next(x for x in ready["diff"]["lines"] if x["text"].startswith("Kitchen:"))
    assert "27.6 m² → 39.6 m²" in kitchen_line["text"]

    # Apply = a normal edit save, recorded as an AI modification.
    resp = await client.post(
        f"/api/v1/projects/{pid}/versions/{v1['id']}/edits",
        json={"operations": ready["operations"], "origin": "ai_modification", "prompt": prompt},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["source"] == "ai_modification" and v2["prompt"] == prompt
    assert v2["parent_version_id"] == v1["id"] and v2["label"] == "AI changes on v1"
    assert v2["model"] == ready["preview"]["model"]

    # Compare v1 -> v2: measured lines.
    resp = await client.get(
        f"/api/v1/projects/{pid}/compare", params={"a": v1["id"], "b": v2["id"]}, headers=h
    )
    assert resp.status_code == 200, resp.text
    cmp = resp.json()
    assert (cmp["a_number"], cmp["b_number"]) == (1, 2)
    texts = [x["text"] for x in cmp["diff"]["lines"]]
    assert "Bedroom 3 renamed to Guest bedroom" in texts and kitchen_line["text"] in texts
    assert cmp["diff"]["changed"]

    # Undo to the original: a NEW version with v1's model; v1 and v2 stay as they are.
    resp = await client.post(f"/api/v1/projects/{pid}/versions/{v1['id']}/restore", headers=h)
    assert resp.status_code == 201, resp.text
    v3 = resp.json()
    assert v3["number"] == 3 and v3["source"] == "restore" and v3["label"] == "Restored v1"
    assert v3["parent_version_id"] == v2["id"]
    assert v3["model"]["elements"] == v1["model"]["elements"]
    again = (await client.get(f"/api/v1/projects/{pid}/versions/{v2['id']}", headers=h)).json()
    assert again["model"] == v2["model"]
    project = (await client.get(f"/api/v1/projects/{pid}", headers=h)).json()
    assert project["current_version_id"] == v3["id"]


async def test_plan_builds_on_the_unsaved_session_operations(client: Any) -> None:
    h, pid, v1 = await _demo(client)
    kitchen = next(e for e in v1["model"]["elements"] if e["semantic_key"] == "room:kitchen")
    session = [{"op": "rename_room", "room_id": kitchen["id"], "name": "Chef's kitchen"}]
    resp = await client.post(
        _url(pid, v1["id"], "plan"),
        json={"prompt": "turn the storage into a laundry", "operations": session},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["status"] == "ready"
    assert [op["op"] for op in plan["operations"]] == ["set_room_type"]  # only the new ones
    names = {e["name"] for e in plan["preview"]["model"]["elements"] if e["type"] == "room"}
    assert "Chef's kitchen" in names  # the preview includes the session's edits


async def test_unsupported_requests_are_reported(client: Any) -> None:
    h, pid, v1 = await _demo(client)
    resp = await client.post(
        _url(pid, v1["id"], "plan"), json={"prompt": "Add a swimming pool"}, headers=h
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["status"] == "nothing_to_apply" and plan["operations"] == []
    assert plan["unsupported"][0]["quote"] == "Add a swimming pool"


async def test_a_tampered_draft_is_refused(client: Any) -> None:
    h, pid, v1 = await _demo(client)
    draft = {
        "understanding": "x",
        "changes": [{"quote": "q", "action": "rename_room", "room": "R999", "new_name": "Y"}],
    }
    resp = await client.post(
        _url(pid, v1["id"], "resolve"),
        json={"prompt": "rename", "draft": draft, "answers": []},
        headers=h,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "AI_MODIFICATION_INVALID"


async def test_provider_failures_are_reported(client: Any) -> None:
    h, pid, v1 = await _demo(client)
    with use_ai_provider(ScriptedAIProvider(AIUnavailableError("down"))):
        resp = await client.post(
            _url(pid, v1["id"], "plan"), json={"prompt": "rename the kitchen to K"}, headers=h
        )
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "AI_UNAVAILABLE"


async def test_modification_needs_ownership(client: Any) -> None:
    _, pid, v1 = await _demo(client)
    other = await _demo(client, email="eve@example.com")
    resp = await client.post(
        _url(pid, v1["id"], "plan"), json={"prompt": "rename the kitchen to K"}, headers=other[0]
    )
    assert resp.status_code == 404
    resp = await client.post(
        f"/api/v1/projects/{pid}/versions/{v1['id']}/restore", headers=other[0]
    )
    assert resp.status_code == 404
