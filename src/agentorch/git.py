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


def commits_between(base: str, head: str = "HEAD") -> int | None:
    """How many commits separate `base` from `head`, or None when git cannot say."""
    try:
        result = subprocess.run(["git", "rev-list", "--count", f"{base}..{head}"],
                                cwd=project.PROJECT_DIR, text=True,
                                capture_output=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def is_ancestor(older: str, newer: str = "HEAD") -> bool | None:
    """Whether `older` is an ancestor of `newer`; None when git cannot answer.

    A sha that is no longer on the branch (a rebase, a rewritten branch) is a
    real answer, not a failure: the caller says so instead of counting commits
    it cannot count.
    """
    try:
        result = subprocess.run(["git", "merge-base", "--is-ancestor", older, newer],
                                cwd=project.PROJECT_DIR, text=True,
                                capture_output=True, check=False)
    except OSError:
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def working_tree() -> dict[str, object] | None:
    """Whether the working tree has uncommitted changes, and how many files.

    None means git could not be asked, which is not the same as a clean tree.
    """
    try:
        result = subprocess.run(["git", "status", "--porcelain"],
                                cwd=project.PROJECT_DIR, text=True,
                                capture_output=True, check=False)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    return {"dirty": bool(dirty), "files": len(dirty)}


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
