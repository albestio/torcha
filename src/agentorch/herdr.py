"""Adapter for the herdr-app CLI and parser for its output."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from shutil import which
from typing import Any

from . import project
from .errors import AgentorchError
from .output import log, note

def run_app(args: list[str], *, allow_error: bool = False) -> str:
    command = ["herdr-app", *args]
    note(f"Running: {' '.join(command)}")
    result = subprocess.run(command, cwd=project.PROJECT_DIR, text=True,
                            capture_output=True, check=False)
    if result.returncode and not allow_error:
        detail = (result.stderr or result.stdout).strip()
        raise AgentorchError(
            f"herdr-app returned code {result.returncode}: "
            f"{' '.join(command)}" + (f"\n{detail}" if detail else "")
        )
    return result.stdout.strip()

SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}


def run_hc(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["hc", *args], text=True, capture_output=True, check=False)


def terminal_info(terminal: str) -> dict[str, Any] | None:
    """Everything herdr-core reports about one terminal, or None."""
    try:
        result = run_hc(["get", terminal])
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def foreground_argv(terminal: str) -> list[str]:
    """The argv of the program in the terminal's foreground."""
    data = terminal_info(terminal) or {}
    foreground = data.get("foreground")
    argv = foreground.get("argv") if isinstance(foreground, dict) else None
    if not isinstance(argv, list):
        return []
    return [str(part) for part in argv]


def terminal_pid(terminal: str) -> int | None:
    """The PID of the program running in a terminal, via herdr-core.

    `herdr-app` cannot report it. Returns None when herdr-core is unavailable or
    the terminal has no foreground program: the registry stays useful without it,
    so this never fails the command.
    """
    data = terminal_info(terminal) or {}
    foreground = data.get("foreground")
    if not isinstance(foreground, dict):
        return None
    pid = foreground.get("pid")
    return pid if isinstance(pid, int) else None


def is_shell(terminal: str) -> bool:
    """True when the terminal's foreground is an interactive shell.

    `app` being empty is not enough: a program that reports nothing over OSC 7501
    looks identical, and sending text into it would type into live work.
    """
    argv = foreground_argv(terminal)
    return bool(argv) and os.path.basename(argv[0]) in SHELLS


def agent_state(terminal: str) -> str | None:
    """What the program reports over OSC 7501: working, done, idle, blocked."""
    data = terminal_info(terminal) or {}
    status = data.get("status")
    if not isinstance(status, dict):
        return None
    state = status.get("state")
    return state if isinstance(state, str) else None


def agent_running(terminal: str, executable: str) -> bool:
    """True when the terminal's foreground is the configured agent."""
    argv = foreground_argv(terminal)
    if not argv:
        return False
    return os.path.basename(argv[0]) == os.path.basename(executable)


def terminals_of_space(space_name: str) -> list[str]:
    """Every terminal in that space, including panes with no agent.

    `herdr-app ls` gives one tab per role, but a tab can hold several panes and a
    setup session can end up as the second one. `where` is "space / tab".
    """
    try:
        result = run_hc(["ls"])
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    terminals = data.get("terminals") if isinstance(data, dict) else None
    if not isinstance(terminals, list):
        return []
    prefix = f"{space_name} /"
    return [str(item["address"]) for item in terminals
            if isinstance(item, dict) and str(item.get("where") or "").startswith(prefix)]


def send_keys(terminal: str, *keys: str) -> bool:
    """Press keys in a terminal. `ctrl+d` closes the program in front, not the tab.

    `hc kill` ends the terminal's own program —the shell— which takes the whole
    tab with it. These keys close only the agent, and the shell comes back.
    """
    try:
        result = run_hc(["keys", terminal, *keys])
    except FileNotFoundError:
        return False
    return result.returncode == 0


def wait_for_agent(terminal: str, executable: str, timeout: float = 60.0,
                   interval: float = 1.0) -> bool:
    """Wait until the terminal's foreground is the configured agent."""
    deadline = time.monotonic() + timeout
    while True:
        if agent_running(terminal, executable):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def send_text(terminal: str, text: str) -> bool:
    try:
        result = run_hc(["send", terminal, text])
    except FileNotFoundError:
        return False
    return result.returncode == 0


def parse_json_output(output: str, operation: str) -> Any:
    # Algunas versiones pueden añadir mensajes antes/después del objeto JSON.
    decoder = json.JSONDecoder()
    for index, char in enumerate(output):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
            return value
        except json.JSONDecodeError:
            continue
    raise AgentorchError(
        f"Could not parse the output of '{operation}' as JSON. "
        f"Output received:\n{output[:3000]}"
    )

def first_string(obj: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None

def objects_with_key(value: Any, wanted: str):
    """Recorre el árbol JSON y devuelve objetos cuyo campo coincide."""
    if isinstance(value, dict):
        if wanted in value:
            yield value
        for child in value.values():
            yield from objects_with_key(child, wanted)
    elif isinstance(value, list):
        for child in value:
            yield from objects_with_key(child, wanted)

def get_spaces(ls_data: Any) -> list[dict[str, Any]]:
    if isinstance(ls_data, dict):
        for obj in objects_with_key(ls_data, "spaces"):
            spaces = obj.get("spaces")
            if isinstance(spaces, list):
                return [x for x in spaces if isinstance(x, dict)]
    # Formato alternativo: el array raíz contiene los spaces.
    if isinstance(ls_data, list):
        return [x for x in ls_data if isinstance(x, dict)
                and any(k in x for k in ("tabs", "folder", "path"))]
    raise AgentorchError(
        "The output of 'herdr-app ls' does not contain a recognisable list of spaces. "
        "The output was saved to .agentorch/last-ls.json."
    )

def space_id(space: dict[str, Any]) -> str | None:
    return first_string(space, "id", "space_id", "space")


def _parent_pid(pid: int) -> int | None:
    result = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], text=True,
                            capture_output=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def ancestor_pids() -> set[int]:
    """This process and every parent up to init."""
    pids: set[int] = set()
    pid = os.getpid()
    while pid and pid > 1 and pid not in pids:
        pids.add(pid)
        pid = _parent_pid(pid)
    return pids


def own_terminal() -> str | None:
    """The terminal this process runs in, if it can be identified.

    herdr-core reports no pid in `ls`, so candidates are narrowed by cwd first and
    only those are asked for their foreground pid.
    """
    ancestors = ancestor_pids()
    try:
        result = run_hc(["ls"])
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    terminals = data.get("terminals") if isinstance(data, dict) else None
    if not isinstance(terminals, list):
        return None
    here = str(project.PROJECT_DIR)
    for terminal in terminals:
        if not isinstance(terminal, dict) or terminal.get("cwd") != here:
            continue
        address = terminal.get("address")
        if isinstance(address, str) and terminal_pid(address) in ancestors:
            return address
    return None


def tab_of_terminal(terminal_id: str) -> dict[str, Any] | None:
    """The tab holding that terminal, from a fresh listing."""
    data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    for space in get_spaces(data):
        for tab in tabs_of(space):
            for terminal in tab.get("terminals") or []:
                if isinstance(terminal, dict) and terminal.get("terminal") == terminal_id:
                    return tab
    return None


def runs_inside(terminal: str) -> bool:
    """Whether this process is a descendant of the program in that terminal.

    Replacing a session from inside that same session kills the executor halfway
    through the swap, leaving a terminal with no agent and no way to report it.
    """
    target = terminal_pid(terminal)
    if target is None:
        return False
    return target in ancestor_pids()


def _parse_terminal_index(output: str) -> dict[str, str] | None:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    terminals = data.get("terminals") if isinstance(data, dict) else None
    if not isinstance(terminals, list):
        return None
    folders: dict[str, str] = {}
    for terminal in terminals:
        if not isinstance(terminal, dict):
            continue
        address, cwd = terminal.get("address"), terminal.get("cwd")
        if isinstance(address, str) and isinstance(cwd, str) and cwd:
            folders[address] = cwd
    return folders


def core_report() -> tuple[bool, str]:
    """Whether herdr-core answers, and what it reports. Never starts it.

    A diagnostic reports; it does not fix. Starting the core is `init`'s job.
    """
    result = subprocess.run(["hc", "ls"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, "does not answer" + (f": {detail}" if detail else "")
    index = _parse_terminal_index(result.stdout)
    if index is None:
        return False, "answered something that is not a list of terminals"
    return True, f"{len(index)} live terminal(s)"


def terminal_folders() -> dict[str, str]:
    """address -> cwd of every live terminal, from herdr-core.

    `herdr-app ls` reports a space's `folder`, but its own type definition says
    that is *where its new terminals start*, not where its terminals are: it is
    inherited from whichever terminal was focused at creation, so it often names
    another project. The cwd is the only reliable answer and only herdr-core has
    it, so this raises instead of guessing.

    Starts the core once when it does not answer: a stopped core is the usual
    reason, and `hc server start` is the documented way back.
    """
    if which("hc") is None:
        raise AgentorchError("'hc' (herdr-core) is not on PATH.")

    result = subprocess.run(["hc", "ls"], text=True, capture_output=True, check=False)
    if result.returncode == 0:
        index = _parse_terminal_index(result.stdout)
        if index is not None:
            return index

    note("herdr-core does not answer; trying to start it…")
    start = subprocess.run(["hc", "server", "start"], text=True,
                           capture_output=True, check=False)
    if start.returncode != 0:
        detail = (start.stderr or start.stdout).strip()
        raise AgentorchError("herdr-core does not answer and could not be started."
                             + (f"\n{detail}" if detail else ""))

    result = subprocess.run(["hc", "ls"], text=True, capture_output=True, check=False)
    index = _parse_terminal_index(result.stdout) if result.returncode == 0 else None
    if index is None:
        detail = (result.stderr or result.stdout).strip()
        raise AgentorchError("herdr-core started but does not answer 'hc ls'."
                             + (f"\n{detail}" if detail else ""))
    note(f"herdr-core started: {len(index)} live terminal(s).")
    return index


def _inside(path: str, project: str) -> bool:
    return path.startswith(project.rstrip(os.sep) + os.sep)


def space_match(space: dict[str, Any], project_dir: str,
                folders: dict[str, str]) -> str | None:
    """How a space relates to the project: "exact", "inside" or None.

    Judged only by where its live terminals work. A space whose terminals are all
    gone cannot be placed, and is treated as not this project's: adopting a
    stale space of unknown origin is worse than creating a fresh one.
    """
    inside = False
    for tab in tabs_of(space):
        for terminal in tab.get("terminals") or []:
            if not isinstance(terminal, dict):
                continue
            cwd = folders.get(terminal.get("terminal") or "")
            if not cwd:
                continue
            if cwd == project_dir:
                return "exact"
            if _inside(cwd, project_dir):
                inside = True
    return "inside" if inside else None


def spaces_for_project(spaces: list[dict[str, Any]], project_dir: str,
                       folders: dict[str, str]) -> list[dict[str, Any]]:
    """The spaces of a project: exact matches win, subfolders only as a fallback."""
    exact: list[dict[str, Any]] = []
    inside: list[dict[str, Any]] = []
    for space in spaces:
        kind = space_match(space, project_dir, folders)
        if kind == "exact":
            exact.append(space)
        elif kind == "inside":
            inside.append(space)
    return exact or inside

def tabs_of(space: dict[str, Any]) -> list[dict[str, Any]]:
    tabs = space.get("tabs")
    if isinstance(tabs, list):
        return [t for t in tabs if isinstance(t, dict)]
    return []

def tab_name(tab: dict[str, Any]) -> str | None:
    return first_string(tab, "name", "label", "title")

def tab_id(tab: dict[str, Any]) -> str | None:
    return first_string(tab, "id", "tab_id")

def extract_tab_ids(tab: dict[str, Any]) -> dict[str, str | None]:
    pane = terminal = None
    # Algunas versiones exponen pane_id directamente; otras usan panes[].id.
    for obj in objects_with_key(tab, "pane_id"):
        value = obj.get("pane_id")
        if isinstance(value, str) and value:
            pane = value
            break
    if pane is None:
        for obj in objects_with_key(tab, "panes"):
            values = obj.get("panes")
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        pane = first_string(item, "pane_id", "id")
                        if pane:
                            break
            if pane:
                break
    if pane is None:
        for obj in objects_with_key(tab, "terminals"):
            values = obj.get("terminals")
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        pane = first_string(item, "pane", "pane_id")
                        if pane:
                            break
            if pane:
                break
    for obj in objects_with_key(tab, "terminal_id"):
        value = obj.get("terminal_id")
        if isinstance(value, str) and value:
            terminal = value
            break
    if terminal is None:
        for obj in objects_with_key(tab, "terminal"):
            value = obj.get("terminal")
            if isinstance(value, str) and value:
                terminal = value
            elif isinstance(value, dict):
                terminal = first_string(value, "terminal_id", "id")
            if terminal:
                break
    if terminal is None:
        for obj in objects_with_key(tab, "terminals"):
            values = obj.get("terminals")
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        terminal = first_string(item, "terminal_id", "id")
                        if terminal:
                            break
            if terminal:
                break
    return {"terminal_id": terminal, "pane_id": pane}

def tab_app(tab: dict[str, Any]) -> str | None:
    """Aplicación que Herdr detecta en el terminal de la tab (p. ej. "pi")."""
    for obj in objects_with_key(tab, "terminals"):
        values = obj.get("terminals")
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    app = first_string(item, "app")
                    if app:
                        return app
    return None

def wait_for_apps(space: str, names: list[str], timeout: float = 20.0,
                  interval: float = 2.0) -> tuple[dict[str, Any], list[str]]:
    """Espera a que Herdr detecte una aplicación en cada tab esperada.

    Herdr descubre la aplicación por los informes OSC 7501 del programa, así que
    justo después de crear una tab el campo `app` todavía es nulo.
    """
    deadline = time.monotonic() + timeout
    while True:
        data = parse_json_output(run_app(["ls"]), "herdr-app ls")
        found = next((s for s in get_spaces(data) if space_id(s) == space), None)
        if found is None:
            raise AgentorchError(
                f"Could not verify space {space} after creating the tabs.")
        tabs = {(tab_name(t) or "").casefold(): t for t in tabs_of(found)}
        pending = [n for n in names if not tab_app(tabs.get(n.casefold(), {}))]
        if not pending or time.monotonic() >= deadline:
            return found, pending
        log(f"Waiting for Pi to start: {len(names) - len(pending)}/{len(names)}")
        time.sleep(interval)
