"""Bundled team templates: ready-made `agents.json` content.

A template is data, not code: the same shape `agents.json` has, so nothing has to
translate it. `init --template <name>` will consume it; today it is only listed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import AgentorchError

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tabs"), list):
        return None
    return data


def available() -> list[dict]:
    """Every bundled template, summarised. Broken files are skipped, not guessed."""
    found = []
    if not TEMPLATES_DIR.is_dir():
        return found
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        data = _load_file(path)
        if data is None:
            continue
        found.append({
            "name": data.get("name") or path.stem,
            "description": data.get("description", ""),
            "tabs": len(data["tabs"]),
            "path": str(path),
        })
    return found


def load(name: str) -> dict:
    """The full template, ready to be written as agents.json."""
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.is_file():
        raise AgentorchError(f"There is no template {name!r}. "
                             f"Available: {[t['name'] for t in available()]}")
    data = _load_file(path)
    if data is None:
        raise AgentorchError(f"Template {name!r} is not an object with 'tabs': {path}")
    tabs = [tab for tab in data["tabs"] if isinstance(tab, dict)]
    if not tabs:
        raise AgentorchError(f"Template {name!r} has no usable tabs.")
    data["tabs"] = tabs
    return data
