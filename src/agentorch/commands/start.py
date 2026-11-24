"""The start command: bring up the agents that are not running.

The usual reason a role has no agent is that Herdr was closed and its terminals
lost their programs. The cheap answer is to resume the same session, not to
rebuild context: a handoff is for when the context is full and someone decides to
renew, never for an accident.
"""

from __future__ import annotations

import json
import uuid

from .. import project
from ..bootstrap import pi_argv
from ..config import load_config
from ..errors import AgentorchError
from ..herdr import (agent_running, extract_tab_ids, first_string, get_spaces,
                     is_shell, parse_json_output, run_app, space_id, tab_id,
                     tab_name, tabs_of, terminal_pid, wait_for_agent,
                     wait_for_apps)
from ..output import log, note
from ..registry import load_registry, save_registry


def _find_terminal(space: dict, tab_id_value: str | None,
                   terminal_id: str | None) -> dict | None:
    tab = next((t for t in tabs_of(space) if tab_id(t) == tab_id_value), None)
    if tab is None:
        return None
    for terminal in tab.get("terminals") or []:
        if isinstance(terminal, dict) and terminal.get("terminal") == terminal_id:
            return terminal
    return None


def _close_tab(identifier: str) -> None:
    run_app(["do", "tab.close", "--id", identifier, "--confirmed", "true"])


def _create_tab(key: str, entry: dict, config: dict, space: str,
                argv: list[str] | None, session_id: str) -> dict | None:
    """Open the tab with `--argv` and take the ids from `ls`, not from the echo.

    No se teclea un programa en un shell: `hc send` envuelve el texto en
    `<hc from="…">…</hc>`, que un bash recibe literal y muere con "syntax error
    near unexpected token"; `--argv` es un array JSON y nunca pasa por bash.

    `tab.new` devuelve un id, pero es `ls` el que dice qué terminal y qué pane
    quedan dentro: es lo mismo que hacen `init` y el relevo de `handoff`.
    """
    name = entry.get("name") or key
    args = ["do", "tab.new", "--name", name, "--space", space,
            "--folder", str(project.PROJECT_DIR), "--focus", "false"]
    if argv:
        args += ["--argv", json.dumps(argv)]
    created = parse_json_output(run_app(args), f"tab.new ({key})")

    # El eco es lo último que se cree: solo si `ls` no llega a enseñar la tab.
    try:
        final_space, _pending = wait_for_apps(space, [name])
    except AgentorchError:
        final_space = None
    tab = next((t for t in (tabs_of(final_space) if final_space else [])
                if (tab_name(t) or "") == name), None)
    if tab is not None:
        ids = extract_tab_ids(tab)
        identifier, terminal = tab_id(tab), ids["terminal_id"]
        pane = ids["pane_id"]
    else:
        identifier = first_string(created, "tab", "tab_id", "id")
        terminal = first_string(created, "terminal", "terminal_id")
        pane = None
    if not identifier or not terminal:
        return None
    return {"tab_id": identifier, "terminal_id": terminal, "pane_id": pane,
            "session_id": session_id}


def _recreate(key: str, entry: dict, config: dict, space: str,
              fresh: bool = False) -> dict | None:
    """Rebuild a tab that was closed, resuming its session unless `fresh`.

    This is the accident path: the tab is gone, so there is nothing to resume in
    place. Recreating it with the old session id brings the conversation back,
    which is not what a deliberate handoff does; `--fresh` is the explicit way to
    start another conversation instead.
    """
    session_id = str(uuid.uuid4()) if fresh else (
        entry.get("session_id") or str(uuid.uuid4()))
    argv = pi_argv(config, {"key": key}, session_id)
    return _create_tab(key, entry, config, space, argv, session_id)


def start(role: str | None = None, fresh: bool = False, timeout: float = 60.0,
          interval: float = 1.0, recreate: bool = False) -> int:
    registry = load_registry()
    config = load_config()
    executable = config["pi"]["executable"]

    data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    spaces = get_spaces(data)
    wanted = (registry.get("herdr") or {}).get("space_id")
    space = next((s for s in spaces if space_id(s) == wanted), None)
    if space is None:
        note(f"El space {wanted!r} del registro ya no existe.")
        return 1

    entries = (registry.get("herdr") or {}).get("tabs") or {}
    if role is not None and role not in entries:
        note(f"No hay ningún rol {role!r} en el registro.")
        return 1

    started = skipped = failed = 0
    for key, entry in entries.items():
        if role is not None and key != role:
            continue

        terminal = entry.get("terminal_id")
        if not terminal:
            note(f"{key}: el registro no tiene terminal; ejecuta 'agentorch init'.")
            failed += 1
            continue
        if _find_terminal(space, entry.get("tab_id"), terminal) is None:
            if not recreate:
                note(f"{key}: la tab o el terminal ya no existen "
                     "(usa --recreate para levantarla).")
                failed += 1
                continue
            previous_session = entry.get("session_id")
            rebuilt = _recreate(key, entry, config, wanted, fresh)
            if rebuilt is None:
                note(f"{key}: no se pudo recrear la tab.")
                failed += 1
                continue
            entry.update({"tab_id": rebuilt["tab_id"],
                          "terminal_id": rebuilt["terminal_id"],
                          "pane_id": rebuilt["pane_id"],
                          "session_id": rebuilt["session_id"]})
            terminal = rebuilt["terminal_id"]
            if not wait_for_agent(terminal, executable, timeout, interval):
                note(f"{key}: la tab se recreó pero el agente no apareció.")
                failed += 1
                save_registry(registry)
                continue
            entry.update({"pid": terminal_pid(terminal),
                          "app": config["pi"]["executable"]})
            save_registry(registry)
            resumed = rebuilt["session_id"] == previous_session
            log(f"{key}: tab recreada ({rebuilt['tab_id']}), "
                f"sesión {'reanudada' if resumed else 'nueva'}")
            started += 1
            continue
        if agent_running(terminal, executable):
            log(f"{key}: ya está en marcha")
            skipped += 1
            continue
        if not is_shell(terminal):
            note(f"{key}: el terminal no es un shell; no se envía nada a ciegas.")
            failed += 1
            continue

        session_id = (str(uuid.uuid4()) if fresh
                      else entry.get("session_id") or str(uuid.uuid4()))
        resumed = not fresh and entry.get("session_id") == session_id
        argv = pi_argv(config, {"key": key}, session_id)
        if argv is None:
            note(f"{key}: el bootstrap está desactivado en agents.json.")
            skipped += 1
            continue
        previous_tab = entry.get("tab_id")
        if not previous_tab:
            note(f"{key}: el registro no tiene tab; ejecuta 'agentorch init'.")
            failed += 1
            continue

        # El agente ya no está, pero su tab sigue ahí con un shell: se reemplaza
        # la tab en vez de teclear el arranque, que un bash no puede ejecutar.
        try:
            _close_tab(previous_tab)
        except AgentorchError as exc:
            note(f"{key}: no se pudo cerrar la tab {previous_tab}: {exc}")
            failed += 1
            continue
        rebuilt = _create_tab(key, entry, config, wanted, argv, session_id)
        if rebuilt is None:
            note(f"{key}: la tab se cerró y la nueva no se pudo crear.")
            failed += 1
            continue
        entry.update({"tab_id": rebuilt["tab_id"],
                      "terminal_id": rebuilt["terminal_id"],
                      "pane_id": rebuilt["pane_id"],
                      "session_id": session_id})
        terminal = rebuilt["terminal_id"]

        if not wait_for_agent(terminal, executable, timeout, interval):
            note(f"{key}: la tab se recreó pero el agente no apareció "
                 f"en {timeout:g}s.")
            failed += 1
            save_registry(registry)
            continue

        entry.update({"pid": terminal_pid(terminal), "app": executable})
        save_registry(registry)
        log(f"{key}: {'reanudada' if resumed else 'sesión nueva'} "
            f"({session_id}), pid={entry['pid']}")
        started += 1

    log(f"{started} arrancada(s), {skipped} ya en marcha, {failed} con problemas")
    return 1 if failed else 0
