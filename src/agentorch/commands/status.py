"""The status command: compare the registry with what Herdr reports."""

from __future__ import annotations

import json

from ..herdr import (get_spaces, parse_json_output, run_app, space_id, tab_id,
                     tab_name, tabs_of, terminal_pid)
from ..output import log, note
from ..registry import load_registry

ALIVE = "alive"
DOWN = "down"
MISSING = "missing"
MOVED = "moved"

# Only these mean the registry no longer describes reality. A role that is down
# is information, not a divergence: not every agent has to be running.
DIVERGENT = {MISSING, MOVED}


def _find_terminal(tab: dict, terminal_id: str | None) -> dict | None:
    for terminal in tab.get("terminals") or []:
        if isinstance(terminal, dict) and terminal.get("terminal") == terminal_id:
            return terminal
    return None


def _role_state(space: dict | None, entry: dict) -> tuple[str, str]:
    if space is None:
        return MISSING, "the space no longer exists"

    tab = next((t for t in tabs_of(space) if tab_id(t) == entry.get("tab_id")), None)
    if tab is None:
        return MISSING, "the tab no longer exists"

    terminal_id = entry.get("terminal_id")
    terminal = _find_terminal(tab, terminal_id)
    if terminal is None:
        return MISSING, "the terminal no longer exists"

    if not terminal.get("app"):
        return DOWN, "no agent (shell)"

    live = terminal_pid(terminal_id)
    recorded = entry.get("pid")
    if recorded and live and recorded != live:
        return MOVED, f"the pid changed: {recorded} → {live}"

    detail = f"pid {live}" if live else "no pid"
    renamed = tab_name(tab)
    if renamed and entry.get("name") and renamed != entry["name"]:
        detail += f", renamed to {renamed!r}"
    return ALIVE, detail


def status(as_json: bool = False) -> int:
    registry = load_registry()
    data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    spaces = get_spaces(data)
    wanted = (registry.get("herdr") or {}).get("space_id")
    space = next((s for s in spaces if space_id(s) == wanted), None)

    roles = []
    for key, entry in ((registry.get("herdr") or {}).get("tabs") or {}).items():
        state, detail = _role_state(space, entry)
        roles.append({"role": key, "name": entry.get("name"),
                      "state": state, "detail": detail})

    alive = sum(1 for role in roles if role["state"] == ALIVE)
    diverged = any(role["state"] in DIVERGENT for role in roles)

    if as_json:
        print(json.dumps({
            "registry": {"status": registry.get("status"), "space_id": wanted},
            "roles": roles,
            "summary": {"total": len(roles), "alive": alive, "diverged": diverged},
        }, indent=2, ensure_ascii=False))
        return 1 if diverged else 0

    if registry.get("status") not in (None, "ready"):
        note(f"The registry is in state {registry.get('status')!r}"
             + (f": {registry['error']}" if registry.get("error") else ""))

    width = max((len(role["role"]) for role in roles), default=4)
    for role in roles:
        log(f"  {role['role']:<{width}}  {role['state']:<11} {role['detail']}")
    log(f"{alive} of {len(roles)} role(s) alive"
        + ("" if not diverged else " · the registry no longer describes reality"))
    return 1 if diverged else 0
