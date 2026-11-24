"""Project registry: template, atomic write and persistence."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__ as VERSION
from . import project
from .errors import AgentorchError

def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                     dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise

def registry_template(tabs: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "status": "initializing",
        "project": {"name": project.PROJECT_NAME, "path": str(project.PROJECT_DIR)},
        "herdr": {"space_id": None, "tabs": {
            item["key"]: {
                "name": item["name"], "tab_id": None,
                "terminal_id": None, "pane_id": None, "app": None, "pid": None,
                "session_id": None
            } for item in tabs
        }},
        "updated_at": timestamp(),
        "error": None,
    }

def save_registry(registry: dict[str, Any]) -> None:
    registry["updated_at"] = timestamp()
    write_json_atomic(project.REGISTRY_FILE, registry)


def load_registry() -> dict[str, Any]:
    """Read the registry, or fail with the reason it cannot be read."""
    if not project.REGISTRY_FILE.exists():
        raise AgentorchError(
            f"No existe el registro: {project.REGISTRY_FILE}. Ejecuta 'agentorch init'.")
    try:
        data = json.loads(project.REGISTRY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentorchError(
            f"No se pudo leer {project.REGISTRY_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentorchError(f"El registro no es un objeto JSON: {project.REGISTRY_FILE}")
    return data
