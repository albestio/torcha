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
# La edad de un handoff se dice igual aquí y en `status`: una sola redacción.
from .status import _age_seconds as handoff_age_seconds
from .status import _age_text as handoff_age_text


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
            note("could not read the current commit: git.head was not checked")
        elif recorded and head != recorded:
            problems.append("the repository moved since the handoff: "
                            f"{recorded} → {head}")

    if as_json:
        print(json.dumps({"valid": not problems, "problems": problems,
                          "path": str(path)}, indent=2, ensure_ascii=False))
        return 1 if problems else 0

    if problems:
        for problem in problems:
            note(f"  {problem}")
        note(f"Invalid handoff: {len(problems)} problem(s) in {path}")
        return 1

    log(f"Valid handoff: {path}")
    return 0


# --- run: ask the agent for its handoff ------------------------------------

RELEVO = (
    "You are about to be relieved. Fill in the handoff at {path} with what you "
    "know and have measured. Respect the shape of every field:\n"
    "- `objective` and `current_state`: one sentence each.\n"
    "- `completed`, `in_progress`, `next_actions`, `decisions`, `blockers`: "
    "lists of strings.\n"
    "- `files_touched`: list of OBJECTS, one per file: "
    '{{"path": "relative/path", "reason": "why you touched it"}}.\n'
    "- `engram_refs`: list of STRINGS, the Engram keys you cite.\n"
    "- `validation`: object with two lists of strings: `commands_run` and "
    "`results`.\n"
    "- `git` is measured by agentorch and must not be edited.\n"
    "Do not invent state: if you have not measured it, say so. Do not change "
    "the keys or the sha."
)


def _head_problems(path: Path) -> list[str]:
    """El sha que el handoff declara tiene que ser el que el repositorio tiene ahora.

    Un `git.head` que ya no existe desarma la comprobación que hace la sesión que
    releva al arrancar: comparar el handoff con `git rev-parse HEAD`.
    """
    recorded = (load_handoff(path).get("git") or {}).get("head")
    head = repo_head()
    if head is None:
        note("could not read the current commit: git.head was not checked")
        return []
    if recorded and recorded != head:
        return [f"the handoff declares {recorded} and the repository is at {head}"]
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
            last = [f"the agent did not write {path}"]
        if time.monotonic() >= deadline:
            return False, last
        time.sleep(interval)


def _prepare(key: str, entry: dict, config: dict, timeout: float,
             interval: float) -> tuple[Path | None, list[str]]:
    terminal = entry.get("terminal_id")
    if not terminal:
        return None, ["the registry has no terminal; run 'agentorch init'"]
    executable = config["pi"]["executable"]
    if not agent_running(terminal, executable):
        return None, ["no agent is running in that terminal"]
    if runs_inside(terminal):
        return None, ["that terminal is the one running this command"]

    state = repo_state()
    if not state["head"]:
        return None, ["the project has no commits: no sha can be stated"]

    if not entry.get("session_id"):
        note(f"{key}: the registry has no session_id; the handoff will leave "
             "it as 'unknown' and it will not be possible to check that this "
             "session wrote it.")
    document = new_handoff(
        agent_id=key, role=entry.get("name") or key,
        source_pi_session_id=entry.get("session_id") or "unknown",
        objective="", current_state="",
        git_branch=state["branch"], git_head=state["head"],
        git_status_summary=state["status_summary"])
    path = handoff_path(key, document["handoff_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")

    state = agent_state(terminal)
    if state == "working":
        note(f"{key}: the agent is working; the notice queues behind its current "
             f"turn, so it may take longer than {timeout:g}s.")

    if not send_text(terminal, RELEVO.format(path=path)):
        return None, [f"herdr-core did not accept the send to terminal {terminal}"]

    ok, problems = _wait_for_valid(path, timeout, interval, key)
    if ok:
        return path, _head_problems(path)
    if not json.loads(path.read_text(encoding="utf-8")).get("objective"):
        return path, [f"the agent did not get to write it in {timeout:g}s"
                      + (" (it was working)" if state == "working" else "")]
    return path, problems


def _swap(key: str, entry: dict, config: dict, registry: dict, timeout: float,
          interval: float, path: Path | None, consume: bool = True) -> list[str]:
    terminal = entry.get("terminal_id")
    if not terminal:
        return ["the registry has no terminal"]
    if runs_inside(terminal):
        return ["that terminal is the one running this command"]
    previous_tab = entry.get("tab_id")
    if not previous_tab:
        return ["the registry has no tab"]
    space = (registry.get("herdr") or {}).get("space_id")
    if not space:
        return ["the registry has no space_id"]

    # Nunca cerrar a un agente a mitad de un turno: cerrar la tab interrumpiría
    # una herramienta en vuelo en vez de relevar la sesión.
    deadline = time.monotonic() + timeout
    while agent_state(terminal) == "working":
        if time.monotonic() >= deadline:
            return ["the agent is still working; it is not closed by force"]
        time.sleep(interval)

    item = next((tab for tab in config.get("tabs") or [] if tab.get("key") == key), None)
    if item is None:
        return [f"{key} is no longer in agents.json"]
    if config["pi"]["bootstrap"] == "none":
        return ["bootstrap is disabled in agents.json"]
    # Un relevo arranca siempre en `recover`: el handoff recién validado es el
    # estado que la sesión nueva hereda, y con `greet` no llegaría a leerlo.
    write_bootstrap_files([item], "recover")
    session_id = str(uuid.uuid4())
    argv = pi_argv(config, item, session_id)
    if argv is None:
        return ["bootstrap is disabled in agents.json"]

    # El relevo no teclea nada en un shell: cierra la tab y abre otra con
    # `--argv`. `hc send` envuelve el texto que escribe en `<hc from="…">…</hc>`,
    # que un bash recibe literal y muere con "syntax error near unexpected
    # token"; `--argv` es un array JSON y nunca pasa por bash.
    try:
        run_app(["do", "tab.close", "--id", previous_tab, "--confirmed", "true"])
    except AgentorchError as exc:
        return [f"could not close tab {previous_tab}: {exc}"]

    name = entry.get("name") or key
    try:
        run_app(["do", "tab.new", "--name", name, "--space", space,
                 "--folder", str(project.PROJECT_DIR), "--focus", "false",
                 "--argv", json.dumps(argv)])
    except AgentorchError as exc:
        entry.update({"tab_id": None, "terminal_id": None, "pane_id": None,
                      "pid": None, "app": None, "session_id": None})
        return [f"the tab was closed and the new one could not be created: {exc}"]

    # Los ids definitivos solo se conocen releyendo el estado: `tab.new` devuelve
    # un id, pero es `ls` el que dice qué terminal y qué pane lleva dentro.
    final_space, pending = wait_for_apps(space, [name])
    fresh = next((tab for tab in (tabs_of(final_space) if final_space else [])
                  if (tab_name(tab) or "") == name), None)
    if fresh is None:
        entry.update({"tab_id": None, "terminal_id": None, "pane_id": None,
                      "pid": None, "app": None, "session_id": None})
        return [f"tab '{name}' does not appear after the swap"
                + (f" (no application: {', '.join(pending)})" if pending else "")]
    ids = extract_tab_ids(fresh)
    entry.update({"tab_id": tab_id(fresh), "terminal_id": ids["terminal_id"],
                  "pane_id": ids["pane_id"]})
    new_terminal = ids["terminal_id"]
    if not new_terminal:
        return [f"tab '{name}' declares no terminal"]

    if not wait_for_agent(new_terminal, config["pi"]["executable"], timeout, interval):
        entry.update({"pid": None, "app": None, "session_id": None})
        return [f"the agent did not appear in the new tab '{name}'"]

    entry.update({"pid": terminal_pid(new_terminal), "session_id": session_id,
                  "app": config["pi"]["executable"]})
    # Un documento reutilizado se deja tal cual: la sesión nueva lee el que se le
    # dio, y reescribirlo —aunque solo fuese el estado— es lo que `--use-existing`
    # existe para evitar.
    if path is not None and consume:
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


def _existing_handoff(key: str) -> tuple[Path | None, list[str]]:
    """The handoff to reuse, or the problems that forbid reusing it.

    No path and no problems means there is nothing eligible on disk and the
    caller falls back to asking the agent. The document is validated again
    here: a file that stopped being `prepared`, or that names another agent or
    project, is not eligible, whatever it said when it was written.
    """
    path = _prepared(key)
    if path is None:
        return None, []
    return path, _head_problems(path)


def run(role: str | None = None, all_roles: bool = False, swap: bool = False,
        timeout: float = 300.0, interval: float = 1.0,
        force: bool = False, use_existing: bool = False) -> int:
    # Reutilizar el documento de disco solo tiene sentido cuando hay una sesión
    # que relevar: sin `--swap` no se reemplaza nada y el flag no significa nada.
    if use_existing and not swap:
        note("--use-existing reuses the handoff already on disk instead of asking "
             "the agent for another one, and that only happens when the session "
             "is replaced: without --swap there is no session to replace. "
             "Nothing was sent or written.")
        return 1
    if use_existing and force:
        note("Use one of --force or --use-existing, not both.")
        return 1

    registry = load_registry()
    config = load_config()
    entries = (registry.get("herdr") or {}).get("tabs") or {}

    if all_roles and role is not None:
        note("Use one role or --all, not both.")
        return 1
    if not all_roles and role is None:
        note(f"Tell me which role. Available: {', '.join(entries)}")
        return 1
    if role is not None and role not in entries:
        note(f"There is no role {role!r} in the registry.")
        return 1

    targets = list(entries.items()) if all_roles else [(role, entries[role])]
    failed = 0
    for key, entry in targets:
        path: Path | None = None
        reused = False
        if use_existing:
            candidate, problems = _existing_handoff(key)
            if candidate is None:
                note(f"{key}: no valid prepared handoff on disk; falling back to "
                     "asking the agent")
            elif problems:
                note(f"{key}: cannot reuse the handoff on disk — "
                     f"{'; '.join(problems)}. Ask for a new handoff: run without "
                     "--use-existing.")
                failed += 1
                if all_roles:
                    note("Stopping here: the other roles were not touched.")
                    break
                continue
            else:
                document = load_handoff(candidate)
                age = handoff_age_text(handoff_age_seconds(candidate, document))
                log(f"{key}: reusing the handoff written {age} ({candidate.name}); "
                    "the agent was not asked for another one")
                path = candidate
                reused = True
        if path is None:
            # Con --swap siempre se vuelve a pedir: se está a punto de perder la
            # sesión, así que el handoff tiene que ser de ahora, no de hace horas.
            if not force and not swap:
                done = _prepared(key)
                if done is not None:
                    log(f"{key}: it already had a valid handoff ({done.name}); skipped")
                    continue
            path, problems = _prepare(key, entry, config, timeout, interval)
            if problems:
                note(f"{key}: invalid handoff — {'; '.join(problems)}")
                failed += 1
                if all_roles:
                    note("Stopping here: the other roles were not touched.")
                    break
                continue
            log(f"{key}: handoff written and validated ({path.name})")
        if not swap:
            continue
        errors = _swap(key, entry, config, registry, timeout, interval, path,
                       # Un documento reutilizado también queda gastado: si no,
                       # un segundo `--use-existing` relevaría otra vez con él.
                       consume=True)
        if errors:
            note(f"{key}: valid handoff, but the swap failed — {'; '.join(errors)}")
            failed += 1
            if all_roles:
                break
        else:
            save_registry(registry)
            log(f"{key}: session replaced, pid={entry['pid']}")

    if swap or failed:
        save_registry(registry)
    return 1 if failed else 0
