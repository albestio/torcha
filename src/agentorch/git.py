"""Precondition: the project must be a git repository."""

from __future__ import annotations

import subprocess
import sys

from . import project
from .errors import AgentorchError
from .output import log

def repo_head() -> str | None:
    """The project's current commit, or None when it cannot be read."""
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project.PROJECT_DIR,
                            text=True, capture_output=True, check=False)
    if result.returncode != 0:
        return None
    head = result.stdout.strip()
    return head or None


def repo_state() -> dict[str, str]:
    """What a handoff must state about the repository, measured now."""
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=project.PROJECT_DIR, text=True,
                            capture_output=True, check=False)
    status = subprocess.run(["git", "status", "--porcelain"],
                            cwd=project.PROJECT_DIR, text=True,
                            capture_output=True, check=False)
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
    summary = "clean tree" if not dirty else f"{len(dirty)} file(s) uncommitted"
    return {
        "branch": branch.stdout.strip() or "unknown",
        "head": repo_head() or "",
        "status_summary": summary,
    }


def ensure_git_repo() -> None:
    """Precondición barata: no arrancar agentes en una carpeta sin repositorio.

    Se ejecuta antes de crear nada: si el usuario cancela, no se crea space,
    ni tabs, ni registry, ni se arranca ningún agente.
    """
    try:
        result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                                cwd=project.PROJECT_DIR, text=True,
                                capture_output=True, check=False)
    except FileNotFoundError:
        raise AgentorchError("'git' is not on PATH.")
    if result.returncode == 0:
        return
    if not sys.stdin.isatty():
        raise AgentorchError(
            f"{project.PROJECT_DIR} is not a git repository and the input is not interactive.")
    answer = input(f"{project.PROJECT_DIR} is not a git repository. Run 'git init'? [Y/n] ")
    if answer.strip().lower() not in ("", "y", "yes", "s", "si", "sí"):
        raise AgentorchError(
            "Cancelled: no space was created and no agent was started.")
    result = subprocess.run(["git", "init"], cwd=project.PROJECT_DIR, text=True,
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise AgentorchError(
            f"'git init' failed: {(result.stderr or result.stdout).strip()}")
    log(f"Git repository initialised in {project.PROJECT_DIR}")
