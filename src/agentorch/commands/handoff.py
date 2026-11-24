"""The handoff command: validate a handoff document."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .. import project
from ..bootstrap import pi_argv, write_bootstrap_files
from ..config import load_config
from ..errors import AgentorchError
from ..git import repo_head, repo_state
from ..handoff import handoff_path, load_handoff, new_handoff, validate_handoff
from ..herdr import (agent_running, agent_state, extract_tab_ids, runs_inside,
                     send_text, tab_id, tab_name, tabs_of, terminal_pid,
                     run_app, wait_for_agent, wait_for_apps)
from ..output import log, note
from ..registry import load_registry, save_registry


def _expected_project(path: Path) -> str | None:
    """The project a handoff must name, but only when it lives inside this one.

    Validating a file from somewhere else says nothing about which project it
    belongs to, and comparing against the current directory would invent an error.
    """
    try:
        path.resolve().relative_to(project.PROJECT_DIR)
    except ValueError:
        return None
    return project.PROJECT_NAME


def validate(path: str, as_json: bool = False, check_head: bool = False) -> int:
    target = Path(path)
    data = load_handoff(target)
    problems = validate_handoff(data, project_name=_expected_project(target))

    if check_head:
        head = repo_head()
        recorded = (data.get("git") or {}).get("head")
        if head is None:
            note("no se pudo leer el commit actual: no se verificó git.head")
        elif recorded and head != recorded:
            problems.append("el repositorio se movió desde el handoff: "
                            f"{recorded} → {head}")

    if as_json:
        print(json.dumps({"valid": not problems, "problems": problems,
                          "path": str(path)}, indent=2, ensure_ascii=False))
        return 1 if problems else 0

    if problems:
        for problem in problems:
            note(f"  {problem}")
        note(f"Handoff inválido: {len(problems)} problema(s) en {path}")
        return 1

    log(f"Handoff válido: {path}")
    return 0


# --- run: ask the agent for its handoff ------------------------------------

RELEVO = (
    "Te van a relevar. Rellena el handoff en {path} con lo que sepas y hayas "
    "medido. Respeta la forma de cada campo:\n"
    "- `objective` y `current_state`: una frase cada uno.\n"
    "- `completed`, `in_progress`, `next_actions`, `decisions`, `blockers`: "
    "listas de cadenas.\n"
    "- `files_touched`: lista de OBJETOS, uno por fichero: "
    '{{"path": "ruta/relativa", "reason": "por qué lo tocaste"}}.\n'
    "- `engram_refs`: lista de CADENAS, las claves de Engram que cites.\n"
    "- `validation`: objeto con dos listas de cadenas: `commands_run` y "
    "`results`.\n"
    "- `git` lo mide agentorch y no se toca.\n"
    "No inventes estado: si no lo has medido, dilo. No cambies las claves ni el sha."
)


def _head_problems(path: Path) -> list[str]:
    """El sha que el handoff declara tiene que ser el que el repositorio tiene ahora.

    Un `git.head` que ya no existe desarma la comprobación que hace la sesión que
    releva al arrancar: comparar el handoff con `git rev-parse HEAD`.
    """
    recorded = (load_handoff(path).get("git") or {}).get("head")
    head = repo_head()
    if head is None:
        note("no se pudo leer el commit actual: no se verificó git.head")
        return []
    if recorded and recorded != head:
        return [f"el handoff declara {recorded} y el repositorio está en {head}"]
    return []


def _wait_for_valid(path: Path, timeout: float, interval: float,
                    agent_id: str) -> tuple[bool, list[str]]:
    """Poll until the file validates, or the deadline passes."""
    deadline = time.monotonic() + timeout
    while True:
        if path.exists():
            data = load_handoff(path)
            problems = validate_handoff(data, project_name=project.PROJECT_NAME,
                                        agent_id=agent_id)
            if not problems:
                return True, []
            last = problems
        else:
            last = [f"el agente no escribió {path}"]
        if time.monotonic() >= deadline:
            return False, last
        time.sleep(interval)


def _prepare(key: str, entry: dict, config: dict, timeout: float,
             interval: float) -> tuple[Path | None, list[str]]:
    terminal = entry.get("terminal_id")
    if not terminal:
        return None, ["el registro no tiene terminal; ejecuta 'agentorch init'"]
    executable = config["pi"]["executable"]
    if not agent_running(terminal, executable):
        return None, ["no hay ningún agente vivo en ese terminal"]
    if runs_inside(terminal):
        return None, ["esa terminal es la que está ejecutando este comando"]

    state = repo_state()
    if not state["head"]:
        return None, ["el proyecto no tiene commits: no se puede afirmar un sha"]

    if not entry.get("session_id"):
        note(f"{key}: el registro no tiene session_id; el handoff lo dejará "
             "como 'desconocida' y no se podrá comprobar que lo escribió esta sesión.")
    document = new_handoff(
        agent_id=key, role=entry.get("name") or key,
        source_pi_session_id=entry.get("session_id") or "desconocida",
        objective="", current_state="",
        git_branch=state["branch"], git_head=state["head"],
        git_status_summary=state["status_summary"])
    path = handoff_path(key, document["handoff_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")

    state = agent_state(terminal)
    if state == "working":
        note(f"{key}: el agente está trabajando; el aviso queda encolado detrás "
             f"de su turno actual, así que puede tardar más que {timeout:g}s.")

    if not send_text(terminal, RELEVO.format(path=path)):
        return None, [f"herdr-core no aceptó el envío al terminal {terminal}"]

    ok, problems = _wait_for_valid(path, timeout, interval, key)
    if ok:
        return path, _head_problems(path)
    if not json.loads(path.read_text(encoding="utf-8")).get("objective"):
        return path, [f"el agente no llegó a escribirlo en {timeout:g}s"
                      + (" (estaba trabajando)" if state == "working" else "")]
    return path, problems


def _swap(key: str, entry: dict, config: dict, registry: dict, timeout: float,
          interval: float, path: Path | None) -> list[str]:
    terminal = entry.get("terminal_id")
    if not terminal:
        return ["el registro no tiene terminal"]
    if runs_inside(terminal):
        return ["esa terminal es la que está ejecutando este comando"]
    previous_tab = entry.get("tab_id")
    if not previous_tab:
        return ["el registro no tiene tab"]
    space = (registry.get("herdr") or {}).get("space_id")
    if not space:
        return ["el registro no tiene space_id"]

    # Nunca cerrar a un agente a mitad de un turno: cerrar la tab interrumpiría
    # una herramienta en vuelo en vez de relevar la sesión.
    deadline = time.monotonic() + timeout
    while agent_state(terminal) == "working":
        if time.monotonic() >= deadline:
            return ["el agente sigue trabajando; no se le cierra a la fuerza"]
        time.sleep(interval)

    item = next((tab for tab in config.get("tabs") or [] if tab.get("key") == key), None)
    if item is None:
        return [f"{key} ya no está en agents.json"]
    if config["pi"]["bootstrap"] == "none":
        return ["el bootstrap está desactivado en agents.json"]
    # Un relevo arranca siempre en `recover`: el handoff recién validado es el
    # estado que la sesión nueva hereda, y con `greet` no llegaría a leerlo.
    write_bootstrap_files([item], "recover")
    session_id = str(uuid.uuid4())
    argv = pi_argv(config, item, session_id)
    if argv is None:
        return ["el bootstrap está desactivado en agents.json"]

    # El relevo no teclea nada en un shell: cierra la tab y abre otra con
    # `--argv`. `hc send` envuelve el texto que escribe en `<hc from="…">…</hc>`,
    # que un bash recibe literal y muere con "syntax error near unexpected
    # token"; `--argv` es un array JSON y nunca pasa por bash.
    try:
        run_app(["do", "tab.close", "--id", previous_tab, "--confirmed", "true"])
    except AgentorchError as exc:
        return [f"no se pudo cerrar la tab {previous_tab}: {exc}"]

    name = entry.get("name") or key
    try:
        run_app(["do", "tab.new", "--name", name, "--space", space,
                 "--folder", str(project.PROJECT_DIR), "--focus", "false",
                 "--argv", json.dumps(argv)])
    except AgentorchError as exc:
        entry.update({"tab_id": None, "terminal_id": None, "pane_id": None,
                      "pid": None, "app": None, "session_id": None})
        return [f"la tab se cerró y la nueva no se pudo crear: {exc}"]

    # Los ids definitivos solo se conocen releyendo el estado: `tab.new` devuelve
    # un id, pero es `ls` el que dice qué terminal y qué pane lleva dentro.
    final_space, pending = wait_for_apps(space, [name])
    fresh = next((tab for tab in (tabs_of(final_space) if final_space else [])
                  if (tab_name(tab) or "") == name), None)
    if fresh is None:
        entry.update({"tab_id": None, "terminal_id": None, "pane_id": None,
                      "pid": None, "app": None, "session_id": None})
        return [f"la tab '{name}' no aparece tras el relevo"
                + (f" (sin aplicación: {', '.join(pending)})" if pending else "")]
    ids = extract_tab_ids(fresh)
    entry.update({"tab_id": tab_id(fresh), "terminal_id": ids["terminal_id"],
                  "pane_id": ids["pane_id"]})
    new_terminal = ids["terminal_id"]
    if not new_terminal:
        return [f"la tab '{name}' no declara terminal"]

    if not wait_for_agent(new_terminal, config["pi"]["executable"], timeout, interval):
        entry.update({"pid": None, "app": None, "session_id": None})
        return [f"el agente no apareció en la tab nueva '{name}'"]

    entry.update({"pid": terminal_pid(new_terminal), "session_id": session_id,
                  "app": config["pi"]["executable"]})
    if path is not None:
        try:
            document = load_handoff(path)
            document["status"] = "consumed"
            path.write_text(json.dumps(document, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        except AgentorchError:
            pass
    return []


def _prepared(key: str) -> Path | None:
    """The newest handoff for a role that already validates and is still prepared."""
    directory = project.AGENTORCH_DIR / "handoffs" / key
    if not directory.is_dir():
        return None
    newest_first = sorted(directory.glob("*.json"),
                          key=lambda item: item.stat().st_mtime, reverse=True)
    for path in newest_first:
        try:
            data = load_handoff(path)
        except AgentorchError:
            continue
        if data.get("status") != "prepared":
            continue
        if not validate_handoff(data, project_name=project.PROJECT_NAME, agent_id=key):
            return path
    return None


def run(role: str | None = None, all_roles: bool = False, swap: bool = False,
        timeout: float = 300.0, interval: float = 1.0,
        force: bool = False) -> int:
    registry = load_registry()
    config = load_config()
    entries = (registry.get("herdr") or {}).get("tabs") or {}

    if all_roles and role is not None:
        note("Usa un rol concreto o --all, no las dos cosas.")
        return 1
    if not all_roles and role is None:
        note(f"Dime qué rol. Disponibles: {', '.join(entries)}")
        return 1
    if role is not None and role not in entries:
        note(f"No hay ningún rol {role!r} en el registro.")
        return 1

    targets = list(entries.items()) if all_roles else [(role, entries[role])]
    failed = 0
    for key, entry in targets:
        # Con --swap siempre se vuelve a pedir: se está a punto de perder la
        # sesión, así que el handoff tiene que ser de ahora, no de hace horas.
        if not force and not swap:
            done = _prepared(key)
            if done is not None:
                log(f"{key}: ya tenía un handoff válido ({done.name}); se salta")
                continue
        path, problems = _prepare(key, entry, config, timeout, interval)
        if problems:
            note(f"{key}: handoff no válido — {'; '.join(problems)}")
            failed += 1
            if all_roles:
                note("Se para aquí: los demás roles no se tocaron.")
                break
            continue
        log(f"{key}: handoff escrito y validado ({path.name})")
        if not swap:
            continue
        errors = _swap(key, entry, config, registry, timeout, interval, path)
        if errors:
            note(f"{key}: handoff válido, pero el relevo falló — {'; '.join(errors)}")
            failed += 1
            if all_roles:
                break
        else:
            save_registry(registry)
            log(f"{key}: sesión reemplazada, pid={entry['pid']}")

    if swap or failed:
        save_registry(registry)
    return 1 if failed else 0
