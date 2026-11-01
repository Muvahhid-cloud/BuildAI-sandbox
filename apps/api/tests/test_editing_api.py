"""Plan editing API: preview and save typed operations on a version (Phase 3.6 D2)."""

from typing import Any

import pytest

from tests.conftest import bearer, register


async def _demo_version(
    client: Any, email: str = "ada@example.com"
) -> tuple[dict[str, str], str, dict[str, Any]]:
    client.cookies.clear()
    h = bearer((await register(client, email=email))["access_token"])
    pid = (await client.post("/api/v1/projects", json={"name": "House"}, headers=h)).json()["id"]
    resp = await client.post(f"/api/v1/projects/{pid}/versions/demo", headers=h)
    assert resp.status_code == 201, resp.text
    return h, pid, resp.json()


def _wall(version: dict[str, Any], key: str) -> dict[str, Any]:
    wall: dict[str, Any] = next(e for e in version["model"]["elements"] if e["semantic_key"] == key)
    return wall


def _move(wall: dict[str, Any], offset: float) -> dict[str, Any]:
    return {"op": "move_wall", "wall_id": wall["id"], "offset_m": offset}


async def test_preview_returns_the_edited_model_without_saving(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    wall = _wall(v1, "wall:G-I1")
    url = f"/api/v1/projects/{pid}/versions/{v1['id']}/edits/preview"
    resp = await client.post(url, json={"operations": [_move(wall, 0.2)]}, headers=h)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["valid"] is True and out["rejection"] is None
    moved = next(e for e in out["model"]["elements"] if e["id"] == wall["id"])
    assert moved["position"] != wall["position"]
    assert wall["id"] in out["changed_ids"]
    assert out["summary"]["rooms"] == v1["summary"]["rooms"]
    assert out["model"]["metadata"]["source"] == "operations"
    versions = (await client.get(f"/api/v1/projects/{pid}/versions", headers=h)).json()["items"]
    assert len(versions) == 1  # nothing stored


async def test_preview_refuses_invalid_edits_with_reasons(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    url = f"/api/v1/projects/{pid}/versions/{v1['id']}/edits/preview"
    # The south facade pulled in 0.6 m would cut the stair opening (D2.5 facade moves).
    resp = await client.post(
        url, json={"operations": [_move(_wall(v1, "wall:G-S"), 0.6)]}, headers=h
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["valid"] is False and out["model"] is None
    assert out["rejection"]["code"] == "FACADE_CUTS_STAIR" and out["rejection"]["index"] == 0
    resp = await client.post(
        url, json={"operations": [_move(_wall(v1, "wall:G-I6"), 0.5)]}, headers=h
    )
    out = resp.json()
    assert out["valid"] is False and out["rejection"]["code"] == "EDIT_INVALID"
    assert out["rejection"]["issues"] and out["rejection"]["message"].startswith(
        "This change would"
    )


async def test_save_creates_a_new_version_from_the_base(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    wall = _wall(v1, "wall:G-I1")
    ops = [_move(wall, 0.2), _move(wall, -0.1)]
    resp = await client.post(
        f"/api/v1/projects/{pid}/versions/{v1['id']}/edits", json={"operations": ops}, headers=h
    )
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["number"] == 2 and v2["source"] == "manual" and v2["parent_version_id"] == v1["id"]
    assert v2["label"] == "Plan edits on v1 (2 changes)"
    assert v2["model_hash"] != v1["model_hash"]
    moved = next(e for e in v2["model"]["elements"] if e["id"] == wall["id"])
    assert moved["position"] != wall["position"]
    project = (await client.get(f"/api/v1/projects/{pid}", headers=h)).json()
    assert project["current_version_id"] == v2["id"]
    # The base version is untouched (versions are immutable).
    again = (await client.get(f"/api/v1/projects/{pid}/versions/{v1['id']}", headers=h)).json()
    assert again["model_hash"] == v1["model_hash"]


async def test_a_saved_edit_is_what_every_later_load_returns(client: Any) -> None:
    """Regression (2D/3D desync): the model the editor previewed is the one stored, the
    project's latest version, and what a reload loads; the base version stays byte-identical;
    a refused save stores nothing and leaves the latest version alone."""
    h, pid, v1 = await _demo_version(client)
    url = f"/api/v1/projects/{pid}/versions"
    wall = _wall(v1, "wall:G-I1")  # interior, runs east: + = north
    ops = [_move(wall, 0.2)]
    preview = (
        await client.post(f"{url}/{v1['id']}/edits/preview", json={"operations": ops}, headers=h)
    ).json()
    assert preview["valid"] is True, preview["rejection"]
    resp = await client.post(f"{url}/{v1['id']}/edits", json={"operations": ops}, headers=h)
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["model"] == preview["model"]
    moved = next(e for e in v2["model"]["elements"] if e["id"] == wall["id"])
    assert moved["position"]["y"] == pytest.approx(wall["position"]["y"] + 0.2, abs=1e-9)
    assert moved["position"]["x"] == wall["position"]["x"]

    # A reload: the project opens at v2 and v2 loads exactly as saved.
    project = (await client.get(f"/api/v1/projects/{pid}", headers=h)).json()
    assert project["current_version_id"] == v2["id"]
    listed = (await client.get(url, headers=h)).json()["items"]
    assert [v["number"] for v in listed] == [2, 1]
    reloaded = (await client.get(f"{url}/{v2['id']}", headers=h)).json()
    assert reloaded["model"] == v2["model"] and reloaded["model_hash"] == v2["model_hash"]
    base = (await client.get(f"{url}/{v1['id']}", headers=h)).json()
    assert base["model"] == v1["model"] and base["model_hash"] == v1["model_hash"]

    # A refused save on v2 stores nothing.
    bad = [_move(_wall(v2, "wall:G-I6"), 0.5)]
    assert (
        await client.post(f"{url}/{v2['id']}/edits", json={"operations": bad}, headers=h)
    ).status_code == 422
    project = (await client.get(f"/api/v1/projects/{pid}", headers=h)).json()
    assert project["current_version_id"] == v2["id"]
    assert len((await client.get(url, headers=h)).json()["items"]) == 2
    again = (await client.get(f"{url}/{v2['id']}", headers=h)).json()
    assert again["model"] == v2["model"]


async def test_save_refuses_invalid_edits(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    resp = await client.post(
        f"/api/v1/projects/{pid}/versions/{v1['id']}/edits",
        json={"operations": [_move(_wall(v1, "wall:G-I6"), 0.5)]},
        headers=h,
    )
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "EDIT_REJECTED" and err["details"][0]["code"] == "EDIT_INVALID"
    versions = (await client.get(f"/api/v1/projects/{pid}/versions", headers=h)).json()["items"]
    assert len(versions) == 1


async def test_edits_need_operations_and_ownership(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    url = f"/api/v1/projects/{pid}/versions/{v1['id']}/edits/preview"
    assert (await client.post(url, json={"operations": []}, headers=h)).status_code == 422
    bad = {
        "operations": [{"op": "move_wall", "wall_id": _wall(v1, "wall:G-I1")["id"], "offset_m": 99}]
    }
    assert (await client.post(url, json=bad, headers=h)).status_code == 422
    other = bearer((await register(client, email="eve@example.com"))["access_token"])
    body = {"operations": [_move(_wall(v1, "wall:G-I1"), 0.3)]}
    assert (await client.post(url, json=body, headers=other)).status_code == 404
    client.cookies.clear()
    assert (await client.post(url, json=body)).status_code == 401


# --- resize_room (D2.2) ----------------------------------------------------------------------


def _room(version: dict[str, Any], name: str) -> dict[str, Any]:
    room: dict[str, Any] = next(
        e for e in version["model"]["elements"] if e["type"] == "room" and e["name"] == name
    )
    return room


def _room_side_on_wall(version: dict[str, Any], room: dict[str, Any], wall_id: str) -> int:
    """Index of the room side that runs along the wall (axis-aligned demo geometry)."""
    wall = next(e for e in version["model"]["elements"] if e["id"] == wall_id)
    pts = [
        (room["position"]["x"] + p["x"], room["position"]["y"] + p["y"])
        for p in room["properties"]["boundary"]
    ]
    y = wall["position"]["y"]
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        if abs(p[1] - y) < 1e-6 and abs(q[1] - y) < 1e-6:
            return i
    raise AssertionError("no side on the wall")


async def test_resize_room_previews_and_saves_with_the_neighbour_updated(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    entrance = _room(v1, "Entrance")
    corridor = _room(v1, "Corridor")
    wall = _wall(v1, "wall:G-I1")  # between the entrance (south) and the corridor (north)
    edge = _room_side_on_wall(v1, entrance, wall["id"])
    resize = {"op": "resize_room", "room_id": entrance["id"], "edge": edge, "delta_m": 0.2}
    url = f"/api/v1/projects/{pid}/versions/{v1['id']}"
    out = (
        await client.post(f"{url}/edits/preview", json={"operations": [resize]}, headers=h)
    ).json()
    assert out["valid"] is True, out["rejection"]
    rooms = {e["id"]: e for e in out["model"]["elements"] if e["type"] == "room"}
    grown = rooms[entrance["id"]]["dimensions"]["area"] - entrance["dimensions"]["area"]
    shrunk = rooms[corridor["id"]]["dimensions"]["area"] - corridor["dimensions"]["area"]
    assert grown == pytest.approx(0.68, abs=0.011)  # 3.4 m side x 0.2 m
    assert shrunk == pytest.approx(-0.68, abs=0.011)
    # Mixed with a wall move, saved as one version.
    ops = [resize, _move(wall, -0.1)]
    saved = await client.post(f"{url}/edits", json={"operations": ops}, headers=h)
    assert saved.status_code == 201, saved.text
    v2 = saved.json()
    entrance2 = next(e for e in v2["model"]["elements"] if e["id"] == entrance["id"])
    assert entrance2["dimensions"]["area"] == pytest.approx(
        entrance["dimensions"]["area"] + 0.34, abs=0.011
    )


async def test_a_refused_resize_changes_nothing(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    entrance = _room(v1, "Entrance")
    edge = _room_side_on_wall(v1, entrance, _wall(v1, "wall:G-I1")["id"])
    url = f"/api/v1/projects/{pid}/versions/{v1['id']}"
    too_far = {"op": "resize_room", "room_id": entrance["id"], "edge": edge, "delta_m": 0.5}
    out = (
        await client.post(f"{url}/edits/preview", json={"operations": [too_far]}, headers=h)
    ).json()
    assert out["valid"] is False and out["model"] is None
    assert "corridor minimum" in out["rejection"]["message"]
    saved = await client.post(f"{url}/edits", json={"operations": [too_far]}, headers=h)
    assert saved.status_code == 422
    again = (await client.get(url, headers=h)).json()
    assert again["model_hash"] == v1["model_hash"]
    bad = {"op": "resize_room", "room_id": entrance["id"], "edge": -1, "delta_m": 0.2}
    assert (
        await client.post(f"{url}/edits/preview", json={"operations": [bad]}, headers=h)
    ).status_code == 422


def _opening(version: dict[str, Any], key: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        e for e in version["model"]["elements"] if e["semantic_key"] == key
    )
    return found


async def test_door_and_window_edits_save_and_reload_as_one_version(client: Any) -> None:
    """D2.3: move a door, add a window, remove a window; saved as one version on its parent,
    reloaded exactly; the base is untouched; a refused opening edit stores nothing."""
    h, pid, v1 = await _demo_version(client)
    url = f"/api/v1/projects/{pid}/versions"
    door = _opening(v1, "door:ent_corr")
    gone = _opening(v1, "window:ent")
    west = _wall(v1, "wall:G-W")
    ops = [
        {"op": "move_opening", "opening_id": door["id"], "offset_m": 2.0},
        {
            "op": "add_opening",
            "kind": "window",
            "host_wall_id": west["id"],
            "offset_m": 6.0,
            "width_m": 1.2,
            "height_m": 1.4,
            "sill_m": 0.9,
        },
        {"op": "remove_element", "element_id": gone["id"]},
    ]
    preview = (
        await client.post(f"{url}/{v1['id']}/edits/preview", json={"operations": ops}, headers=h)
    ).json()
    assert preview["valid"] is True, preview["rejection"]
    assert len(preview["changed_ids"]) == 3
    resp = await client.post(f"{url}/{v1['id']}/edits", json={"operations": ops}, headers=h)
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["model"] == preview["model"] and v2["parent_version_id"] == v1["id"]
    assert v2["label"] == "Plan edits on v1 (3 changes)"
    assert v2["summary"]["windows"] == v1["summary"]["windows"]  # one added, one removed
    moved = _opening(v2, "door:ent_corr")
    assert moved["position"]["x"] == 2.0 and moved["id"] == door["id"]
    added = _opening(v2, "window:edit:1")
    assert added["relationships"][0] == {"kind": "hosted_by", "target_id": west["id"]}
    assert all(e["id"] != gone["id"] for e in v2["model"]["elements"])

    reloaded = (await client.get(f"{url}/{v2['id']}", headers=h)).json()
    assert reloaded["model"] == v2["model"]
    base = (await client.get(f"{url}/{v1['id']}", headers=h)).json()
    assert base["model"] == v1["model"] and base["model_hash"] == v1["model_hash"]

    # Refused: removing the storage room's only door cuts it off.
    storage_door = _opening(v2, "door:storage")
    bad = [{"op": "remove_element", "element_id": storage_door["id"]}]
    out = (
        await client.post(f"{url}/{v2['id']}/edits/preview", json={"operations": bad}, headers=h)
    ).json()
    assert out["valid"] is False and "Storage cannot be reached" in out["rejection"]["message"]
    resp = await client.post(f"{url}/{v2['id']}/edits", json={"operations": bad}, headers=h)
    assert resp.status_code == 422
    assert len((await client.get(url, headers=h)).json()["items"]) == 2
    project = (await client.get(f"/api/v1/projects/{pid}", headers=h)).json()
    assert project["current_version_id"] == v2["id"]


async def test_opening_operations_are_validated_as_input(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    url = f"/api/v1/projects/{pid}/versions/{v1['id']}/edits/preview"
    wall = _wall(v1, "wall:G-I2")
    for bad in (
        {
            "op": "add_opening",
            "kind": "skylight",
            "host_wall_id": wall["id"],
            "offset_m": 1,
            "width_m": 1,
            "height_m": 1,
        },
        {
            "op": "add_opening",
            "kind": "door",
            "host_wall_id": wall["id"],
            "offset_m": -1,
            "width_m": 1,
            "height_m": 2,
        },
        {"op": "move_opening", "opening_id": "not-a-uuid", "offset_m": 1},
    ):
        resp = await client.post(url, json={"operations": [bad]}, headers=h)
        assert resp.status_code == 422, bad


async def test_d24_resize_wall_removal_and_room_edits_save_and_reload(client: Any) -> None:
    """D2.4: resize a window and a door, merge two rooms across a removed wall, rename a room and
    change its type; one new version on its parent, reloaded exactly; the base is untouched."""
    h, pid, v1 = await _demo_version(client)
    url = f"/api/v1/projects/{pid}/versions"
    window = _opening(v1, "window:bed3_s")
    door = _opening(v1, "door:bedroom3")
    wall = _wall(v1, "wall:F-I7")  # master bedroom | study
    bedroom = _opening(v1, "room:bedroom3")
    study = _opening(v1, "room:study")
    ops = [
        {"op": "resize_opening", "opening_id": window["id"], "width_m": 1.8, "height_m": 1.5},
        {"op": "resize_opening", "opening_id": door["id"], "width_m": 1.0, "height_m": 2.2},
        {"op": "remove_wall", "wall_id": wall["id"], "merge_rooms": True},
        {"op": "rename_room", "room_id": bedroom["id"], "name": "Guest bedroom"},
        {"op": "set_room_type", "room_id": bedroom["id"], "room_type": "study"},
    ]
    preview = (
        await client.post(f"{url}/{v1['id']}/edits/preview", json={"operations": ops}, headers=h)
    ).json()
    assert preview["valid"] is True, preview["rejection"]
    resp = await client.post(f"{url}/{v1['id']}/edits", json={"operations": ops}, headers=h)
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["model"] == preview["model"] and v2["parent_version_id"] == v1["id"]
    w = _opening(v2, "window:bed3_s")
    assert (w["dimensions"]["width"], w["dimensions"]["height"]) == (1.8, 1.5)
    assert w["id"] == window["id"]
    d = _opening(v2, "door:bedroom3")
    assert (d["dimensions"]["width"], d["dimensions"]["height"]) == (1.0, 2.2)
    room = _opening(v2, "room:bedroom3")
    assert room["name"] == "Guest bedroom" and room["properties"]["room_type"] == "study"
    assert all(e["id"] not in (wall["id"], study["id"]) for e in v2["model"]["elements"])
    assert v2["summary"]["rooms"] == v1["summary"]["rooms"] - 1

    reloaded = (await client.get(f"{url}/{v2['id']}", headers=h)).json()
    assert reloaded["model"] == v2["model"]
    base = (await client.get(f"{url}/{v1['id']}", headers=h)).json()
    assert base["model"] == v1["model"] and base["model_hash"] == v1["model_hash"]

    # Refused edits store nothing and explain why.
    bad = [{"op": "remove_wall", "wall_id": _wall(v2, "wall:G-S")["id"]}]
    out = (
        await client.post(f"{url}/{v2['id']}/edits/preview", json={"operations": bad}, headers=h)
    ).json()
    assert out["valid"] is False and out["rejection"]["code"] == "EXTERIOR_WALL_FIXED"
    resp = await client.post(f"{url}/{v2['id']}/edits", json={"operations": bad}, headers=h)
    assert resp.status_code == 422
    assert len((await client.get(url, headers=h)).json()["items"]) == 2


async def test_an_added_wall_saves_and_reloads_with_its_new_room(client: Any) -> None:
    h, pid, v1 = await _demo_version(client)
    url = f"/api/v1/projects/{pid}/versions"
    entrance = _opening(v1, "room:entrance")
    op = {
        "op": "add_wall",
        "room_id": entrance["id"],
        "direction": "north_south",
        "x_m": 1.02,
        "y_m": 1.44,
        "new_room_type": "storage",
        "door_width_m": 0.8,
        "door_height_m": 2.1,
    }
    resp = await client.post(f"{url}/{v1['id']}/edits", json={"operations": [op]}, headers=h)
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["parent_version_id"] == v1["id"]
    assert _opening(v2, "room:edit:1")["properties"]["room_type"] == "storage"
    assert _wall(v2, "wall:edit:1")["properties"]["wall_kind"] == "interior"
    assert (await client.get(f"{url}/{v2['id']}", headers=h)).json()["model"] == v2["model"]
    base = (await client.get(f"{url}/{v1['id']}", headers=h)).json()
    assert base["model_hash"] == v1["model_hash"]


async def test_d25_envelope_edits_save_and_reload_as_one_version(client: Any) -> None:
    """D2.5: a facade move, a facade thickness, a finish and a partition height preview, save as
    a new version and reload exactly; the base version is untouched."""
    h, pid, v1 = await _demo_version(client, email="envelope@example.com")
    url = f"/api/v1/projects/{pid}/versions"
    east = _wall(v1, "wall:G-E")  # exterior, runs north: + = west (inwards)
    upper_east = _wall(v1, "wall:F-E")
    interior = _wall(v1, "wall:G-I1")
    ops = [
        _move(east, -0.8),
        {"op": "set_wall_thickness", "wall_id": east["id"], "thickness_m": 0.4},
        {
            "op": "set_wall_finish",
            "wall_id": east["id"],
            "face": "right",
            "material_id": "exterior_wall",
        },
        {"op": "set_wall_thickness", "wall_id": interior["id"], "thickness_m": 0.15},
    ]
    preview = (
        await client.post(f"{url}/{v1['id']}/edits/preview", json={"operations": ops}, headers=h)
    ).json()
    assert preview["valid"] is True, preview["rejection"]
    resp = await client.post(
        f"{url}/{v1['id']}/edits", json={"operations": ops, "label": "Wider east"}, headers=h
    )
    assert resp.status_code == 201, resp.text
    v2 = resp.json()
    assert v2["model"] == preview["model"]
    moved = _wall(v2, "wall:G-E")
    assert moved["position"]["x"] == pytest.approx(east["position"]["x"] + 0.8)
    assert moved["dimensions"]["thickness"] == 0.4
    assert moved["properties"]["finish_right_id"] == "exterior_wall"
    # The storey above moved with it.
    assert _wall(v2, "wall:F-E")["position"]["x"] == pytest.approx(
        upper_east["position"]["x"] + 0.8
    )
    roof = next(e for e in v2["model"]["elements"] if e["type"] == "roof")
    base_roof = next(e for e in v1["model"]["elements"] if e["type"] == "roof")
    assert max(p["x"] for p in roof["properties"]["outline"]) > max(
        p["x"] for p in base_roof["properties"]["outline"]
    )
    reloaded = (await client.get(f"{url}/{v2['id']}", headers=h)).json()
    assert reloaded["model"] == v2["model"]
    base = (await client.get(f"{url}/{v1['id']}", headers=h)).json()
    assert base["model"] == v1["model"]

    # Refusals explain themselves and store nothing.
    for bad, code in (
        ([{"op": "set_wall_thickness", "wall_id": east["id"], "thickness_m": 0.1}], "EDIT_INVALID"),
        ([{"op": "set_wall_height", "wall_id": east["id"], "height_m": 2.0}], "WALL_HEIGHT_FIXED"),
    ):
        out = (
            await client.post(
                f"{url}/{v2['id']}/edits/preview", json={"operations": bad}, headers=h
            )
        ).json()
        assert out["valid"] is False and out["rejection"]["code"] == code
    assert len((await client.get(url, headers=h)).json()["items"]) == 2
