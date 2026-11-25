"""The handoff document: contract, validation and storage.

A handoff is the operational state of one role at one moment. It is a file, not a
memory entry, because the session swap validates it (schema, ids, checksum)
before replacing anything: a memory store cannot be a validation target.

It is never versioned. The current handoff is gitignored and the chain of
revisions lives in Engram, where each new one supersedes the previous.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import project
from .errors import TorchaError

SCHEMA_VERSION = 1
STATUSES = ("prepared", "consumed", "superseded")

REQUIRED_STRINGS = (
    "handoff_id", "project", "agent_id", "role", "created_at",
    "source_pi_session_id", "status", "objective", "current_state",
)
REQUIRED_STRING_LISTS = (
    "completed", "in_progress", "next_actions", "decisions", "blockers",
    "engram_refs",
)

HEX = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

# High-confidence credential shapes. A handoff must never carry one.
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|api[_-]?key|secret[_-]?key)\s*[:=]\s*\S+"),
)


def handoff_dir(role: str) -> Path:
    return project.TORCHA_DIR / "handoffs" / role


def handoff_path(role: str, handoff_id: str) -> Path:
    return handoff_dir(role) / f"{handoff_id}.json"


def walk_strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from walk_strings(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_strings(child, f"{path}[{index}]")


def secret_findings(data: Any) -> list[str]:
    """Fields whose value looks like a credential."""
    findings = []
    for path, text in walk_strings(data):
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            findings.append(f"{path}: looks like it contains a credential")
    return findings


def _iso(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_handoff(data: Any, *, project_name: str | None = None,
                     agent_id: str | None = None) -> list[str]:
    """Everything wrong with a handoff document. An empty list means valid."""
    if not isinstance(data, dict):
        return ["the document is not a JSON object"]

    problems: list[str] = []

    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}, "
                        f"is {data.get('schema_version')!r}")

    for field in REQUIRED_STRINGS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"'{field}' is missing or is not a non-empty string")

    handoff_id = data.get("handoff_id")
    if isinstance(handoff_id, str) and handoff_id:
        try:
            uuid.UUID(handoff_id)
        except ValueError:
            problems.append(f"'handoff_id' is not a UUID: {handoff_id!r}")

    created_at = data.get("created_at")
    if isinstance(created_at, str) and created_at and not _iso(created_at):
        problems.append(f"'created_at' is not ISO-8601: {created_at!r}")

    status = data.get("status")
    if isinstance(status, str) and status and status not in STATUSES:
        problems.append(f"'status' must be one of {STATUSES}: {status!r}")

    for field in REQUIRED_STRING_LISTS:
        value = data.get(field)
        if not isinstance(value, list):
            problems.append(f"'{field}' must be a list")
        elif any(not isinstance(item, str) for item in value):
            problems.append(f"'{field}' must contain strings only")

    files = data.get("files_touched")
    if not isinstance(files, list):
        problems.append("'files_touched' must be a list")
    else:
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                problems.append(f"'files_touched[{index}]' must be an object")
                continue
            if not isinstance(item.get("path"), str) or not item["path"].strip():
                problems.append(f"'files_touched[{index}].path' is missing")
            if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                problems.append(f"'files_touched[{index}].reason' is missing")

    validation = data.get("validation")
    if not isinstance(validation, dict):
        problems.append("'validation' must be an object")
    else:
        for field in ("commands_run", "results"):
            value = validation.get(field)
            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                problems.append(f"'validation.{field}' must be a list of strings")

    git = data.get("git")
    if not isinstance(git, dict):
        problems.append("'git' must be an object")
    else:
        for field in ("branch", "head", "status_summary"):
            if not isinstance(git.get(field), str) or not git[field].strip():
                problems.append(f"'git.{field}' is missing or empty")
        head = git.get("head")
        if isinstance(head, str) and head and not HEX.match(head):
            problems.append(f"'git.head' is not a 40 or 64 character sha: {head!r}")

    if project_name is not None and data.get("project") != project_name:
        problems.append(f"'project' is {data.get('project')!r}, "
                        f"expected {project_name!r}")
    if agent_id is not None and data.get("agent_id") != agent_id:
        problems.append(f"'agent_id' is {data.get('agent_id')!r}, "
                        f"expected {agent_id!r}")

    problems.extend(secret_findings(data))
    return problems


def newest_handoff(role: str) -> Path | None:
    """The newest handoff document of a role, or None when it has none.

    "Newest" is the last one written, by modification time: that is the document
    the agents are told to read and the one that describes the role now.
    """
    directory = handoff_dir(role)
    try:
        candidates = [path for path in directory.glob("*.json") if path.is_file()]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)
    except OSError:
        return None


def load_handoff(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise TorchaError(f"The handoff does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TorchaError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TorchaError(f"The handoff is not a JSON object: {path}")
    return data


def new_handoff(*, agent_id: str, role: str, source_pi_session_id: str,
                objective: str, current_state: str, git_branch: str,
                git_head: str, git_status_summary: str,
                project_name: str | None = None) -> dict[str, Any]:
    """A handoff with every required field, ready to be filled in and validated."""
    return {
        "schema_version": SCHEMA_VERSION,
        "handoff_id": str(uuid.uuid4()),
        "project": project_name or project.PROJECT_NAME,
        "agent_id": agent_id,
        "role": role,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_pi_session_id": source_pi_session_id,
        "status": "prepared",
        "objective": objective,
        "current_state": current_state,
        "completed": [],
        "in_progress": [],
        "next_actions": [],
        "files_touched": [],
        "decisions": [],
        "blockers": [],
        "validation": {"commands_run": [], "results": []},
        "git": {"branch": git_branch, "head": git_head,
                "status_summary": git_status_summary},
        "engram_refs": [],
    }
