"""Resolved paths of the target project.

The path globals live here and are reassigned by `configure_project()`. Other
modules must read them as `project.PROJECT_DIR` and never import the value
directly: a `from .project import PROJECT_DIR` would freeze it at import time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import TorchaError

PROJECT_DIR = Path.cwd().resolve()


PROJECT_NAME = PROJECT_DIR.name


TORCHA_DIR = PROJECT_DIR / ".torcha"


LEGACY_DIR_NAME = ".agentorch"
"""The runtime data directory before the rename, still present in adopted projects."""


CONFIG_FILE = TORCHA_DIR / "agents.json"


REGISTRY_FILE = TORCHA_DIR / "registry.json"


BOOTSTRAP_DIR = TORCHA_DIR / "bootstrap"


def configure_project(path: Path | None = None) -> None:
    """Resuelve las rutas del proyecto objetivo: el directorio actual por defecto.

    Las demás funciones leen estos nombres como atributos del módulo, así que el
    cambio se propaga sin reimportar nada.
    """
    global PROJECT_DIR, PROJECT_NAME, TORCHA_DIR
    global CONFIG_FILE, REGISTRY_FILE, BOOTSTRAP_DIR
    target = (path or Path.cwd()).expanduser().resolve()
    if not target.is_dir():
        raise TorchaError(f"The project directory does not exist: {target}")
    PROJECT_DIR = target
    PROJECT_NAME = target.name
    TORCHA_DIR = target / ".torcha"
    CONFIG_FILE = TORCHA_DIR / "agents.json"
    REGISTRY_FILE = TORCHA_DIR / "registry.json"
    BOOTSTRAP_DIR = TORCHA_DIR / "bootstrap"

def legacy_dir() -> Path:
    """The old data directory of the project being acted on."""
    return PROJECT_DIR / LEGACY_DIR_NAME

def require_current_layout() -> None:
    """Refuse a project that still keeps its data under the old directory name.

    The migration is explicit on purpose: copying a project behind the human's
    back is worse than stopping. `torcha migrate` is the only command that runs
    on that layout, so it never calls this.
    """
    legacy, current = legacy_dir(), TORCHA_DIR
    if legacy.is_dir() and not current.is_dir():
        raise TorchaError(
            f"This project still keeps its data in {legacy}: run 'torcha migrate' "
            f"to copy it to {current}.")


def norm_path(value: Any) -> str | None:
    """Normaliza una ruta que llega de Herdr, resolviendo las relativas contra el proyecto."""
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    try:
        return str(path.resolve())
    except OSError:
        return os.path.abspath(path)
