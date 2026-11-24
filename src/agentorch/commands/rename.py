"""The rename command: give a role's tab its final name.

The agent never touches `herdr-app`. It asks agentorch by role, and agentorch
resolves the tab id from the registry, checks the tab still exists and performs
the rename.
"""

from __future__ import annotations

from ..errors import AgentorchError
from ..herdr import get_spaces, parse_json_output, run_app, tab_id, tabs_of
from ..output import log, note
from ..registry import load_registry, save_registry


def rename(role: str, name: str) -> int:
    name = name.strip()
    if not name:
        note("El nombre nuevo no puede estar vacío.")
        return 1

    registry = load_registry()
    entries = (registry.get("herdr") or {}).get("tabs") or {}
    entry = entries.get(role)
    if entry is None:
        note(f"No hay ningún rol {role!r} en el registro. Ejecuta 'agentorch init'.")
        return 1

    tab = entry.get("tab_id")
    if not tab:
        note(f"{role}: el registro no tiene tab_id; ejecuta 'agentorch init'.")
        return 1

    data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    exists = any(tab_id(inner) == tab
                 for space in get_spaces(data) for inner in tabs_of(space))
    if not exists:
        note(f"{role}: la tab {tab} ya no existe.")
        return 1

    try:
        run_app(["do", "tab.rename", "--id", tab, "--name", name])
    except AgentorchError as exc:
        note(f"{role}: {exc}")
        return 1

    entry["name"] = name
    save_registry(registry)
    log(f"{role}: tab renombrada a {name!r}")
    return 0
