"""Inspection of the live Herdr workspace: which tabs already run an agent.

A tab that a human renamed and that has a coding agent running is evidence of
the team the project is actually using, which is often more accurate than the
files in the repository. This module only reports; it never decides.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from . import project
from .config import MAX_TABS
from .discovery import (DEFAULT_ORCHESTRATOR, ORCHESTRATOR_NAMES, Candidate,
                        is_orchestrator, repeated_prefixes, role_name, slug)
from .herdr import tab_app, tab_id, tab_name, tabs_of
from .output import note

# `app` is what the program reports about itself over OSC 7501.
CODING_AGENTS = {
    "pi", "claude", "claude-code", "codex", "gemini", "cursor-agent",
    "aider", "opencode", "amp", "goose", "cline", "copilot", "devin",
}


@dataclass(frozen=True)
class LiveTab:
    name: str
    app: str | None
    status: str | None
    active: bool
    renamed: bool
    candidate: Candidate | None
    tab_id: str | None = None
    terminal_id: str | None = None

    @property
    def has_agent(self) -> bool:
        return bool(self.app)


def normalize(value: str) -> str:
    """Casefold, strip accents and collapse separators, for name comparison."""
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", plain.casefold()).strip()


def is_renamed(name: str | None) -> bool:
    """Herdr names an untouched tab after its number; anything else was chosen."""
    if not name or not name.strip():
        return False
    return not name.strip().isdigit()


def match_tab(name: str, candidates: list[Candidate]) -> Candidate | None:
    """Find the candidate whose declaration accounts for every word of the tab name.

    Requiring all tokens keeps common words ("worker", "auditor") from matching
    the first candidate that happens to share one of them.
    """
    tokens = set(normalize(name).split())
    if not tokens:
        return None

    best: Candidate | None = None
    best_score = 0
    for candidate in candidates:
        haystack = set(normalize(f"{candidate.name} {candidate.role}").split())
        if not tokens <= haystack:
            continue
        score = 3 if tokens <= set(normalize(candidate.name).split()) else 2
        if score > best_score:
            best, best_score = candidate, score
    return best


def _status(tab: dict) -> str | None:
    for terminal in tab.get("terminals") or []:
        if isinstance(terminal, dict) and terminal.get("status"):
            return terminal["status"]
    return None


def names_the_role(name: str) -> bool:
    """Whether the tab name itself states the coordinating role."""
    return bool(set(normalize(name).split()) & ORCHESTRATOR_NAMES)


def designate_orchestrator(tabs: list[LiveTab]) -> LiveTab | None:
    """Identify the main session of the project.

    Order of evidence: a renamed tab whose name states the role, then a renamed
    tab matched to a candidate that claims it, then the only tab running an agent.
    """
    for tab in tabs:
        if tab.renamed and names_the_role(tab.name):
            return tab
    for tab in tabs:
        if tab.renamed and tab.candidate is not None and is_orchestrator(tab.candidate):
            return tab
    live = [tab for tab in tabs if tab.has_agent]
    if len(live) == 1:
        return live[0]
    return None


UNDECLARED_ROLE = "Not declared in the repository; describe it."


def active_named(tabs: list[LiveTab]) -> list[LiveTab]:
    """Tabs a human named and where an agent is actually running.

    This is the team in use: the one that will carry handoffs. Declared roles in
    files are a catalogue; these are the sessions someone opened on purpose.
    """
    return [tab for tab in tabs if tab.renamed and tab.has_agent]


# The name `_mark_setup_tab` writes on the tab the interview runs in. It is a
# marker, not a role: adopting it would add a tab nobody uses to the team.
SETUP_TAB_NAME = "Agentorch"


def is_setup_tab(tab: LiveTab) -> bool:
    """Whether the tab carries the setup marker a previous interview left."""
    return tab.name.strip().casefold() == SETUP_TAB_NAME.casefold()


def role_tabs(tabs: list[LiveTab], own_tab_id: str | None = None) -> list[LiveTab]:
    """Tabs that can become roles: named, and neither the setup tab nor the caller's.

    One predicate on purpose. The skeleton, the proposal and the election of the
    orchestrator all have to ignore the same tabs, or they disagree about who
    the team is; the tab running the command is excluded because it is the setup
    terminal, not a role.
    """
    return [tab for tab in tabs
            if tab.renamed and not is_setup_tab(tab)
            and (own_tab_id is None or tab.tab_id != own_tab_id)]


def _cut_by_limit(ordered: list[LiveTab], limit: int, taken: int) -> list[LiveTab]:
    """Keep the tabs that fit and name the ones a live agent loses to the limit.

    Silent truncation is the defect this exists to stop: a named tab with an
    agent that never reaches the interview is a role nobody adopts. The tabs
    excluded before the limit are not named here, because they were not cut.
    """
    room = max(0, limit - taken)
    if len(ordered) <= room:
        return ordered
    dropped = [tab for tab in ordered[room:] if tab.has_agent]
    if dropped:
        note(f"The limit of {limit} tabs leaves out {len(dropped)} tab(s) with "
             f"an agent: {', '.join(tab.name for tab in dropped)}. Raise it with "
             f"'max_tabs' in {project.CONFIG_FILE}.")
    return ordered[:room]


def report_tabs_without_agent(tabs: list[LiveTab],
                              own_tab_id: str | None = None) -> list[LiveTab]:
    """Name the named tabs left out only because no agent runs in them.

    A named tab whose Pi died is an exclusion a human cannot see on screen: the
    skeleton drops it, so without this the role disappears in silence. The tabs
    excluded on purpose stay quiet -- the setup marker, a bare tab Herdr named
    after its number, and the tab running the command -- because reporting them
    would train the human to ignore the message. It is reported once per
    command, not from `role_tabs`, which several callers share in one run.
    """
    idle = [tab for tab in role_tabs(tabs, own_tab_id) if not tab.has_agent]
    if idle:
        place = "that tab" if len(idle) == 1 else "each of them"
        note(f"Named tab(s) with no agent running: "
             f"{', '.join(tab.name for tab in idle)}. Start Pi in {place} by "
             f"hand, or once the role is in the configuration run "
             f"'agentorch start <role> --recreate'.")
    return idle


def proposal_from_live(tabs: list[LiveTab], max_tabs: int = MAX_TABS,
                       own_tab_id: str | None = None) -> list[dict[str, str]]:
    """Build a `tabs` list from the tabs a human actually created and named.

    Always starts with an orchestrator, synthesised when no tab claims the role:
    a config without one would be rejected by the loader. Named tabs with an
    agent go first, and any tab the limit leaves out is reported.
    """
    members = role_tabs(tabs, own_tab_id)
    if not members:
        return []

    main = designate_orchestrator(members)
    namespace = repeated_prefixes([tab.name for tab in members])
    rest = [tab for tab in members if tab is not main]
    ordered = [tab for tab in rest if tab.has_agent] \
        + [tab for tab in rest if not tab.has_agent]

    result: list[dict[str, str]] = []
    taken: set[str] = {"orchestrator"}
    if main is None:
        result.append(dict(DEFAULT_ORCHESTRATOR))
    else:
        result.append({
            "key": "orchestrator",
            "name": "Orchestrator",
            "role": main.candidate.role if main.candidate else UNDECLARED_ROLE,
        })

    for tab in _cut_by_limit(ordered, max_tabs, len(result)):
        label = role_name(tab.name, namespace)
        base = key = slug(label)
        index = 2
        while key in taken:
            key = f"{base}_{index}"
            index += 1
        taken.add(key)
        result.append({
            "key": key,
            "name": label,
            "role": tab.candidate.role if tab.candidate else UNDECLARED_ROLE,
        })
    return result


def skeleton_from_live(tabs: list[LiveTab], max_tabs: int = MAX_TABS,
                       own_tab_id: str | None = None) -> list[dict[str, str]]:
    """Structure for the setup interview: live names, derived keys, empty prose.

    The names are the ones on screen, not the normalised role names: the config
    has to match the live tabs verbatim or `init` would create new ones. The keys
    are derived from the role the name expresses.

    Only a named tab with an agent is a role of the team in use: a named tab
    whose terminal went back to a shell declares nothing anyone can adopt. The
    setup marker and the tab running the command are never roles.
    """
    members = [tab for tab in role_tabs(tabs, own_tab_id) if tab.has_agent]
    if not members:
        return []

    main = designate_orchestrator(members)
    rest = [tab for tab in members if tab is not main]
    ordered = ([main] if main is not None else []) + rest
    namespace = repeated_prefixes([tab.name for tab in members])

    result: list[dict[str, str]] = []
    taken: set[str] = {"orchestrator"}
    for tab in _cut_by_limit(ordered, max_tabs, 0):
        if tab is main:
            key = "orchestrator"
        else:
            base = key = slug(role_name(tab.name, namespace))
            index = 2
            while key in taken:
                key = f"{base}_{index}"
                index += 1
        taken.add(key)
        result.append({"key": key, "name": tab.name,
                       "role": "", "instructions": ""})
    return result


def inspect_space(space: dict, candidates: list[Candidate]) -> list[LiveTab]:
    tabs: list[LiveTab] = []
    for tab in tabs_of(space):
        name = tab_name(tab) or ""
        renamed = is_renamed(name)
        terminals = tab.get("terminals") or []
        terminal_id = None
        for terminal in terminals:
            if isinstance(terminal, dict) and terminal.get("terminal"):
                terminal_id = str(terminal["terminal"])
                break
        tabs.append(LiveTab(
            name=name,
            app=tab_app(tab),
            status=_status(tab),
            active=bool(tab.get("active")),
            renamed=renamed,
            candidate=match_tab(name, candidates) if renamed else None,
            tab_id=tab_id(tab),
            terminal_id=terminal_id,
        ))
    return tabs
