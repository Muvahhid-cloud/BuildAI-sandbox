"""Live creation (docs/ai-pipeline.md §6.1): the AI's answer is streamed in the same single
call, simple facts are read from the partial JSON, and the laid-out model is exposed as soon as
the layout stage is done — identical to the model that is then saved."""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_sessionmaker
from app.modules.ai import orchestrator
from app.modules.ai.interim import (
    InterimFact,
    interim_facts,
    merge_facts,
    parse_partial_json,
    spec_facts_for_display,
)
from app.modules.ai.interpreter import interpret
from app.modules.ai.models import AIGeneration
from app.modules.ai.prompts.generation import build_generation_request
from app.modules.ai.providers import use_ai_provider
from app.modules.ai.providers.mock import MOCK_STREAM_CHUNK_CHARS, MockAIProvider
from app.modules.jobs.runner import job_runner
from app.modules.versions.service import VersionService
from tests.ai.helpers import DEMO_PROMPT, ScriptedAIProvider, context, valid_draft, validate_spec
from tests.ai.test_generation_api import URL, _auth, _generate, _project, _runs


def _request() -> Any:
    return build_generation_request(DEMO_PROMPT, options=None, context=context(), max_tokens=4000)


def _facts(text: str) -> dict[str, Any]:
    return {f.key: f.value for f in interim_facts(text)}


# --- streaming ------------------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


async def test_mock_stream_is_the_same_answer_in_deterministic_chunks() -> None:
    provider = MockAIProvider()
    whole = await provider.complete_structured(_request())
    runs = []
    for _ in range(2):
        chunks: list[str] = []

        async def on_text(text: str, into: list[str] = chunks) -> None:
            into.append(text)

        result = await provider.stream_structured(_request(), on_text)
        assert result == whole  # one call, the same result as without streaming
        runs.append(chunks)
    assert runs[0] == runs[1]
    assert "".join(runs[0]) == whole.raw_output
    assert len(runs[0]) > 5
    assert all(len(c) == MOCK_STREAM_CHUNK_CHARS for c in runs[0][:-1])


async def test_provider_without_streaming_delivers_the_answer_in_one_piece() -> None:
    provider = ScriptedAIProvider(valid_draft())
    chunks: list[str] = []

    async def on_text(text: str) -> None:
        chunks.append(text)

    result = await provider.stream_structured(_request(), on_text)
    assert chunks == [result.raw_output]
    assert len(provider.requests) == 1  # still a single call


async def test_interpretation_streams_only_the_first_call_and_validates_the_whole_answer() -> None:
    bad = valid_draft()
    bad["specification"]["targets"]["storeys"] = 9  # streamed, seen, and still rejected
    provider = ScriptedAIProvider(bad, valid_draft())
    seen: list[str] = []

    async def on_text(text: str) -> None:
        seen.append(text)

    result = await interpret(
        DEMO_PROMPT,
        provider=provider,
        options=None,
        context=context(),
        validate_spec=validate_spec,
        on_text=on_text,
    )
    assert len(seen) == 1 and '"storeys": 9' in seen[0]
    assert result.repair_count == 1
    assert result.spec is not None and result.spec.targets.storeys == 2


# --- partial JSON ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", {}),
        ("not json", {}),
        ("{", {}),
        ('{"a": 1', {}),  # the number may still grow
        ('{"a": 1,', {"a": 1}),
        ('{"a": 1}', {"a": 1}),
        ('{"a": "two-st', {}),  # open string
        ('{"a": "two", "b": tr', {"a": "two"}),
        ('{"a": {"b": 2, "c": 28', {"a": {"b": 2}}),
        ('{"a": [1, 2, 3', {"a": [1, 2]}),
        ('{"a": [{"t": "x"}, {"t": "y"', {"a": [{"t": "x"}]}),  # an open element is no element
        ('{"a": [{"t": "x"}, {"t": "y"}], "b"', {"a": [{"t": "x"}, {"t": "y"}]}),
        ('{"a": "q\\"uote", "n": -1.5e2 }', {"a": 'q"uote', "n": -150.0}),
        ('{"a": 1 "b": 2}', {"a": 1}),  # malformed: stop, keep what was complete
    ],
)
def test_partial_json_keeps_only_complete_values(text: str, expected: dict[str, Any]) -> None:
    assert parse_partial_json(text) == expected


def test_every_prefix_of_an_answer_parses_and_facts_only_grow_towards_the_final_ones() -> None:
    draft = valid_draft()
    text = json.dumps(draft)  # the model's key order: targets before rooms, …
    final = _facts(text)
    assert final["storeys"] == 2 and final["floor_area_m2"] == 280.0
    assert final["room:bedroom"] == 4 and final["garage_cars"] == 2 and final["balconies"] == 1
    assert final["style"] == "modern"
    seen: dict[str, Any] = {}
    for end in range(0, len(text) + 1, 7):
        facts = _facts(text[:end])
        for key, value in facts.items():
            # A fact is never a cut-off value: scalars are final at once, counts only grow.
            if isinstance(final[key], bool | str | float) or key in ("storeys", "garage_cars"):
                assert value == final[key], (key, value, end)
            else:
                assert value <= final[key]
                assert value >= seen.get(key, 0)
        seen.update(facts)
    assert seen == final


def test_facts_before_the_specification_and_from_untrusted_values() -> None:
    assert interim_facts('{"outcome": "specification", "understanding": "A house') == []
    spec = {
        "targets": {"storeys": 40, "gross_floor_area_m2": "big"},
        "style": {"architectural_style": "<script>", "roof": {"type": "flat"}},
        "rooms": [{"type": "bedroom", "count": 2}, {"type": 7}, "x", {"type": "bedroom"}],
        "features": {"garage": {"cars": True}, "balconies": [], "terrace": None},
        "design": ["not", "an", "object"],
    }
    facts = {f.key: f.value for f in spec_facts_for_display(spec)}
    assert facts == {"roof": "flat", "room:bedroom": 3}


def test_merged_facts_keep_their_first_position() -> None:
    def fact(key: str, value: int) -> InterimFact:
        return InterimFact(key=key, value=value)

    known = [fact("storeys", 2), fact("room:bedroom", 1)]
    current = [fact("room:bedroom", 3), fact("floor_area_m2", 280), fact("storeys", 2)]
    merged = merge_facts(known, current)
    assert [(f.key, f.value) for f in merged] == [
        ("storeys", 2),
        ("room:bedroom", 3),
        ("floor_area_m2", 280),
    ]


# --- generation: facts, preview, failure ----------------------------------------------------


class _SlowlyStreamed(MockAIProvider):
    """Mock whose stream is observed: records the generation's facts after every piece."""

    def __init__(self, generation_id: list[str]) -> None:
        super().__init__()
        self.generation_id = generation_id
        self.snapshots: list[list[dict[str, Any]]] = []

    async def stream_structured(self, request: Any, on_text: Any) -> Any:
        async def observed(text: str) -> None:
            await on_text(text)
            async with get_sessionmaker()() as session:
                row = await session.scalar(
                    select(AIGeneration.interim_facts).where(
                        AIGeneration.id == uuid.UUID(self.generation_id[0])
                    )
                )
            self.snapshots.append(list(row or []))

        return await super().stream_structured(request, observed)


async def test_facts_are_recorded_while_the_answer_streams(client: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(orchestrator, "INTERIM_FACTS_INTERVAL_S", 0.0)
    h = await _auth(client)
    pid = await _project(client, h)
    gid: list[str] = []
    provider = _SlowlyStreamed(gid)
    with use_ai_provider(provider):
        resp = await client.post(URL, json={"project_id": pid, "prompt": DEMO_PROMPT}, headers=h)
        assert resp.status_code == 202, resp.text
        assert resp.json()["interim_facts"] == []
        gid.append(resp.json()["id"])
        await job_runner.drain()
    counts = [len(s) for s in provider.snapshots]
    assert counts[0] == 0 and counts[-1] > 3
    assert counts == sorted(counts)  # they appear one after the other, in a stable order
    for before, after in zip(provider.snapshots, provider.snapshots[1:], strict=False):
        assert [f["key"] for f in after][: len(before)] == [f["key"] for f in before]
    done = (await client.get(f"/api/v1/ai/generations/{gid[0]}", headers=h)).json()
    assert done["status"] == "completed"
    # After validation the facts are those of the accepted specification.
    facts = {f["key"]: f["value"] for f in done["interim_facts"]}
    spec = done["specification"]
    assert facts["storeys"] == spec["targets"]["storeys"] == 2
    assert facts["floor_area_m2"] == spec["targets"]["gross_floor_area_m2"]
    assert facts["room:bedroom"] == 4
    assert len(await _runs(gid[0])) == 1  # streaming added no AI call


async def test_facts_are_throttled(client: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(orchestrator, "INTERIM_FACTS_INTERVAL_S", 3600.0)
    h = await _auth(client)
    pid = await _project(client, h)
    gid: list[str] = []
    provider = _SlowlyStreamed(gid)
    with use_ai_provider(provider):
        resp = await client.post(URL, json={"project_id": pid, "prompt": DEMO_PROMPT}, headers=h)
        gid.append(resp.json()["id"])
        await job_runner.drain()
    # One read when the stream starts (nothing to see yet), none again within the interval.
    assert all(s == [] for s in provider.snapshots)
    done = (await client.get(f"/api/v1/ai/generations/{gid[0]}", headers=h)).json()
    assert len(done["interim_facts"]) > 3  # the complete answer is still read at the end


def _spy_on_saving(monkeypatch: Any, client: Any, h: dict[str, str], url: list[str]) -> list[Any]:
    """Reads the status and the preview through the API at the moment the version is saved."""
    seen: list[Any] = []
    original = VersionService.create

    async def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        status = (await client.get(url[0], headers=h)).json()
        preview = await client.get(url[0] + "/preview", headers=h)
        seen.append((status, preview.status_code, preview.json()))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(VersionService, "create", create)
    return seen


async def test_preview_model_is_identical_to_the_saved_model(client: Any, monkeypatch: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    url: list[str] = []
    seen = _spy_on_saving(monkeypatch, client, h, url)
    resp = await client.post(URL, json={"project_id": pid, "prompt": DEMO_PROMPT}, headers=h)
    url.append(f"/api/v1/ai/generations/{resp.json()['id']}")
    assert resp.json()["preview_model_hash"] is None
    assert (await client.get(url[0] + "/preview", headers=h)).status_code == 404  # no layout yet
    await job_runner.drain()

    (status, code, preview) = seen[0]
    assert status["status"] == "running" and status["stage"] == "saving"
    assert status["version_id"] is None  # not saved yet, and the house is already available
    assert code == 200 and status["preview_model_hash"] == preview["model_hash"]

    done = (await client.get(url[0], headers=h)).json()
    assert done["status"] == "completed"
    version = (
        await client.get(f"/api/v1/projects/{pid}/versions/{done['version_id']}", headers=h)
    ).json()
    assert preview["model_hash"] == version["model_hash"]
    assert _canonical(preview["model"]) == _canonical(version["model"])
    # The preview only bridges the time until the version exists.
    assert done["preview_model_hash"] is None
    assert (await client.get(url[0] + "/preview", headers=h)).status_code == 404


async def test_preview_is_private(client: Any, monkeypatch: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    url: list[str] = []
    codes: list[int] = []
    original = VersionService.create

    async def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        other = await _auth(client, "eve@example.com")
        codes.append((await client.get(url[0] + "/preview", headers=other)).status_code)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(VersionService, "create", create)
    resp = await client.post(URL, json={"project_id": pid, "prompt": DEMO_PROMPT}, headers=h)
    url.append(f"/api/v1/ai/generations/{resp.json()['id']}")
    await job_runner.drain()
    assert codes == [404]


async def test_failure_after_the_layout_keeps_the_real_error(client: Any, monkeypatch: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    url: list[str] = []
    seen: list[Any] = []

    async def create(self: Any, *args: Any, **kwargs: Any) -> Any:
        status = (await client.get(url[0], headers=h)).json()
        seen.append((status, (await client.get(url[0] + "/preview", headers=h)).status_code))
        raise SQLAlchemyError("disk full")

    monkeypatch.setattr(VersionService, "create", create)
    resp = await client.post(URL, json={"project_id": pid, "prompt": DEMO_PROMPT}, headers=h)
    url.append(f"/api/v1/ai/generations/{resp.json()['id']}")
    await job_runner.drain()

    status, code = seen[0]
    assert code == 200 and status["preview_model_hash"]  # the client was already building it
    done = (await client.get(url[0], headers=h)).json()
    assert done["status"] == "failed" and done["stage"] == "saving"
    assert done["error"]["code"] == "DATABASE_ERROR"
    assert done["version_id"] is None and done["preview_model_hash"] is None
    assert (await client.get(url[0] + "/preview", headers=h)).status_code == 404
    versions = (await client.get(f"/api/v1/projects/{pid}/versions", headers=h)).json()
    assert versions["items"] == []


async def test_clarification_has_no_preview(client: Any) -> None:
    h = await _auth(client)
    pid = await _project(client, h)
    gen = await _generate(client, h, {"project_id": pid, "prompt": "something nice please"})
    assert gen["status"] == "needs_clarification"
    assert gen["preview_model_hash"] is None and gen["interim_facts"] == []
