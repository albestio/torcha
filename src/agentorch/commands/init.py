"""The init command: prepare the workspace and start the Pi sessions."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid

from .. import __version__ as VERSION
from pathlib import Path

from .. import project
from ..bootstrap import pi_argv, write_bootstrap_files
from ..config import DEFAULT_TABS, configured_max_tabs, load_config, write_default_config
from ..discovery import choose, role_name, scan, slug
from ..errors import AgentorchError
from ..git import ensure_git_repo
from ..herdr import (extract_tab_ids, first_string, get_spaces, parse_json_output,
                     own_terminal, tab_of_terminal,
                     run_app, space_id, spaces_for_project, tab_app, tab_id,
                     tab_name, tabs_of, terminal_folders, terminal_pid,
                     wait_for_apps)
from ..live import (inspect_space, names_the_role, proposal_from_live,
                    role_tabs, skeleton_from_live)
from ..commands.discover import live_payload
from ..output import error, log, note
from ..registry import registry_template, save_registry, timestamp, write_json_atomic

def initial_tabs(candidates) -> tuple[list[dict[str, str]], str]:
    """Decide the tabs of a brand-new agents.json, in order of evidence.

    1. Named tabs where an agent is running: the team in use, the one that will
       carry handoffs. Declared roles in files are a catalogue, not the shift.
    2. Roles the project declares in files.
    3. The built-in default team.
    """
    try:
        data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    except AgentorchError:
        data = None
    if data is not None:
        spaces = spaces_for_project(get_spaces(data), str(project.PROJECT_DIR),
                                    terminal_folders())
        for space in spaces:
            tabs = proposal_from_live(inspect_space(space, candidates),
                                      max_tabs=configured_max_tabs())
            if tabs:
                return tabs, "tabs abiertas con nombre"
    if candidates:
        return choose(candidates, max_tabs=configured_max_tabs()), "agentes declarados en el proyecto"
    return [dict(tab) for tab in DEFAULT_TABS], "equipo por defecto"


def match_tab_entry(label: str, tabs: list[dict], claimed: set[str]):
    """Find the Herdr tab for a configured label: by name first, then by role.

    Without the second step, a config seeded from the live workspace with role
    names would not recognise a tab called "Lead" and would create a duplicate,
    losing the session the human wanted to keep.
    """
    for candidate in tabs:
        if (tab_id(candidate) or "") in claimed:
            continue
        if (tab_name(candidate) or "").casefold() == label.casefold():
            return candidate
    wanted = slug(role_name(label))
    for candidate in tabs:
        if (tab_id(candidate) or "") in claimed:
            continue
        tab_label = tab_name(candidate) or ""
        if wanted == "orchestrator" and names_the_role(tab_label):
            return candidate
        if slug(role_name(tab_label)) == wanted:
            return candidate
    return None


SETUP_SKILL = Path(__file__).resolve().parent.parent / "skills" / "setup" / "SKILL.md"


def proposed_sessions() -> dict[str, str]:
    """Session ids the interview collected. Ignored if absent; validated if not."""
    path = project.AGENTORCH_DIR / "proposals" / "sessions.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        note(f"No se pudo leer {path}: se ignora y las sesiones no se reanudarán.")
        return {}
    if not isinstance(data, dict):
        return {}
    result = {}
    for key, value in data.items():
        try:
            uuid.UUID(str(value))
        except ValueError:
            note(f"session_id inválido para {key!r}: se ignora.")
            continue
        result[str(key)] = str(value)
    return result


def unfilled_roles() -> list[str]:
    """Keys whose role is still empty. Reads the raw file: load_config() falls

    back to the name, which would hide an unfinished interview.
    """
    if not project.CONFIG_FILE.exists():
        return []
    try:
        data = json.loads(project.CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    tabs = data.get("tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return []
    return [str(tab.get("key")) for tab in tabs
            if isinstance(tab, dict) and not str(tab.get("role") or "").strip()]


def _interview_prompt(skeleton: list[dict[str, str]], payload: dict) -> str:
    """The project-specific data; the procedure lives in the setup skill."""
    live = {tab.get("name"): tab for tab in payload.get("tabs") or []}
    lines = [
        f"# Agentorch setup — {project.PROJECT_NAME}",
        "",
        f"Project: `{project.PROJECT_DIR}` · space `{payload.get('space')}`.",
        "",
        f"`{project.CONFIG_FILE}` already exists with these tabs, in this order:",
        "",
        "| key | name | tab_id | terminal | app | state |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for tab in skeleton:
        entry = live.get(tab["name"], {})
        lines.append(f"| `{tab['key']}` | {tab['name']} | "
                     f"`{entry.get('tab_id') or '?'}` | "
                     f"`{entry.get('terminal_id') or '?'}` | "
                     f"{entry.get('app') or '—'} | {entry.get('status') or '—'} |")
    lines += [
        "",
        "Every `role` and `instructions` is empty. Fill them from what each agent",
        "tells you, following the setup skill. Do not touch keys, names or order.",
        "",
    ]
    return "\n".join(lines)


def _own_tab() -> dict | None:
    """The tab this process runs in, or None when it cannot be identified."""
    terminal = own_terminal()
    if terminal is None:
        return None
    return tab_of_terminal(terminal)


def _mark_setup_tab(tab: dict | None, team_tab_ids: set[str]) -> None:
    """Name the tab running the interview, so it is findable while debugging.

    Never a team tab: renaming one would destroy the role's name, which is what
    lets agentorch adopt it later.
    """
    if tab is None:
        return
    identifier = tab_id(tab)
    if not identifier or identifier in team_tab_ids:
        return
    if tab_name(tab) == "Agentorch":
        return
    try:
        run_app(["do", "tab.rename", "--id", identifier, "--name", "Agentorch"])
        log("Tab renombrada a 'Agentorch' para poder identificarla al depurar.")
    except AgentorchError as exc:
        note(f"No se pudo renombrar la tab de la entrevista: {exc}")


def _run_interview(path: Path, executable: str) -> int:
    """Run the setup session in this same terminal, as a child.

    The procedure and the conventions travel in the setup skill, loaded from this
    package: nothing has to exist in the target project for it to work.
    """
    command = [executable]
    if SETUP_SKILL.is_file():
        command += ["--skill", str(SETUP_SKILL)]
    command.append(f"@{path}")
    return subprocess.run(command, cwd=project.PROJECT_DIR, check=False).returncode


def start_interview(candidates) -> bool:
    """Hand the setup to a Pi session. True when it produced a config."""
    payload, live_tabs = live_payload(candidates)
    if not payload.get("tabs"):
        return False
    # Solo las tabs que son roles. Una tab suelta del space (la que el usuario
    # abre para lanzar init) no lo es, y tratarla como tal impedía renombrarla.
    team_tab_ids = {tab.tab_id for tab in role_tabs(live_tabs) if tab.tab_id}
    # La tab que ejecuta init tampoco es un rol: es el terminal del setup, así
    # que se identifica antes de decidir el esqueleto y se queda fuera de él.
    own_tab = _own_tab()
    own_tab_id = tab_id(own_tab) if own_tab else None

    if own_tab_id and own_tab_id in team_tab_ids:
        note("Estás lanzando init en la tab de un rol del equipo: la entrevista "
             "ocupará un panel de esa tab y habrá dos sesiones con la misma "
             "etiqueta. Mejor ejecútalo desde una tab que no sea del equipo.")

    directory = project.AGENTORCH_DIR
    directory.mkdir(parents=True, exist_ok=True)
    if not project.CONFIG_FILE.exists():
        tabs = skeleton_from_live(live_tabs, max_tabs=configured_max_tabs(),
                                  own_tab_id=own_tab_id)
        if not tabs:
            return False
        write_default_config(tabs)
        log(f"Esqueleto de configuración creado: {project.CONFIG_FILE}")
    skeleton_tabs = json.loads(
        project.CONFIG_FILE.read_text(encoding="utf-8")).get("tabs") or []
    path = directory / "interview.md"
    path.write_text(_interview_prompt(skeleton_tabs, payload), encoding="utf-8")
    executable = "pi"
    try:
        executable = load_config_default_executable()
    except AgentorchError:
        pass
    from shutil import which
    if which(executable) is None:
        note(f"No se encuentra '{executable}' en PATH: no se puede abrir la entrevista.")
        return False

    _mark_setup_tab(own_tab, team_tab_ids)

    log(f"Abriendo la entrevista de configuración con {executable}…")
    code = _run_interview(path, executable)
    pending = unfilled_roles()
    if pending:
        note(f"La entrevista cerró (código {code}) sin rellenar: "
             f"{', '.join(pending)}")
        return False
    return True


def load_config_default_executable() -> str:
    """The configured pi executable without requiring a full config."""
    try:
        return json.loads(project.CONFIG_FILE.read_text(encoding="utf-8")) \
            .get("pi", {}).get("executable", "pi")
    except (OSError, json.JSONDecodeError, AttributeError):
        return "pi"


def init(plain: bool = False) -> int:
    log(f"Agentorch v{VERSION}")
    log(f"Proyecto: {project.PROJECT_NAME}")
    log(f"Directorio: {project.PROJECT_DIR}")

    # Precondición más barata primero: sin repositorio no se escribe nada, no se
    # crea ningún space y no se arranca ningún agente.
    ensure_git_repo()

    from shutil import which
    if which("herdr-app") is None:
        raise AgentorchError("No se encuentra 'herdr-app' en PATH.")
    candidates = scan(project.PROJECT_DIR, scope="project")
    interviewed_sessions = proposed_sessions()
    pending = unfilled_roles()
    if (not project.CONFIG_FILE.exists() or pending) and not plain \
            and sys.stdin.isatty() and sys.stdout.isatty():
        start_interview(candidates)
        pending = unfilled_roles()
        # La entrevista acaba de escribir las propuestas: hay que releerlas.
        interviewed_sessions = proposed_sessions()

    if not project.CONFIG_FILE.exists():
        tabs, origin = initial_tabs(candidates)
        write_default_config(tabs)
        log(f"Configuración creada desde {origin}: {project.CONFIG_FILE}")
    elif pending:
        note(f"La entrevista dejó sin rellenar: {', '.join(pending)}. "
             "No se aplicó nada; vuelve a ejecutar 'agentorch init'.")
        return 1
    else:
        log(f"Configuración lista: {project.CONFIG_FILE}")
    config = load_config()
    tabs_config = config["tabs"]
    project.AGENTORCH_DIR.mkdir(parents=True, exist_ok=True)
    registry = registry_template(tabs_config)
    persisted = False
    created_session: dict[str, str] = {}

    try:
        mode = config["pi"]["bootstrap"]
        if mode == "none":
            log("Bootstrap desactivado (pi.bootstrap=none): Pi arranca sin prompt.")
        else:
            write_bootstrap_files(tabs_config, mode)
            log(f"Prompts de arranque preparados en {project.BOOTSTRAP_DIR} (modo {mode})")
        # 1. Inspeccionar la ventana en ejecución y localizar el space por carpeta.
        log("Consultando spaces existentes en Herdr...")
        ls_output = run_app(["ls"])
        try:
            ls_data = parse_json_output(ls_output, "herdr-app ls")
        except AgentorchError:
            write_json_atomic(project.AGENTORCH_DIR / "last-ls.json",
                              {"stdout": ls_output, "saved_at": timestamp()})
            raise
        spaces = get_spaces(ls_data)
        matches = spaces_for_project(spaces, str(project.PROJECT_DIR),
                                     terminal_folders())

        if len(matches) > 1:
            ids = [space_id(s) for s in matches]
            raise AgentorchError(
                f"Hay varios spaces asociados a {project.PROJECT_DIR}: {ids}. "
                "No se modificó ninguno; resuelve el duplicado manualmente."
            )

        if matches:
            space = matches[0]
            sid = space_id(space)
            if not sid:
                raise AgentorchError("Se encontró el space del proyecto, pero no se pudo extraer su ID.")
            log(f"Space existente recuperado: {sid}")
        else:
            # 2. Crear el space con la primera tab (Orquestador).
            log("No existe un space asociado a esta carpeta. Creándolo...")
            space_args = [
                "do", "space.new", "--name", project.PROJECT_NAME,
                "--folder", str(project.PROJECT_DIR),
                "--tab", tabs_config[0]["name"],
                "--focus", "true",
            ]
            session_id = str(uuid.uuid4())
            argv = pi_argv(config, tabs_config[0], session_id)
            if argv:
                created_session[tabs_config[0]["key"]] = session_id
                space_args += ["--argv", json.dumps(argv)]
            output = run_app(space_args)
            created = parse_json_output(output, "space.new")
            sid = first_string(created, "space", "space_id", "id")
            if not sid:
                raise AgentorchError(f"space.new no devolvió un ID de space: {output}")
            log(f"Space creado: {sid}")

        registry["herdr"]["space_id"] = sid
        save_registry(registry)
        persisted = True

        # 3. Releer el estado antes de crear tabs para evitar duplicados.
        ls_data = parse_json_output(run_app(["ls"]), "herdr-app ls")
        current_spaces = get_spaces(ls_data)
        current = next((s for s in current_spaces if space_id(s) == sid), None)
        if current is None:
            raise AgentorchError(f"El space {sid} no aparece en la segunda consulta 'ls'.")
        current_tabs = tabs_of(current)
        claimed: set[str] = set()

        # 4. Crear solo las tabs ausentes, arrancando Pi en cada una.
        created: list[str] = []
        for index, item in enumerate(tabs_config):
            key, name = item["key"], item["name"]
            found = match_tab_entry(name, current_tabs, claimed)
            if found is not None:
                claimed.add(tab_id(found) or "")
                log(f"Tab existente recuperada: {name}")
                continue
            # La primera tab se crea junto con el space.new.
            if index == 0 and not matches:
                continue
            log(f"Creando tab: {name}")
            tab_args = [
                "do", "tab.new", "--name", name, "--space", sid,
                "--folder", str(project.PROJECT_DIR), "--focus", "false",
            ]
            session_id = str(uuid.uuid4())
            argv = pi_argv(config, item, session_id)
            if argv:
                created_session[key] = session_id
                tab_args += ["--argv", json.dumps(argv)]
            parse_json_output(run_app(tab_args), f"tab.new ({name})")
            created.append(key)

        # 5. Obtener IDs definitivos (tab, terminal y pane) desde ls, esperando
        #    solo a las tabs en las que se acaba de arrancar Pi.
        started = list(created)
        if not matches:
            started.insert(0, tabs_config[0]["key"])
        expected = [t["name"] for t in tabs_config if t["key"] in started]
        final_space, pending = wait_for_apps(sid, expected)
        final_tabs = tabs_of(final_space)
        if pending:
            log(f"Sin aplicación detectada todavía en: {', '.join(pending)}")

        claimed = set()
        for item in tabs_config:
            name, key = item["name"], item["key"]
            tab = match_tab_entry(name, final_tabs, claimed)
            if tab is None:
                raise AgentorchError(f"La tab '{name}' no aparece en el estado final de Herdr.")
            claimed.add(tab_id(tab) or "")
            tid = tab_id(tab)
            ids = extract_tab_ids(tab)
            if not tid:
                raise AgentorchError(f"No se pudo recuperar tab_id para '{name}'.")
            app = tab_app(tab)
            # Only an agent has a pid worth recording: on a bare shell the
            # foreground pid is the shell itself and identifies no role.
            pid = terminal_pid(ids["terminal_id"]) if app and ids["terminal_id"] else None
            registry["herdr"]["tabs"][key].update({
                "tab_id": tid,
                "terminal_id": ids["terminal_id"],
                "pane_id": ids["pane_id"],
                "app": app,
                "pid": pid,
                "session_id": created_session.get(key) or interviewed_sessions.get(key),
            })
            save_registry(registry)
            log(f"{name}: tab={tid}, terminal={ids['terminal_id']}, "
                f"pane={ids['pane_id']}, app={app}, pid={pid}")

        # 6. Dejar el foco en la primera tab configurada (tabs[0]) y devolverla a
        #    la posición 1 si Herdr la hubiera recreado al final.
        orchestrator = tabs_config[0]
        orchestrator_tab = registry["herdr"]["tabs"][orchestrator["key"]]["tab_id"]
        ordered = [tab_id(t) for t in tabs_of(final_space)]
        if orchestrator_tab in ordered and ordered.index(orchestrator_tab) != 0:
            position = ordered.index(orchestrator_tab) + 1
            run_app(["do", "tab.move", "--id", orchestrator_tab, "--index", "1"])
            log(f"Orquestador movido de la posición {position} a la 1")
        run_app(["do", "space.select", "--id", sid])
        run_app(["do", "tab.select", "--id", orchestrator_tab])
        log(f"Foco en {orchestrator['name']} ({orchestrator_tab})")

        registry["status"] = "ready"
        registry["error"] = None
        save_registry(registry)
        log("Inicialización y reconciliación completadas.")
        log(f"Tabs verificadas: {len(tabs_config)}")
        log(f"Registry: {project.REGISTRY_FILE}")
        if config["pi"]["bootstrap"] == "none":
            log("Arranque Pi sin prompt de arranque (pi.bootstrap=none).")
        elif started:
            log(f"Pi arrancado en {len(started)} tab(s): {', '.join(started)}")
        else:
            log("Ninguna tab nueva: no se arrancó ninguna sesión Pi.")
        return 0

    except Exception as exc:
        registry["status"] = "partial"
        registry["error"] = str(exc)
        # Only overwrite a previous registry once this run got far enough to have
        # something worth recording. A failure before that must not erase it.
        if persisted:
            save_registry(registry)
        error(str(exc))
        error(f"Consulta el diagnóstico y registry en: {project.AGENTORCH_DIR}")
        return 1
