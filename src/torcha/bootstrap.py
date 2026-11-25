"""Bootstrap prompts handed to every Pi session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import project

# The team skill travels with the package, like the setup skill `init` loads:
# nothing has to exist in the target project for an agent to read it.
TEAM_SKILL = Path(__file__).resolve().parent / "skills" / "torcha" / "SKILL.md"


def bootstrap_path(key: str) -> Path:
    return project.BOOTSTRAP_DIR / f"{key}.md"

def bootstrap_text(item: dict[str, str], mode: str) -> str:
    """Prompt de arranque de un agente, según el modo configurado."""
    lines = [
        f"# Torcha bootstrap — {item['name']}",
        "",
        f"You are **{item['name']}** (`{item['key']}`), a member of the torcha team "
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
            f"`.torcha/handoffs/{item['key']}/`. It is the state your previous",
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

# The two modes that render a prompt: `none` launches no session, so it never
# writes a file and there is nothing to compare.
RENDERED_MODES = ("greet", "recover")


def _shown_path(path: Path) -> str:
    try:
        return path.relative_to(project.PROJECT_DIR).as_posix()
    except ValueError:
        return str(path)


def bootstrap_disagreement(key: str, item: dict[str, str],
                           mode: str) -> str | None:
    """Why `pi` would read a prompt other than the configured one, or None.

    The mode is not consulted at launch: it is rendered into this file, and the
    file is what `pi` reads as its first message. Editing `agents.json` from
    `greet` to `recover` therefore changes nothing until something renders the
    file again, so a launch whose file disagrees refuses instead of running the
    old prompt in silence. `torcha init` is the command that renders them.

    Writes nothing: the file is authoritative, and reconciling it is explicit.
    """
    path = bootstrap_path(key)
    shown = _shown_path(path)
    if not path.is_file():
        return f"the bootstrap file {shown} does not exist"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"the bootstrap file {shown} cannot be read: {exc}"
    if content == bootstrap_text(item, mode):
        return None
    written = next((other for other in RENDERED_MODES
                    if content == bootstrap_text(item, other)), None)
    if written is None:
        return (f"the bootstrap file {shown} holds neither the 'greet' nor the "
                f"'recover' prompt, but agents.json configures the {mode!r} mode")
    return (f"the bootstrap file {shown} holds the {written!r} prompt, "
            f"but agents.json configures the {mode!r} mode")


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
    """The argv that starts Pi with the bootstrap prompt as its first message.

    The prompt travels as an `@file` reference: there is no race with Pi's
    startup and no quoting of quotes, newlines or backticks. torcha assigns
    the `--session-id`, so the id is known from the start and the handoff can
    check that this session wrote it and not an earlier one.

    Every launch also gets the packaged team skill with an absolute `--skill`
    path: catching up and handing over cannot be commands, because `recover`
    and `handoff run --swap` both refuse the terminal running them, so the
    procedure has to be in the agent's own context from the first turn. The
    token cost in every session is accepted on purpose.

    Does not render the prompt: whoever needs a mode other than the configured
    one writes the file first with `write_bootstrap_files(tabs, mode)`.
    """
    if config["pi"]["bootstrap"] == "none":
        return None
    relative = bootstrap_path(item["key"]).relative_to(project.PROJECT_DIR).as_posix()
    argv = [config["pi"]["executable"], "--skill", str(TEAM_SKILL)]
    if session_id:
        argv += ["--session-id", session_id]
    return argv + [f"@{relative}"]
