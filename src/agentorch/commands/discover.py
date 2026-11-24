"""The discover command: what this project already declares and already runs.

This is the only surface an agent should read. It wraps `herdr-app` and `hc` and
scopes everything to the project, so nothing from another workspace can leak into
an answer: the raw listings span every space on the machine, and mixing them is
how a role from one project ends up attributed to another.
"""

from __future__ import annotations

import json

from .. import project
from ..config import configured_max_tabs
from ..discovery import choose, scan
from ..herdr import (get_spaces, parse_json_output, run_app, space_id,
                     spaces_for_project, terminal_folders)
from ..live import (designate_orchestrator, inspect_space, normalize,
                    proposal_from_live)
from ..output import note


def live_payload(candidates) -> tuple[dict, list]:
    data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    spaces = spaces_for_project(get_spaces(data), str(project.PROJECT_DIR),
                                terminal_folders())
    if not spaces:
        wanted = normalize(project.PROJECT_NAME)
        alike = [s for s in get_spaces(data)
                 if normalize(str(s.get("name") or "")) == wanted]
        return {"space": None, "space_id": None, "tabs": [],
                "main_session": None,
                "hint": (f"existe un space llamado {alike[0].get('name')!r} que "
                         f"apunta a {alike[0].get('folder')}" if alike else None)}, []

    space = spaces[0]
    tabs = inspect_space(space, candidates)
    main = designate_orchestrator(tabs)
    return {
        "space": space.get("name"),
        "space_id": space_id(space),
        "main_session": main.name if main else None,
        "hint": None,
        "tabs": [{
            "tab_id": tab.tab_id,
            "terminal_id": tab.terminal_id,
            "name": tab.name,
            "renamed": tab.renamed,
            "active": tab.active,
            "app": tab.app,
            "status": tab.status,
            "role": tab.candidate.key if tab.candidate else None,
            "is_main": main is not None and tab is main,
        } for tab in tabs],
    }, tabs


def _report(payload: dict) -> None:
    if payload["space"] is None:
        note("No hay ningún space de Herdr para este proyecto"
             + (f"; {payload['hint']}." if payload.get("hint") else "."))
        return
    note(f"Space {payload['space_id']} · {len(payload['tabs'])} tab(s)")
    for tab in payload["tabs"]:
        marks = []
        if tab["is_main"]:
            marks.append("main")
        if tab["active"]:
            marks.append("activa")
        if tab["renamed"]:
            marks.append("renombrada")
        if tab["app"]:
            marks.append(f"agente={tab['app']}")
        if tab["status"]:
            marks.append(tab["status"])
        note(f"  {tab['name']:<26} {', '.join(marks) or '—':<40} "
             f"→ {tab['role'] or 'sin rol detectado'}")
    note(f"Main session: {payload['main_session'] or 'no identificada'}")


def discover(live: bool = False, as_json: bool = False) -> int:
    candidates = scan(project.PROJECT_DIR)
    payload: dict = {"project": {"name": project.PROJECT_NAME,
                                 "path": str(project.PROJECT_DIR)},
                     "live": None, "candidates": [], "proposed": None}

    live_tabs: list = []
    if live:
        payload["live"], live_tabs = live_payload(candidates)
        if not as_json:
            _report(payload["live"])

    if candidates:
        payload["candidates"] = [{
            "key": candidate.key, "name": candidate.name,
            "role": candidate.role, "source": candidate.source,
            "scope": candidate.scope, "path": candidate.path,
        } for candidate in candidates]

    proposal = proposal_from_live(live_tabs, max_tabs=configured_max_tabs()) \
        if live_tabs else []
    if proposal:
        if not as_json:
            note(f"Propuesta a partir de las {len(proposal)} tabs abiertas en Herdr.")
    elif candidates:
        declared = [c for c in candidates if c.scope == "project"]
        if not as_json:
            note(f"Candidatos encontrados: {len(candidates)}")
            if declared:
                note(f"Propuesta a partir de los {len(declared)} agentes "
                     f"declarados en el proyecto.")
            else:
                note("El proyecto no declara agentes: la propuesta usa tu "
                     "configuración de usuario.")
        proposal = choose(declared or candidates, max_tabs=configured_max_tabs())

    if proposal:
        payload["proposed"] = {"pi": {"executable": "pi", "bootstrap": "greet"},
                               "tabs": proposal}

    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if payload["proposed"]:
        print(json.dumps(payload["proposed"], indent=2, ensure_ascii=False))
        return 0

    note("No hay nada de lo que proponer un equipo todavía.")
    return 0
