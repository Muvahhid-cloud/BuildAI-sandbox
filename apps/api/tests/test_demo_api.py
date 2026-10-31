import json
from typing import Any

from tests.building.helpers import FIXTURE_PATH


async def test_demo_model_is_public_and_matches_fixture(client: Any) -> None:
    resp = await client.get("/api/v1/demo/building-model")
    assert resp.status_code == 200, resp.text
    assert resp.json() == json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
