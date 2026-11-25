"""The ls command: the declared team against what the workspace is running.

`status` compares the registry with Herdr and `discover` lists the live tabs.
Neither can answer the question this command exists for: does the team declared
in agents.json match what is on screen? A role declared but never adopted has no
registry entry, so `status` never sees it, which is how a live tab can stay out
of the team without anyone noticing.

It only reads: it never creates, closes, moves or focuses a tab and never writes
the registry. `status` stays the command that rules on divergence.
"""

from __future__ import annotations

import json

from ..config import load_config
from ..errors import TorchaError
from ..herdr import (get_spaces, parse_json_output, run_app, space_id, tab_id)
from ..live import inspect_space, normalize, own_tab, role_tabs
from ..output import log, note
from ..registry import load_registry
# The state of a registered role is one rule, not two: `status` owns it and this
# command reports it unchanged, so both always agree about what `alive` means.
from .status import ALIVE, _role_state

NOT_ADOPTED = "not adopted"
UNKNOWN = "unknown"

DASH = "—"


def _short(value: object) -> str | None:
    """The start of a session id, or None: a line has room for eight characters."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().split("-")[0][:8]


def _or_dash(value: str | None) -> str:
    return value if value else DASH


def _count(value: int | None) -> str:
    """A count that could not be computed is asked, not guessed."""
    return "?" if value is None else str(value)


def _entries(registry: dict | None) -> dict[str, dict]:
    raw = ((registry or {}).get("herdr") or {}).get("tabs")
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(value, dict)}


def _space_of(registry: dict | None, spaces: list[dict]) -> dict | None:
    """The space the registry recorded, when `ls` still reports it."""
    wanted = ((registry or {}).get("herdr") or {}).get("space_id")
    if not wanted:
        return None
    return next((space for space in spaces if space_id(space) == wanted), None)


def _undeclared(space: dict, declared: list[dict], entries: dict[str, dict]):
    """Live tabs a human would count as the team but agents.json never declares.

    The exclusion predicate is the shared one: the setup marker, a tab Herdr
    named after its number and the tab running this command are not roles, so
    naming them would train the human to ignore the message.
    """
    own = own_tab()
    own_id = tab_id(own) if own else None
    names = {normalize(tab["name"]) for tab in declared}
    ids = {entries[tab["key"]].get("tab_id") for tab in declared
           if tab["key"] in entries}
    return [tab for tab in role_tabs(inspect_space(space, []), own_id)
            if tab.tab_id not in ids and normalize(tab.name) not in names]


def _rows(declared: list[dict], entries: dict[str, dict], space: dict | None,
          registry_failed: bool, live_failed: bool) -> list[dict]:
    rows: list[dict] = []
    for tab in declared:
        entry = entries.get(tab["key"])
        adopted = bool(entry and entry.get("tab_id"))
        if registry_failed:
            state, detail = UNKNOWN, "the registry could not be read"
        elif not adopted:
            state, detail = NOT_ADOPTED, "no tab in the registry"
        elif live_failed:
            state, detail = UNKNOWN, "the live workspace could not be read"
        else:
            state, detail = _role_state(space, entry)
        session_id = entry.get("session_id") if entry else None
        rows.append({
            "key": tab["key"],
            "name": tab["name"],
            "terminal": entry.get("terminal_id") if adopted else None,
            "state": state,
            "session": _short(session_id),
            "session_id": session_id if isinstance(session_id, str) else None,
            "detail": detail,
        })
    return rows


def _summary(rows: list[dict], declared: list[dict], entries: dict[str, dict],
             registry_failed: bool, live_failed: bool) -> dict:
    adopted = None if registry_failed else sum(
        1 for tab in declared if (entries.get(tab["key"]) or {}).get("tab_id"))
    alive = None if (registry_failed or live_failed) else sum(
        1 for row in rows if row["state"] == ALIVE)
    return {"declared": len(rows), "adopted": adopted, "alive": alive}


def _report(space: dict | None, wanted: str | None, rows: list[dict],
            undeclared: list, summary: dict, errors: list[str]) -> None:
    for message in errors:
        note(message)
    if space is not None:
        log(f"Space {space_id(space)} · {space.get('name') or 'unnamed'}")
    elif wanted:
        log(f"Space {wanted} is no longer in Herdr. Run 'torcha init' "
            "to create it again.")
    elif not errors:
        log("No Herdr space for this project was found. Run 'torcha init'.")

    key_w = max([len("role")] + [len(row["key"]) for row in rows])
    name_w = max([len("name")] + [len(row["name"]) for row in rows])
    terminal_w = max([len("terminal")] + [len(_or_dash(row["terminal"]))
                                          for row in rows])
    for row in rows:
        log(f"  {row['key']:<{key_w}}  {row['name']:<{name_w}}  "
            f"{_or_dash(row['terminal']):<{terminal_w}}  {row['state']:<11}  "
            f"{_or_dash(row['session']):<8}  {row['detail']}")

    if space is not None:
        if undeclared:
            log(f"Tabs not in the team ({len(undeclared)}): "
                + ", ".join(tab.name for tab in undeclared))
        else:
            log("No live tab is outside the team.")

    log(f"{_count(summary['declared'])} declared · "
        f"{_count(summary['adopted'])} adopted · "
        f"{_count(summary['alive'])} alive")


def ls(as_json: bool = False) -> int:
    declared = load_config()["tabs"]

    errors: list[str] = []
    registry: dict | None = None
    try:
        registry = load_registry()
    except TorchaError as exc:
        errors.append(str(exc))

    data = None
    try:
        data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    except TorchaError as exc:
        errors.append(str(exc))

    registry_failed = registry is None
    live_failed = data is None
    entries = _entries(registry)
    spaces = get_spaces(data) if data is not None else []
    wanted = ((registry or {}).get("herdr") or {}).get("space_id")
    space = _space_of(registry, spaces)
    rows = _rows(declared, entries, space, registry_failed, live_failed)
    undeclared = _undeclared(space, declared, entries) if space is not None else []
    summary = _summary(rows, declared, entries, registry_failed, live_failed)

    if as_json:
        print(json.dumps({
            "space": ({"id": space_id(space),
                       "name": space.get("name")} if space is not None else None),
            "roles": rows,
            "undeclared": [{"name": tab.name, "tab_id": tab.tab_id,
                            "terminal_id": tab.terminal_id, "app": tab.app}
                           for tab in undeclared],
            "summary": summary,
            "errors": errors,
        }, indent=2, ensure_ascii=False))
        return 1 if errors else 0

    _report(space, wanted, rows, undeclared, summary, errors)
    return 1 if errors else 0
