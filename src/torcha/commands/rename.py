"""The rename command: give a role's tab its final name.

The agent never touches `herdr-app`. It asks torcha by role, and torcha
resolves the tab id from the registry, checks the tab still exists and performs
the rename.
"""

from __future__ import annotations

from ..errors import TorchaError
from ..herdr import get_spaces, parse_json_output, run_app, tab_id, tabs_of
from ..output import log, note
from ..registry import load_registry, save_registry


def rename(role: str, name: str) -> int:
    name = name.strip()
    if not name:
        note("The new name cannot be empty.")
        return 1

    registry = load_registry()
    entries = (registry.get("herdr") or {}).get("tabs") or {}
    entry = entries.get(role)
    if entry is None:
        note(f"There is no role {role!r} in the registry. Run 'torcha init'.")
        return 1

    tab = entry.get("tab_id")
    if not tab:
        note(f"{role}: the registry has no tab_id; run 'torcha init'.")
        return 1

    data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    exists = any(tab_id(inner) == tab
                 for space in get_spaces(data) for inner in tabs_of(space))
    if not exists:
        note(f"{role}: tab {tab} no longer exists.")
        return 1

    try:
        run_app(["do", "tab.rename", "--id", tab, "--name", name])
    except TorchaError as exc:
        note(f"{role}: {exc}")
        return 1

    entry["name"] = name
    save_registry(registry)
    log(f"{role}: tab renamed to {name!r}")
    return 0
