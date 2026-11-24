"""Bootstrap prompts handed to every Pi session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import project

def bootstrap_path(key: str) -> Path:
    return project.BOOTSTRAP_DIR / f"{key}.md"

def bootstrap_text(item: dict[str, str], mode: str) -> str:
    """Prompt de arranque de un agente, según el modo configurado."""
    lines = [
        f"# Agentorch bootstrap — {item['name']}",
        "",
        f"You are **{item['name']}** (`{item['key']}`), a member of the agentorch team "
        f"for the project `{project.PROJECT_NAME}`.",
        "",
        "## Context",
        "",
        f"- Project root: `{project.PROJECT_DIR}`",
        f"- Role: {item['role']}",
        "",
    ]
    if item.get("instructions"):
        lines += ["## Instructions", "", item["instructions"], ""]
    if mode == "recover":
        lines += [
            "## Recovery protocol",
            "",
            "1. Confirm your identity, your role and the project root.",
            "",
            f"2. Read your latest handoff: the newest file in "
            f"`.agentorch/handoffs/{item['key']}/`. It is the state your previous",
            "   session left. If there is none, say so and continue.",
            "",
            "3. Validate that handoff against the repository before trusting it:",
            "   compare its `git.head` with `git rev-parse HEAD`. If HEAD moved, the",
            "   handoff is stale — re-measure what it claims and say what changed.",
            "   The working tree is the source of truth, never the document.",
            "",
            "4. Consult Engram for durable knowledge about this role:",
            "   `mem_search` with the project and your role, then",
            "   `mem_get_observation` on the best hit and read it in full; a snippet",
            "   is not enough. If there is nothing, say so and continue.",
            "",
            "5. Reply with a short recovery summary: what you were doing, what is",
            "   done, what is pending, and anything the repository contradicts.",
            "",
            "6. Declare `READY` only when you can continue safely, then wait for",
            "   instructions. Do not start work on your own.",
            "",
        ]
    else:
        lines += [
            "## Now",
            "",
            "Reply with one short line confirming who you are, then wait for instructions.",
            "Do not run any command, do not inspect the repository and do not start "
            "work on your own.",
            "",
        ]
    return "\n".join(lines)

def write_bootstrap_files(tabs: list[dict[str, str]], mode: str) -> list[Path]:
    project.BOOTSTRAP_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in tabs:
        path = bootstrap_path(item["key"])
        content = bootstrap_text(item, mode)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
        written.append(path)
    return written

def pi_argv(config: dict[str, Any], item: dict[str, str],
            session_id: str | None = None) -> list[str] | None:
    """argv que arranca Pi con el prompt de arranque como primer mensaje.

    El prompt viaja como referencia @archivo: no hay carrera con el arranque de
    Pi ni escapado de comillas, saltos de línea o backticks. El `--session-id`
    lo asigna agentorch, para que el id de sesión se conozca desde el arranque y
    el handoff pueda comprobar que lo escribió esta sesión y no otra anterior.

    No renderiza el prompt: quien necesite un modo distinto al configurado
    escribe el archivo antes con `write_bootstrap_files(tabs, modo)`.
    """
    if config["pi"]["bootstrap"] == "none":
        return None
    relative = bootstrap_path(item["key"]).relative_to(project.PROJECT_DIR).as_posix()
    argv = [config["pi"]["executable"]]
    if session_id:
        argv += ["--session-id", session_id]
    return argv + [f"@{relative}"]
