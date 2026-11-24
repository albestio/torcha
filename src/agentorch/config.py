"""Project configuration: loading and validation of agents.json."""

from __future__ import annotations

import json
import re
from typing import Any

from . import project
from .errors import AgentorchError
from .registry import write_json_atomic

PI_DEFAULT = "pi"
MAX_TABS = 10
"""Tope de tabs del equipo cuando el proyecto no fija el suyo en 'max_tabs'."""


def _instructions(key: str, value: Any) -> str:
    """Per-role instructions as one text block.

    A JSON array is accepted and joined: rejecting it silently would drop every
    rule an agent wrote, which is exactly the failure this function exists to
    stop. Anything else that is not text is an error, not an empty string.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines = [str(part).strip() for part in value if str(part).strip()]
        return "\n".join(lines)
    raise AgentorchError(
        f"'instructions' de {key!r} debe ser texto o una lista de textos, "
        f"no {type(value).__name__}")

DEFAULT_TABS = [
    {"key": "orchestrator", "name": "Orchestrator",
     "role": "Coordinates the team, assigns work and verifies results."},
    {"key": "worker_1", "name": "Worker 1",
     "role": "Research and code exploration."},
    {"key": "worker_2", "name": "Worker 2", "role": "Implementation of changes."},
    {"key": "worker_3", "name": "Worker 3", "role": "Review and quality audit."},
    {"key": "worker_4", "name": "Worker 4",
     "role": "Testing and functional verification."},
]

def write_default_config(tabs: list[dict[str, str]]) -> None:
    """Write the initial agents.json with the tabs the caller decided on."""
    write_json_atomic(project.CONFIG_FILE, {
        "pi": {"executable": PI_DEFAULT, "bootstrap": "greet"},
        "max_tabs": MAX_TABS,
        "tabs": tabs,
    })

BOOTSTRAP_MODES = ("none", "greet", "recover")

def parse_bootstrap(value: Any) -> str:
    """Modo de arranque de Pi: none, greet o recover (true/false por compatibilidad)."""
    if isinstance(value, bool):
        return "greet" if value else "none"
    if isinstance(value, str) and value.strip().lower() in BOOTSTRAP_MODES:
        return value.strip().lower()
    raise AgentorchError(
        f"'pi.bootstrap' debe ser uno de {BOOTSTRAP_MODES}, o true/false: {value!r}")

def parse_max_tabs(value: Any) -> int:
    """Tope de tabs del equipo: un entero positivo, como se escribe 'max_tabs'."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AgentorchError(
            f"'max_tabs' debe ser un entero positivo "
            f"(por defecto {MAX_TABS}): {value!r}")
    return value


def configured_max_tabs() -> int:
    """El tope que fija el proyecto, o el de por defecto si no hay configuración.

    `init` construye el esqueleto *antes* de escribir agents.json, así que la
    ausencia del fichero no es un error: solo se lee el valor si ya existe uno,
    y uno inválido se rechaza en vez de ignorarse.
    """
    if not project.CONFIG_FILE.exists():
        return MAX_TABS
    try:
        raw = json.loads(project.CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentorchError(
            f"No se pudo leer {project.CONFIG_FILE}: {exc}") from exc
    if not isinstance(raw, dict) or "max_tabs" not in raw:
        return MAX_TABS
    return parse_max_tabs(raw["max_tabs"])


def load_config() -> dict[str, Any]:
    if not project.CONFIG_FILE.exists():
        raise AgentorchError(f"No existe el archivo de configuración: {project.CONFIG_FILE}")
    try:
        raw = json.loads(project.CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentorchError(f"No se pudo leer {project.CONFIG_FILE}: {exc}") from exc

    executable, bootstrap = PI_DEFAULT, "greet"
    max_tabs = MAX_TABS
    if isinstance(raw, dict) and "max_tabs" in raw:
        max_tabs = parse_max_tabs(raw["max_tabs"])
    pi_raw = raw.get("pi") if isinstance(raw, dict) else None
    if isinstance(pi_raw, dict):
        value = pi_raw.get("executable")
        if isinstance(value, str) and value.strip():
            executable = value.strip()
        if "bootstrap" in pi_raw:
            bootstrap = parse_bootstrap(pi_raw["bootstrap"])
    if any(char.isspace() for char in executable):
        raise AgentorchError(
            f"'pi.executable' debe ser un único ejecutable, sin argumentos: {executable!r}")

    tabs = raw.get("tabs") if isinstance(raw, dict) else None
    if not isinstance(tabs, list) or not tabs:
        raise AgentorchError("agents.json debe contener una lista no vacía en 'tabs'.")

    result: list[dict[str, str]] = []
    keys, names = set(), set()
    for item in tabs:
        if not isinstance(item, dict):
            raise AgentorchError("Cada elemento de 'tabs' debe ser un objeto.")
        key, name = item.get("key"), item.get("name")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise AgentorchError(f"Clave de tab no válida: {key!r}")
        if not isinstance(name, str) or not name.strip():
            raise AgentorchError(f"Nombre de tab no válido para {key!r}.")
        if key in keys or name.casefold() in names:
            raise AgentorchError(f"Clave o nombre de tab duplicado: {key!r} / {name!r}")
        keys.add(key)
        names.add(name.casefold())
        role = item.get("role")
        instructions = _instructions(key, item.get("instructions"))
        result.append({
            "key": key,
            "name": name.strip(),
            "role": role.strip() if isinstance(role, str) and role.strip() else name.strip(),
            "instructions": instructions,
        })

    if result[0]["key"] != "orchestrator":
        raise AgentorchError("La primera tab debe tener key='orchestrator'.")
    return {"tabs": result, "max_tabs": max_tabs,
            "pi": {"executable": executable, "bootstrap": bootstrap}}
