"""The status command: compare the registry with what Herdr reports.

It rules on divergence: a role whose space, tab, terminal or pid no longer
matches the registry is `missing` or `moved`, and the command exits 1. That
contract does not move.

On top of it, and without ever changing the verdict, it prints the detail that
decides a handoff: the newest handoff of the role with its age and the `git.head`
it recorded, how far the repository has moved since that head and whether the
working tree is dirty, and the tokens the role spent on its last turn read from
its Pi session transcript, with the context percentage only when the model's
window is resolvable.

Every one of those sources is optional and read-only. A missing handoff, session
id, transcript, model window or git answer is said per role: it never fails the
command, is never estimated, and nothing is written or sent to an agent.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from ..errors import AgentorchError
from ..git import commits_between, is_ancestor, repo_head, working_tree
from ..handoff import load_handoff, newest_handoff
from ..herdr import (get_spaces, parse_json_output, run_app, space_id, tab_id,
                     tab_name, tabs_of, terminal_pid)
from ..output import log, note
from ..registry import load_registry

ALIVE = "alive"
DOWN = "down"
MISSING = "missing"
MOVED = "moved"

# Only these mean the registry no longer describes reality. A role that is down
# is information, not a divergence: not every agent has to be running.
DIVERGENT = {MISSING, MOVED}

# A session id is a file name fragment and a glob: anything else is not looked
# up, because a registry is data and data does not get to walk the filesystem.
SESSION_ID = re.compile(r"^[A-Za-z0-9._-]{4,}$")

# Where Pi states the window of a model it knows. Read in this order: the store
# Pi filled when it resolved its providers, then a hand-written model file, which
# only fills the gaps. Both lose to the transcript, which states what the human
# already saw in Pi's own status bar.
MODEL_FILES = ("models-store.json", "models.json")

TRANSCRIPT_SUFFIXES = (".jsonl", ".json")

# One lookup per session id and process: `status` asks for the same transcript
# once per run and a store can be large.
_TRANSCRIPTS: dict[str, Path | None] = {}


def _find_terminal(tab: dict, terminal_id: str | None) -> dict | None:
    for terminal in tab.get("terminals") or []:
        if isinstance(terminal, dict) and terminal.get("terminal") == terminal_id:
            return terminal
    return None


def _role_state(space: dict | None, entry: dict) -> tuple[str, str]:
    if space is None:
        return MISSING, "the space no longer exists"

    tab = next((t for t in tabs_of(space) if tab_id(t) == entry.get("tab_id")), None)
    if tab is None:
        return MISSING, "the tab no longer exists"

    terminal_id = entry.get("terminal_id")
    terminal = _find_terminal(tab, terminal_id)
    if terminal is None:
        return MISSING, "the terminal no longer exists"

    if not terminal.get("app"):
        return DOWN, "no agent (shell)"

    live = terminal_pid(terminal_id)
    recorded = entry.get("pid")
    if recorded and live and recorded != live:
        return MOVED, f"the pid changed: {recorded} → {live}"

    detail = f"pid {live}" if live else "no pid"
    renamed = tab_name(tab)
    if renamed and entry.get("name") and renamed != entry["name"]:
        detail += f", renamed to {renamed!r}"
    return ALIVE, detail


# --- the newest handoff ------------------------------------------------------


def _short(value: str | None, length: int = 7) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:length]


def _text(value: object) -> str | None:
    """A non-empty string as it is, or None: a document is data, not a promise."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _short_session(value: str) -> str:
    """The start of a session id: a line has room for eight characters."""
    return value.split("-")[0][:8]


def _moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(path: Path, document: dict) -> int | None:
    """How old the handoff is, from `created_at`, else from the file's mtime."""
    moment = _moment(document.get("created_at"))
    if moment is None:
        try:
            moment = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        except OSError:
            return None
    now = datetime.now(tz=moment.tzinfo) if moment.tzinfo else datetime.now()
    return int((now - moment).total_seconds())


def _age_text(seconds: int | None) -> str:
    if seconds is None:
        return "age unknown"
    if seconds < 90:
        return f"{max(seconds, 0)}s ago"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 36:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _handoff_of(role: str) -> dict:
    """The newest handoff of a role: how old it is and the head it recorded."""
    block: dict = {"present": False, "path": None, "handoff_id": None,
                   "status": None, "created_at": None, "age_seconds": None,
                   "age": None, "head": None, "branch": None, "detail": ""}

    path = newest_handoff(role)
    if path is None:
        block["detail"] = "no handoff: nothing to compare"
        return block

    block.update(present=True, path=str(path))
    try:
        document = load_handoff(path)
    except AgentorchError as exc:
        block["detail"] = f"the newest handoff could not be read: {exc}"
        return block

    git_block = document.get("git")
    head = git_block.get("head") if isinstance(git_block, dict) else None
    branch = git_block.get("branch") if isinstance(git_block, dict) else None
    age = _age_seconds(path, document)
    block.update(
        handoff_id=document.get("handoff_id"),
        status=_text(document.get("status")),
        created_at=_text(document.get("created_at")),
        age_seconds=age,
        age=_age_text(age),
        head=_text(head),
        branch=_text(branch),
    )

    parts = [block["age"]]
    parts.append(f"head {_short(block['head'])}" if block["head"]
                 else "no git.head recorded")
    if block["status"]:
        parts.append(block["status"])
    block["detail"] = " · ".join(parts)
    return block


# --- drift against the repository --------------------------------------------


def _tree_text(tree: dict | None) -> str:
    if tree is None:
        return "the working tree could not be inspected"
    if not tree["dirty"]:
        return "the working tree is clean"
    return f"{tree['files']} uncommitted file(s)"


def _repository() -> tuple[str | None, dict | None]:
    """The current HEAD and the state of the tree, or None when unreadable."""
    try:
        head = repo_head()
    except OSError:
        head = None
    return head, working_tree()


def _drift(handoff: dict, current: str | None, tree: dict | None) -> dict:
    """How far the repository moved since the handoff, measured, never guessed."""
    drift: dict = {
        "head": current,
        "commits": None,
        "ancestor": None,
        "dirty": None if tree is None else bool(tree["dirty"]),
        "dirty_files": None if tree is None else int(tree["files"]),
        "detail": "",
    }

    if not handoff.get("present"):
        drift["detail"] = "nothing to compare: there is no handoff"
        return drift

    recorded = handoff.get("head")
    if not recorded:
        drift["detail"] = ("nothing to compare: the handoff records no "
                           "'git.head' · " + _tree_text(tree))
        return drift

    if not current:
        drift["detail"] = ("the current commit could not be read, so the drift "
                           "is unknown · " + _tree_text(tree))
        return drift

    ancestor = is_ancestor(recorded, current)
    drift["ancestor"] = ancestor
    if ancestor is False:
        movement = ("the handoff's head is not an ancestor of HEAD: the branch "
                    "was rebased or rewritten, so no count is given")
    elif ancestor is None:
        movement = "the ancestry of the handoff's head could not be checked"
    else:
        commits = commits_between(recorded, current)
        drift["commits"] = commits
        if commits is None:
            movement = "the commit count could not be read"
        elif commits == 0:
            movement = "HEAD has not moved since that head"
        else:
            movement = f"{commits} commit(s) since that head"

    drift["detail"] = f"{movement} · {_tree_text(tree)}"
    return drift


# --- tokens from the Pi transcript -------------------------------------------


def _agent_dir() -> Path:
    """Pi's own directory: its session store and its model catalogue live there."""
    override = os.environ.get("PI_CODING_AGENT_DIR")
    return Path(override).expanduser() if override else Path.home() / ".pi" / "agent"


def _session_roots() -> list[Path]:
    """The stores Pi may keep transcripts in, whichever layout this machine has.

    A store can be flat or hold one directory per project path, so the caller
    globs by session id under each root instead of assuming a shape. A root that
    does not exist is not an error; it is simply not searched.
    """
    candidates: list[Path] = []
    own = os.environ.get("PI_SESSION_FILE")
    if own:
        candidates.append(Path(own).expanduser().parent)
    agent = _agent_dir()
    candidates.append(agent / "sessions")
    try:
        candidates.extend(sorted(path for path in agent.glob("*/sessions")
                                 if path.is_dir()))
    except OSError:
        pass

    roots: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        roots.append(path)
    return roots


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_transcript(session_id: object) -> Path | None:
    """The transcript of a session id, or None. A guessed path is never used."""
    if not isinstance(session_id, str) or not SESSION_ID.match(session_id.strip()):
        return None
    wanted = session_id.strip()
    if wanted in _TRANSCRIPTS:
        return _TRANSCRIPTS[wanted]

    matches: list[Path] = []
    for root in _session_roots():
        try:
            matches.extend(path for path in root.rglob(f"*{wanted}*")
                           if path.is_file() and path.suffix in TRANSCRIPT_SUFFIXES)
        except OSError:
            continue
    found = max(matches, key=_mtime) if matches else None
    _TRANSCRIPTS[wanted] = found
    return found


def last_turn(path: Path) -> dict | None:
    """The last message of a transcript that carries a `usage` block.

    The last line is not necessarily the one: Pi writes other events after it,
    so the block is searched for instead of assumed to be the newest line.
    """
    found: dict | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                usage = message.get("usage") if isinstance(message, dict) else None
                if not isinstance(usage, dict):
                    continue
                tokens = usage.get("totalTokens")
                if not isinstance(tokens, int) or isinstance(tokens, bool):
                    continue
                model = message.get("model")
                found = {
                    "total_tokens": tokens,
                    "model": model if isinstance(model, str) and model.strip() else None,
                }
    except OSError:
        return None
    return found


def _windows(document: object) -> dict[str, int]:
    """Every `contextWindow` a Pi model file states, keyed by model id and name.

    The whole document is walked instead of one known shape: a hand-written
    `models.json` nests providers under `providers`, but the store Pi downloaded
    keeps every provider at the top level (`{"opencode-go": {"models": [...]}}`),
    so a lookup that only walked `providers.*` never found the real machine's
    model. A window that is not a positive integer is not an answer.
    """
    windows: dict[str, int] = {}
    for node in _mappings(document):
        window = _positive_int(node.get("contextWindow"))
        if window is None:
            continue
        for key in (node.get("id"), node.get("name")):
            if isinstance(key, str) and key.strip():
                windows.setdefault(key.strip(), window)

    providers = document.get("providers") if isinstance(document, dict) else None
    if isinstance(providers, dict):
        for provider in providers.values():
            overrides = provider.get("modelOverrides") \
                if isinstance(provider, dict) else None
            if not isinstance(overrides, dict):
                continue
            for key, override in overrides.items():
                if not isinstance(key, str) or not isinstance(override, dict):
                    continue
                window = _positive_int(override.get("contextWindow"))
                if window is not None:
                    windows[key] = window
    return windows


def context_window(model: str | None) -> int | None:
    """The window a Pi model file states for a model, or None.

    The transcript is asked first (see `last_presence`); this is the fallback for
    a transcript that carries no presence record. When neither says anything the
    caller states that it is unknown instead of inventing a number.
    """
    if not isinstance(model, str) or not model.strip():
        return None
    wanted = model.strip()
    agent = _agent_dir()
    for name in MODEL_FILES:
        try:
            document = json.loads((agent / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        windows = _windows(document)
        if wanted in windows:
            return windows[wanted]
    return None


def _positive_int(value: object) -> int | None:
    """A count a source states, or None. `True` is not a count."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _percent(value: object) -> int | None:
    """A stated percentage: a whole number from 0 to 100, or nothing."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 100 else None


def _mappings(node: object):
    """Every mapping of a document, in the order the document holds them."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


# What a presence record states about the model Pi is running. Where the record
# sits on the line changes between versions and between transports, so it is
# found by its fields instead of by a path.
PRESENCE_FIELDS = ("contextPct", "contextWindow")


def _presence(record: object) -> dict | None:
    """The presence block a transcript line carries, wherever the line puts it."""
    candidates = [node for node in _mappings(record)
                  if any(field in node for field in PRESENCE_FIELDS)]
    if not candidates:
        return None
    complete = [node for node in candidates
                if all(field in node for field in PRESENCE_FIELDS)]
    return (complete or candidates)[0]


def last_presence(path: Path, session_id: str | None = None) -> dict | None:
    """The last presence record of a transcript, or None.

    Pi writes, beside the message, the figures its own status bar shows: the
    percentage of the window it is running and the size of that window. That is
    the number the human already read, so it is the one to trust; the last such
    record wins, as in `last_turn`, because a session can change models.
    """
    found: dict | None = None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or '"context' not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                block = _presence(record)
                if block is None:
                    continue
                # A transcript also stores other sessions' presence blocks:
                # intercom tool results carry them, with their own context and
                # window. Borrowing one reports a neighbour's percentage, so only
                # a block that identifies itself as this session counts.
                if session_id and block.get("id") != session_id:
                    continue
                window = _positive_int(block.get("contextWindow"))
                percent = _percent(block.get("contextPct"))
                model = block.get("model")
                found = {
                    "percent": percent,
                    "window": window,
                    "tokens": _positive_int(block.get("contextTokens")),
                    "model": (model if isinstance(model, str) and model.strip()
                              else None),
                }
    except OSError:
        return None
    return found


def _usage(entry: dict) -> dict:
    """The tokens of the role's last turn, and honestly nothing else if unknown."""
    session_id = entry.get("session_id")
    block: dict = {
        "session_id": session_id if isinstance(session_id, str) else None,
        "transcript": None, "model": None, "total_tokens": None,
        "context_window": None, "percent": None, "detail": "",
    }

    if not block["session_id"] or not block["session_id"].strip():
        block["detail"] = "no session id in the registry: the tokens are unknown"
        return block

    path = find_transcript(block["session_id"])
    if path is None:
        block["detail"] = (f"no transcript for session "
                           f"{_short_session(block['session_id'])}: "
                           "the tokens are unknown")
        return block
    block["transcript"] = str(path)

    turn = last_turn(path)
    if turn is None:
        block["detail"] = ("no message of the transcript carries a usage block: "
                           "the tokens are unknown")
        return block

    block["model"] = turn["model"]
    block["total_tokens"] = turn["total_tokens"]

    presence = last_presence(path, block["session_id"]) or {}
    model = turn["model"] or presence.get("model")
    window = presence.get("window") or context_window(model)
    block["context_window"] = window
    # The stated percentage wins over the one this code could divide out: Pi
    # counted what it actually holds, and a second, disagreeing number would be
    # a number nobody asked for.
    percent = presence.get("percent")
    if percent is None and window:
        percent = round(100 * turn["total_tokens"] / window)
    block["percent"] = percent

    parts = [f"{turn['total_tokens']:,} tokens"]
    parts.append(f"model {turn['model']}" if turn["model"] else "model unknown")
    if percent is not None and window:
        parts.append(f"about {percent}% of a {window:,}-token window")
    elif percent is not None:
        # A window nobody stated is not invented, but the percentage Pi gave is
        # still the human's own reading, so it is shown without a size.
        parts.append(f"about {percent}% of its context window · "
                     "the window size is unknown")
    else:
        parts.append("no context window known: no percentage")
    block["detail"] = " · ".join(parts)
    return block


def status(as_json: bool = False) -> int:
    registry = load_registry()
    data = parse_json_output(run_app(["ls"]), "herdr-app ls")
    spaces = get_spaces(data)
    wanted = (registry.get("herdr") or {}).get("space_id")
    space = next((s for s in spaces if space_id(s) == wanted), None)
    current, tree = _repository()

    roles = []
    for key, entry in ((registry.get("herdr") or {}).get("tabs") or {}).items():
        state, detail = _role_state(space, entry)
        handoff = _handoff_of(key)
        roles.append({"role": key, "name": entry.get("name"),
                      "state": state, "detail": detail,
                      "handoff": handoff,
                      "drift": _drift(handoff, current, tree),
                      "usage": _usage(entry)})

    alive = sum(1 for role in roles if role["state"] == ALIVE)
    diverged = any(role["state"] in DIVERGENT for role in roles)

    if as_json:
        print(json.dumps({
            "registry": {"status": registry.get("status"), "space_id": wanted},
            "roles": roles,
            "summary": {"total": len(roles), "alive": alive, "diverged": diverged},
        }, indent=2, ensure_ascii=False))
        return 1 if diverged else 0

    if registry.get("status") not in (None, "ready"):
        note(f"The registry is in state {registry.get('status')!r}"
             + (f": {registry['error']}" if registry.get("error") else ""))

    width = max((len(role["role"]) for role in roles), default=4)
    for role in roles:
        log(f"  {role['role']:<{width}}  {role['state']:<11} {role['detail']}")
        log(f"      {'handoff':<8} {role['handoff']['detail']}")
        log(f"      {'drift':<8} {role['drift']['detail']}")
        log(f"      {'tokens':<8} {role['usage']['detail']}")
    log(f"{alive} of {len(roles)} role(s) alive"
        + ("" if not diverged else " · the registry no longer describes reality"))
    return 1 if diverged else 0
