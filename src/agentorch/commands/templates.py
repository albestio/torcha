"""The templates command: list the team shapes agentorch ships with."""

from __future__ import annotations

import json

from ..templates import available
from ..output import log, note


def templates(as_json: bool = False) -> int:
    found = available()
    if not found:
        note("No hay templates disponibles.")
        return 1

    if as_json:
        print(json.dumps({"templates": found}, indent=2, ensure_ascii=False))
        return 0

    width = max(len(item["name"]) for item in found)
    for item in found:
        log(f"  {item['name']:<{width}}  {item['tabs']} rol(es)  {item['description']}")
    return 0
