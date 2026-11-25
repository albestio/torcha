"""Discovery of agents and roles a project already declares as files.

Every supported convention uses the same shape: Markdown with YAML frontmatter
carrying `name` and `description`. A file missing either is not an agent
declaration and is skipped, which is exactly what Pi's own loader does.

No YAML dependency: only the scalar fields we need are parsed, including block
scalars (`key: >` and `key: |`), which real files use for long descriptions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# (relative directory, glob, source label, scope)
SOURCES = [
    (".pi/agents", "*.md", "pi", "project"),
    (".claude/agents", "*.md", "claude", "project"),
    (".github/agents", "*.agent.md", "copilot", "project"),
    (".cursor/agents", "*.md", "cursor", "project"),
    ("agents", "*.md", "agents", "project"),
    ("ai-specs/agents", "*.md", "ai-specs", "project"),
    (".pi/agent/agents", "*.md", "pi", "user"),
    (".claude/agents", "*.md", "claude", "user"),
]

ORCHESTRATOR_NAMES = {
    "orchestrator", "orquestador", "lead", "leader", "coordinator", "coordinador",
    "architect", "arquitecto", "manager", "captain",
}

# Only nouns that name the role. "lead" is deliberately absent: it appears in
# ordinary prose ("indexes lead sources") and would elect the wrong agent.
ORCHESTRATOR_ROLE_WORDS = ("orchestrator", "orquestador", "coordinator", "coordinador")

ROLE_MODIFIERS = {
    "senior", "junior", "lead", "leader", "chief", "principal", "staff",
    "head", "main", "primary", "sr", "jr",
}

ROLE_LIMIT = 300

DEFAULT_ORCHESTRATOR = {
    "key": "orchestrator",
    "name": "Orchestrator",
    "role": "Coordinates the team, assigns work and verifies results.",
}


@dataclass(frozen=True)
class Candidate:
    key: str
    name: str
    role: str
    source: str
    scope: str
    path: str


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the scalar fields of a leading YAML frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    fields: dict[str, str] = {}
    key: str | None = None
    collected: list[str] = []

    def flush() -> None:
        if key is not None:
            fields[key] = " ".join(collected).strip()

    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if raw[:1] in (" ", "\t") and key is not None:
            collected.append(raw.strip())
            continue
        flush()
        key, collected = None, []
        if ":" not in raw:
            continue
        name, _, value = raw.partition(":")
        name, value = name.strip(), value.strip()
        if not name:
            continue
        key = name
        if value and value not in (">", "|", ">-", "|-", ">+", "|+"):
            collected = [value]
    flush()
    return fields


def slug(value: str) -> str:
    """Turn a display name into a key accepted by the config validator."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not cleaned:
        return "agent"
    if not cleaned[0].isalpha():
        return f"agent_{cleaned}"
    return cleaned


def _trim(role: str) -> str:
    role = " ".join(role.split())
    return role if len(role) <= ROLE_LIMIT else role[:ROLE_LIMIT].rstrip() + "…"


def _candidate(path: Path, source: str, scope: str) -> Candidate | None:
    try:
        fields = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    name, description = fields.get("name", "").strip(), fields.get("description", "").strip()
    if not name or not description:
        return None
    return Candidate(
        key=slug(name),
        name=name,
        role=_trim(description),
        source=source,
        scope=scope,
        path=str(path),
    )


def scan(project_dir: Path, user_home: Path | None = None,
         scope: str | None = None) -> list[Candidate]:
    """Find agent declarations, project sources first, deduplicated by identity."""
    home = user_home if user_home is not None else Path.home()
    found: list[Candidate] = []
    seen: set[tuple[str, str]] = set()

    for relative, pattern, source, where in SOURCES:
        if scope is not None and where != scope:
            continue
        base = project_dir if where == "project" else home
        directory = base / relative
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(pattern)):
            candidate = _candidate(path, source, where)
            if candidate is None:
                continue
            identity = candidate.name.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            found.append(candidate)
    return found


def orchestrator_score(candidate: Candidate) -> int:
    """How strongly a declaration claims the coordinating role; 0 means no claim.

    The name is a deliberate statement, so it outranks the description, where a
    stray word can be prose.
    """
    tokens = set(re.split(r"[^a-z0-9]+", candidate.name.casefold())) - {""}
    if tokens & ORCHESTRATOR_NAMES:
        return 2
    role = candidate.role.casefold()
    if any(re.search(rf"\b{word}\b", role) for word in ORCHESTRATOR_ROLE_WORDS):
        return 1
    return 0


def is_orchestrator(candidate: Candidate) -> bool:
    return orchestrator_score(candidate) > 0


def _unique(key: str, taken: set[str]) -> str:
    if key not in taken:
        return key
    index = 2
    while f"{key}_{index}" in taken:
        index += 1
    return f"{key}_{index}"


def repeated_prefixes(names: list[str]) -> set[str]:
    """First tokens shared by at least two names: a project's own namespace.

    Discovered, never assumed. Per token, not global: a project can have several
    families (`job-*` and `review-*`) and each keeps its own prefix.
    """
    counts: dict[str, int] = {}
    for name in names:
        tokens = [t for t in re.split(r"[^A-Za-z0-9]+", name) if t]
        if tokens:
            counts[tokens[0].lower()] = counts.get(tokens[0].lower(), 0) + 1
    return {token for token, count in counts.items() if count >= 2}


def role_name(name: str, prefixes: set[str] | frozenset[str] = frozenset()) -> str:
    """The role an agent plays: namespace prefix and seniority removed.

    "Senior Orchestrator" and "job-senior" both describe the same role; only the
    remaining words belong in the config. `Worker 1` keeps its number: stripping
    the prefix would leave nothing but a digit.
    """
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", name) if t]
    if tokens and tokens[0].lower() in prefixes:
        rest = tokens[1:]
        if rest and not all(token.isdigit() for token in rest):
            tokens = rest
    kept = [t for t in tokens if t.lower() not in ROLE_MODIFIERS]
    kept = kept or tokens or [name]
    return " ".join(token[:1].upper() + token[1:] for token in kept)


from .config import MAX_TABS


def choose(candidates: list[Candidate], max_tabs: int = MAX_TABS) -> list[dict[str, str]]:
    """Build the `tabs` list: one orchestrator first, then up to max_tabs - 1."""
    if max_tabs < 1:
        raise ValueError("max_tabs must be at least 1")

    namespace = repeated_prefixes([c.name for c in candidates])
    ranked = [(orchestrator_score(c), index, c) for index, c in enumerate(candidates)]
    best = max(ranked, key=lambda item: (item[0], -item[1])) if ranked else None
    orchestrator = best[2] if best and best[0] > 0 else None

    tabs = [{
        "key": "orchestrator",
        "name": "Orchestrator",
        "role": orchestrator.role if orchestrator else DEFAULT_ORCHESTRATOR["role"],
    }]
    taken = {"orchestrator"}

    for candidate in candidates:
        if len(tabs) >= max_tabs:
            break
        if orchestrator is not None and candidate is orchestrator:
            continue
        label = role_name(candidate.name, namespace)
        key = _unique(slug(label), taken)
        taken.add(key)
        tabs.append({"key": key, "name": label, "role": candidate.role})
    return tabs
