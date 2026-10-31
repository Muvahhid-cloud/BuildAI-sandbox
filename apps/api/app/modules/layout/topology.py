"""Footprint topology selection (Design Intelligence V1.1/V1.3, docs/3d-engine.md §16.10-16.12).

Which footprint topologies the candidate search explores, and why. What can be generated at all
is building/footprint.py CAPABILITIES ("rect", "l", "t" today); a shape the interpreter
recognises is not therefore a shape the engine can build. A user requirement and a pattern
suggestion are kept apart:

    footprint_shape = rectangular              -> rect only
    a generated shape (l, t), MUST             -> that topology only; none fits ->
                                                  LAYOUT_INFEASIBLE, never a silent rectangle
    a generated shape (l, t), SHOULD           -> it and rect compete; the shape is a SHOULD
                                                  requirement, so a valid one that meets every
                                                  MUST wins over a comparable rectangle
    a shape without a generator (u_shape, courtyard), or beyond its storeys limit:
                                     MUST      -> nothing is searched: LAYOUT_SHAPE_UNSUPPORTED
                                                  with the reason (spec checks refuse it first)
                                     SHOULD    -> rect, reported as a fallback with the reason
    not requested, a pattern suggests an L     -> rect and L compete on the evaluation only
    not requested, no pattern                  -> rect only (the default)

The shape that was generated is measured on the validated model (building/evaluation.py
measure_footprint), never taken from the plan.
"""

from dataclasses import dataclass

from app.modules.building.footprint import CAPABILITIES, capability, unsupported_reason
from app.modules.building.specification import BuildingSpecification, Priority
from app.modules.layout.patterns import PatternGuidance

# Topology id -> words (reports). Every generated topology has an entry.
SHAPE_NAMES = {c.topology: c.label for c in CAPABILITIES.values() if c.topology is not None}
# Topology id -> the measured shape that proves it (measure_footprint).
MEASURED = {c.topology: c.shape.value for c in CAPABILITIES.values() if c.topology is not None}


@dataclass(frozen=True)
class TopologyChoice:
    topologies: tuple[str, ...]  # searched, in seeding order ("rect" first)
    requested: str | None  # FootprintShape value from the spec
    mandatory: bool
    reason: str  # why these topologies were searched (shown in the report)
    target: str | None = None  # topology id the request asks for ("rect" / "l" / "t")
    unsupported: str | None = None  # why the requested shape cannot be generated at all


def choose_topologies(spec: BuildingSpecification, guidance: PatternGuidance) -> TopologyChoice:
    requested = spec.design.footprint_shape
    must = spec.priority_of("/design/footprint_shape") == Priority.MUST
    if requested is not None:
        cap = capability(requested)
        why_not = unsupported_reason(requested, spec.targets.storeys)
        if why_not is not None:
            if must:
                return TopologyChoice(
                    (),
                    requested.value,
                    True,
                    f"{cap.a_label} footprint is required, but {why_not}",
                    cap.topology,
                    why_not,
                )
            return TopologyChoice(
                ("rect",),
                requested.value,
                False,
                f"{cap.a_label} footprint was requested as a preference, but {why_not}; a "
                "rectangular footprint was used",
                cap.topology,
                why_not,
            )
        if cap.topology == "rect":
            return TopologyChoice(
                ("rect",), requested.value, must, "a rectangular footprint was requested", "rect"
            )
        target = cap.topology or "rect"  # (generated shapes always have a topology)
        if must:
            return TopologyChoice(
                (target,),
                requested.value,
                True,
                f"{cap.a_label} footprint is required",
                target,
            )
        return TopologyChoice(
            ("rect", target),
            requested.value,
            False,
            f"{cap.a_label} footprint was requested as a preference; rectangular layouts were "
            "kept as alternatives",
            target,
        )
    if "l" in guidance.topologies and spec.targets.storeys == 1:
        return TopologyChoice(
            ("rect", "l"),
            None,
            False,
            "the experimental pattern(s) "
            + ", ".join(guidance.topology_sources)
            + " suggested also trying an L-shaped footprint; both competed on the evaluation",
        )
    return TopologyChoice(("rect",), None, False, "rectangular footprint (the default)")
