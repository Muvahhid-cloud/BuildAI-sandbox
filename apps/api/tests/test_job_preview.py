"""Spec-form generation exposes the laid-out model before it is saved (same pipeline as AI
generation: docs/ai-pipeline.md §6.1)."""

import json
from typing import Any

from app.modules.jobs.runner import job_runner
from app.modules.versions.service import VersionService
from tests.building.helpers import SPECS_DIR
from tests.test_versions_generation_api import _auth, _project


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


async def test_job_preview_is_identical_to_the_saved_model(client: Any, monkeypatch: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    spec = json.loads(sorted(SPECS_DIR.glob("*.json"))[0].read_text(encoding="utf-8"))
    url: list[str] = []
    seen: list[Any] = []
    original = VersionService.create

    async def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        job = (await client.get(url[0], headers=h)).json()
        preview = await client.get(url[0] + "/preview", headers=h)
        seen.append((job, preview.status_code, preview.json()))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(VersionService, "create", create)
    resp = await client.post(
        f"/api/v1/projects/{pid}/generate", json={"spec": spec, "seed": 0}, headers=h
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["preview_model_hash"] is None
    url.append(f"/api/v1/jobs/{resp.json()['id']}")
    assert (await client.get(url[0] + "/preview", headers=h)).status_code == 404
    await job_runner.drain()

    job, code, preview = seen[0]
    assert job["status"] == "running" and job["stage"] == "saving"
    assert code == 200 and job["preview_model_hash"] == preview["model_hash"]
    done = (await client.get(url[0], headers=h)).json()
    assert done["status"] == "succeeded" and done["preview_model_hash"] is None
    version = (
        await client.get(
            f"/api/v1/projects/{pid}/versions/{done['result']['version_id']}", headers=h
        )
    ).json()
    assert preview["model_hash"] == version["model_hash"]
    assert _canonical(preview["model"]) == _canonical(version["model"])
    assert (await client.get(url[0] + "/preview", headers=h)).status_code == 404
