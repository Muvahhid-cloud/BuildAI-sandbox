"""Load BuildingRulesProfiles from `data/rules-profiles/<id>.v<version>.yaml`.

`extends: "<id>@<version>"` is resolved by deep-merging the child over its parent before
validation, so regional profiles only list the values they override.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.modules.rules.profile import BuildingRulesProfile

PROFILES_DIR = Path("rules-profiles")
REF_PATTERN = re.compile(r"^(?P<id>[a-z][a-z0-9-]*)@(?P<version>[1-9][0-9]*)$")


class RulesProfileNotFoundError(LookupError):
    pass


def parse_ref(ref: str) -> tuple[str, int]:
    match = REF_PATTERN.match(ref)
    if match is None:
        raise RulesProfileNotFoundError(f"Invalid rules profile reference {ref!r} (id@version)")
    return match["id"], int(match["version"])


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _raw(data_dir: Path, ref: str, seen: frozenset[str]) -> dict[str, Any]:
    if ref in seen:
        raise RulesProfileNotFoundError(f"Circular 'extends' chain at {ref}")
    profile_id, version = parse_ref(ref)
    path = data_dir / PROFILES_DIR / f"{profile_id}.v{version}.yaml"
    if not path.is_file():
        raise RulesProfileNotFoundError(f"Rules profile {ref} not found")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise RulesProfileNotFoundError(f"Rules profile {ref} is not a mapping")
    parent = doc.get("extends")
    if parent:
        return _deep_merge(_raw(data_dir, str(parent), seen | {ref}), doc)
    return doc


@lru_cache
def load_rules_profile(data_dir: Path, ref: str) -> BuildingRulesProfile:
    profile = BuildingRulesProfile.model_validate(_raw(data_dir, ref, frozenset()))
    if profile.ref != ref:
        raise RulesProfileNotFoundError(f"File for {ref} declares {profile.ref}")
    return profile
