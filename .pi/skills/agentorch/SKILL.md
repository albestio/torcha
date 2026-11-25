---
name: agentorch
description: >
  Audit an existing Herdr workspace before adopting it with agentorch: identify
  the main session, normalise tab names to English, and generate
  .agentorch/agents.json from what the project and the workspace already declare.
  Use when the user asks to adopt a project that already has tabs or agents, to
  find out which tab is the orchestrator, or to rename tabs.
---

# Agentorch workspace audit

You are auditing a project that already runs, before agentorch takes it over.
Your job is to report what exists, propose names, and only then write config.

## 1. agentorch is the only source of truth

**Never run `hc` or `herdr-app` yourself.** Not to "check", not to "confirm", not
because a command failed. Those tools answer for the whole machine: 20+ spaces,
every project on it, and no notion of which one you are working on. Reading them
is how a role from one project gets attributed to another.

Everything you need comes from agentorch, already scoped to this project:

```bash
agentorch discover --live --json --project <path>   # everything, machine readable
agentorch discover --live --project <path>          # the same, for a human
agentorch status --json                             # registry vs reality
agentorch doctor                                    # preconditions
```

`--json` gives you, per tab: `tab_id`, `terminal_id`, `name`, `renamed`,
`active`, `app`, `status`, `role` (or `null`) and `is_main`. It also gives the
candidates declared in the project and a proposed `agents.json`.

If a command fails, **report the failure and stop**. Do not investigate by hand:
the failure is the finding, and the raw tools are not yours to reach for.

A tab with `role: null` is not an error. It is a role nobody wrote down.

## 2. Identify the main session

Apply these rules in order and stop at the first that answers:

1. **A renamed tab whose name states the role.** `Orchestrator`, `Orquestador`,
   `Lead`, `Coordinator`, `Architect`, `Manager`, `Captain`.
2. **A renamed tab matched to a declared role that claims it** (the role's name
   or description says orchestrator/coordinator).
3. **The only tab running an agent.** If exactly one tab has an app, that tab is
   the main session, whatever it is called.

If two or more tabs run agents and none states the role, do **not** pick one.
Report the ambiguity and ask the human.

`agentorch discover --live` already prints `Main session: <name>` using exactly
these rules. If it says `no identificada`, say so and stop.

## 3. Naming conventions

All names are English, in every artefact:

| Where | Convention | Example |
| --- | --- | --- |
| Tab name | Title Case, English | `Orchestrator`, `Reviewer`, `Implementer` |
| `agents.json` key | snake_case, English | `orchestrator`, `reviewer` |
| `role` | One English sentence, what it does | `Reviews changes for correctness.` |

Translate, do not transliterate: `Orquestador` → `Orchestrator`, `Revisor` →
`Reviewer`, `Porteador Implementer` → `Porting Implementer`.

Keep the human's own wording when it is already English and specific. Do not
invent roles to fill five tabs; a team of three is a valid team.

## 4. Rename, with confirmation

Show the human a table of current name → proposed name, and wait for approval.
Then, one call per tab:

```bash
agentorch rename <role> "<New Name>"
```

Rules:

- Never rename without explicit confirmation of the table.
- Never close, move or recreate a tab during an audit.
- If a tab runs an agent, renaming does not disturb it; if it does not, the tab
  is just a shell.
- Re-run `agentorch discover --live` afterwards and confirm the report shows the
  new names and the same `Main session`.

## 5. Write the config

`agentorch init` generates `.agentorch/agents.json` from the project's declared
roles when the file does not exist. If the audit produced a better team than
what the files declare, write the file yourself with the agreed tabs, keeping
`orchestrator` first:

```json
{
  "pi": { "executable": "pi", "bootstrap": "greet" },
  "tabs": [
    { "key": "orchestrator", "name": "Orchestrator", "role": "Coordinates the team." }
  ]
}
```

Then run `agentorch init` and check that every tab exists and has its agent.

## What this audit must not do

- Create a Herdr space or tab. That is `agentorch init`'s job.
- Start or kill agents.
- Change a role's meaning to fit a name.
- Present a guess as a detection. If the evidence is thin, say it is thin.
