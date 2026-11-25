"""The recover command: ask a running agent to catch up, without replacing it.

A parked or long-idle role needs to catch up on the world, not to be replaced.
The launch bootstrap cannot do it — it asks a session that has just started to
confirm who it is and then wait — and `RELEVO` cannot either: it asks for a
handoff because the session is about to be destroyed. This command types one
message into the agent that is already running, in its own session.
"""

from __future__ import annotations

from ..config import load_config
from ..herdr import agent_running, runs_inside, send_text
from ..output import log, note
from ..registry import load_registry

# Escrito para una sesión que ya está en marcha y a mitad de una conversación:
# no reinicia, no relee el proyecto entero y no pide un handoff. El árbol de
# trabajo manda sobre el documento, y el handoff es lo primero que se relee.
CATCH_UP = (
    "Catch up with the project as it is now. You are already running in this "
    "session: do not restart it, do not ask for instructions and do not re-read "
    "the whole project.\n"
    "- Read your newest handoff: the most recent file in "
    "`.agentorch/handoffs/{key}/`.\n"
    "- Compare its `git.head` with `git rev-parse HEAD`, then read the working "
    "tree: the tree is the source of truth, never the document.\n"
    "- Look your role up in Engram: `mem_search` for the project and your role, "
    "then `mem_get_observation` on the best hit and read it in full; a snippet "
    "is not enough.\n"
    "- Answer in your own tab with what is done, what is pending and anything "
    "the repository contradicts. Do not write a handoff, do not change the keys "
    "or the sha, and do not start work on your own."
)


def recover(role: str) -> int:
    """Send the catch-up message to a role's live agent and return.

    Nothing else is touched: the tab is not created, closed or focused, the
    session id stays the same, the registry is not written and no handoff is
    opened. Refusals send nothing.
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
    if runs_inside(terminal):
        note(f"{role}: that terminal is the one running this command")
        return 1

    if not send_text(terminal, CATCH_UP.format(key=role)):
        note(f"{role}: herdr-core did not accept the send to terminal {terminal}")
        return 1

    log(f"{role}: catch-up message sent to its running session "
        f"(no tab, no session id and no handoff touched)")
    return 0
