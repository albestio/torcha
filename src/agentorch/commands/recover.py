"""The recover command: ask a running agent to catch up, without replacing it.

A parked or long-idle role needs to catch up on the world, not to be replaced.
The launch bootstrap cannot do it — it asks a session that has just started to
confirm who it is and then wait — and `RELEVO` cannot either: it asks for a
handoff because the session is about to be destroyed. This command types one
message into the agent that is already running, in its own session.
"""

from __future__ import annotations

from .. import project
from ..config import load_config
from ..herdr import (agent_running, agent_state, runs_inside, send_text,
                     tab_id, tab_name, tab_of_terminal)
from ..output import log, note
from ..registry import load_registry

# Escrito para una sesión que ya está en marcha y a mitad de una conversación:
# no reinicia, no relee el proyecto entero y no pide un handoff. El árbol de
# trabajo manda sobre el documento, y el handoff es lo primero que se relee.
# Cada fuente que puede faltar trae su propia salida: un handoff que no existe
# y un Engram vacío se declaran y se continúa, en vez de pedir una comparación
# que no se puede hacer.
CATCH_UP = (
    "Catch up with the project as it is now. You are {name} (`{key}`), a member "
    "of the agentorch team for the project `{project}`. You are already running "
    "in this session: do not restart it, do not ask for instructions and do not "
    "re-read the whole project — check only what you need to trust the state "
    "below.\n"
    "- Read your newest handoff: the newest file in `.agentorch/handoffs/{key}/`, "
    "by modification time. That file is the state your previous session left. "
    "If there is none, say so and continue.\n"
    "- Compare its `git.head` with `git rev-parse HEAD`, and if HEAD moved, "
    "re-measure what the handoff claims and say what changed. Where the document "
    "and the repository disagree, the tree is the source of truth, never the "
    "document.\n"
    "- Look your role up in Engram: `mem_search` for the project and your role, "
    "then `mem_get_observation` on the best hit and read it in full; a snippet "
    "is not enough. If there is nothing, say so and continue.\n"
    "- Answer in your own tab with what is done, what is pending and anything "
    "the repository contradicts. Do not write a handoff and do not start work "
    "on your own."
)


def _label(role: str, entry: dict, config: dict) -> str:
    """The role's human name: agents.json first, the registry next, the key last."""
    item = next((tab for tab in config.get("tabs") or []
                 if isinstance(tab, dict) and tab.get("key") == role), None)
    for candidate in ((item or {}).get("name"), entry.get("name"), role):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return role


def _tab_identity(role: str, entry: dict,
                  terminal: str) -> tuple[str | None, str | None]:
    """Whether the terminal is in the tab the registry records, and any drift.

    A terminal running the configured executable proves nothing about who is in
    it: terminal ids are reused, so the entry can end on another role's tab and
    this role's handoff path would reach a stranger. The tab id is the identity
    and it is fatal when it disagrees. The name is the human's label: renaming a
    tab in Herdr does not change who is inside it, so that is reported and the
    message still goes to the agent the id points at.
    """
    tab = tab_of_terminal(terminal)
    if tab is None:
        return (f"its terminal {terminal} is in no tab of this workspace; "
                f"nothing was sent — run 'agentorch start {role}'"), None
    live_id, live_name = tab_id(tab), tab_name(tab)
    recorded_id, recorded_name = entry.get("tab_id"), entry.get("name")
    if recorded_id and live_id and live_id != recorded_id:
        where = f" ({live_name})" if live_name else ""
        return (f"terminal {terminal} now lives in tab {live_id}{where}, not the "
                f"tab the registry records for it ({recorded_id}); nothing was "
                f"sent — run 'agentorch start {role}'"), None
    if recorded_name and live_name and live_name != recorded_name:
        return None, (f"the tab holding terminal {terminal} is named {live_name!r} "
                      f"but the registry records {recorded_name!r}; sending anyway, "
                      f"run 'agentorch start {role}' to refresh the name")
    return None, None


def recover(role: str) -> int:
    """Send the catch-up message to a role's live agent and return.

    Nothing else is touched: the tab is not created, closed or focused, the
    session id stays the same, the registry is not written and no handoff is
    opened. Refusals send nothing, and so does a target whose terminal is no
    longer in that role's tab.
    """
    registry = load_registry()
    config = load_config()
    entries = (registry.get("herdr") or {}).get("tabs") or {}

    if role not in entries:
        note(f"There is no role {role!r} in the registry. "
             f"Available: {', '.join(entries)}")
        return 1
    entry = entries[role]
    terminal = entry.get("terminal_id")
    if not terminal:
        note(f"{role}: the registry has no terminal; run 'agentorch start {role}'")
        return 1
    if not agent_running(terminal, config["pi"]["executable"]):
        note(f"{role}: no agent is running in terminal {terminal}; "
             f"start it with 'agentorch start {role}'")
        return 1
    problem, drift = _tab_identity(role, entry, terminal)
    if problem:
        note(f"{role}: {problem}")
        return 1
    if drift:
        note(f"{role}: {drift}")
    if runs_inside(terminal):
        note(f"{role}: that terminal is the one running this command")
        return 1

    # A mitad de turno el mensaje se queda en cola: decirlo así, y no como si el
    # agente ya hubiera contestado, es la misma advertencia que hace `handoff`.
    queued = agent_state(terminal) == "working"
    if queued:
        note(f"{role}: the agent is working; the message queues behind its "
             f"current turn, so it has not been answered yet.")

    text = CATCH_UP.format(project=project.PROJECT_NAME, key=role,
                           name=_label(role, entry, config))
    if not send_text(terminal, text):
        note(f"{role}: herdr-core did not accept the send to terminal {terminal}")
        return 1

    where = ("queued behind its current turn" if queued
             else "sent to its running session")
    log(f"{role}: catch-up message {where} "
        f"(no tab, no session id and no handoff touched)")
    return 0
