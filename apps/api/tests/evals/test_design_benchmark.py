"""Design Intelligence benchmark (data/fixtures/benchmark/design-benchmark.v1.json).

Hard expectations must hold for every case; known gaps must still fail (so a fix is noticed
and the gap is removed from the file, not silently kept); soft expectations are a quality
score with a floor that only guards against regressions. Never lower an expectation to make
this pass: fix the engine or record a known gap with its reason.
"""

from functools import cache

import pytest

from evals.design_benchmark import CaseResult, load_cases, run_case, summarize

CASES = load_cases()
# Regression floors for soft expectations, per benchmark generation (the case's "set"; never
# lowered to pass): v1 cases: 12 of 17 met at layout@1.4.0 (unchanged since); v1.1 (L-shaped
# topology): 1 of 4 at 1.5.0, 3 of 4 at 1.6.0, 4 of 4 at 1.7.0; v1.2 (L layout quality): 8 of
# 10 at 1.6.0 and 1.7.0; v1.3 (footprint shape intent, T footprints): 2 of 2 at 1.7.0.
V11_CASES = {
    "rect-compact-retained",
    "l-explicit",
    "l-garden-living-dining",
    "l-kitchen-dining",
    "l-explicit-areas",
    "l-infeasible-plot",
}
SOFT_PASS_FLOOR = {"v1": 0.7, "v1.1": 1.0, "v1.2": 0.8, "v1.3": 1.0}


@cache
def result(case_id: str, use_patterns: bool = True) -> CaseResult:
    case = next(c for c in CASES if c["id"] == case_id)
    return run_case(case, use_patterns=use_patterns)


def test_benchmark_has_at_least_ten_distinct_cases() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) >= 10 and len(set(ids)) == len(ids)
    assert set(ids) >= V11_CASES
    assert len({c["prompt"] for c in CASES}) == len(CASES)
    for case in CASES:
        priorities = {e["priority"] for e in case["expectations"]}
        assert "hard" in priorities, case["id"]


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES])
def test_hard_expectations_hold(case_id: str) -> None:
    res = result(case_id)
    failed = [
        f"{o.kind}: {o.measured}"
        for o in res.outcomes
        if o.priority == "hard" and not o.known_gap and not o.passed
    ]
    assert not failed, f"{case_id} [{res.status}] {res.message}: {failed}"


def test_known_gaps_are_still_gaps() -> None:
    gaps = [(c["id"], o) for c in CASES for o in result(c["id"]).outcomes if o.known_gap]
    assert gaps, "no known gaps recorded"
    still_open = [cid for cid, o in gaps if not o.passed]
    assert len(still_open) == len(gaps), "a known gap now passes: remove its known_gap entry"


def test_cases_are_tagged_with_their_benchmark_generation() -> None:
    sets = {c["id"]: c.get("set", "v1") for c in CASES}
    assert {i for i, s in sets.items() if s == "v1.1"} == V11_CASES
    assert set(sets.values()) == set(SOFT_PASS_FLOOR)


@pytest.mark.parametrize("generation", sorted(SOFT_PASS_FLOOR))
def test_soft_expectations_do_not_regress(generation: str) -> None:
    ids = [c["id"] for c in CASES if c.get("set", "v1") == generation]
    summary = summarize([result(i) for i in ids])
    assert summary["soft"]["rate"] >= SOFT_PASS_FLOOR[generation], summary["soft"]


def test_the_conflicting_request_fails_with_reasons_instead_of_relaxing() -> None:
    res = result("conflicting-constraints")
    assert res.status in ("failed", "spec_invalid")
    assert "REQUIREMENTS_UNMET" in res.message or res.status == "spec_invalid"


def test_layout_patterns_are_what_the_knowledge_expectations_measure() -> None:
    """Without the pattern library the knowledge expectations fail and the open-plan case is
    laid out differently (measured connections change): the patterns are consumed, not just
    stored. (Until V1.2 this also asserted a lost dining-living connection without patterns;
    that 0.00 m was float noise between room outlines, gone once the benchmark measures on the
    model's 1 mm grid: the connection is 2.80 m.)"""
    with_patterns = result("open-plan-living")
    without = result("open-plan-living", use_patterns=False)
    kinds = {o.kind: o.passed for o in without.outcomes if o.kind == "pattern_applied"}
    assert kinds == {"pattern_applied": False}
    assert with_patterns.patterns == ["pattern.open_plan_living"]
    assert all(o.passed for o in with_patterns.outcomes if o.priority == "hard")
    measured = [o.measured for o in with_patterns.outcomes if o.kind == "open_connection"]
    assert measured != [o.measured for o in without.outcomes if o.kind == "open_connection"]


def test_l_shaped_requests_produce_validated_l_geometry() -> None:
    """A successful L is only reported when the model's own geometry is an L."""
    for case_id in ("l-explicit", "l-garden-living-dining", "l-kitchen-dining", "l-explicit-areas"):
        res = result(case_id)
        shape = next(o for o in res.outcomes if o.kind == "footprint_shape")
        assert res.status == "model" and shape.passed, (case_id, shape.measured)
    rect = next(o for o in result("rect-compact-retained").outcomes if o.kind == "footprint_shape")
    assert rect.passed, rect.measured
