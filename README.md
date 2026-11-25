# agentorch

Bootstrap a team of [Pi](https://pi.dev) coding agents in
[Herdr](https://github.com/) workspaces.

`agentorch init` prepares a workspace for the project in the current directory:
it creates or recovers a Herdr space, creates the configured tabs, starts one Pi
session per tab with a bootstrap prompt, and leaves the focus on the first tab.

## Status

Early prototype: `init`, `discover`, `ls`, `status`, `doctor`, `start`,
`recover`, `rename`, `handoff` and `templates` exist, but there is no memory
integration yet. Do not expect stability.

## Requirements

- Python 3.10 or newer
- `git` on `PATH` (the project must be a git repository; `init` offers `git init`)
- `herdr-app` on `PATH`, with the Herdr desktop app running
- `pi` on `PATH`, for the bootstrap sessions

## Install

```bash
uv tool install .
# or, for development, so edits take effect without reinstalling:
uv tool install --editable .
```

Then, in any project directory:

```bash
agentorch init
```

Use `--project <path>` to target another directory instead of the current one.

## What it creates

Only `.agentorch/` in the target project:

```
.agentorch/
├── agents.json     # the team: one entry per tab (commit this)
├── registry.json   # Herdr ids for this machine (do not commit)
└── bootstrap/      # generated prompts (do not commit)
```

`init` writes a default `agents.json` if there is none. Edit it to change the
tabs, their names and their roles.

## Configuration

```json
{
  "pi": { "executable": "pi", "bootstrap": "greet" },
  "max_tabs": 10,
  "tabs": [
    { "key": "orchestrator", "name": "Orquestador", "role": "Coordinates the team." }
  ]
}
```

`max_tabs` is the maximum team size and defaults to 10. `init` writes it so it is
visible, and it can be raised or lowered. When the workspace holds more named tabs
with a live agent than the limit allows, the ones left out are named on stderr
instead of disappearing silently. The setup tab (`Agentorch`) and the tab the
command runs in never count as roles.

`pi.bootstrap` accepts `none`, `greet` or `recover`:

| Mode | What the agent receives | Cost |
| --- | --- | --- |
| `none` | No prompt at all | 0 calls |
| `greet` | Identity, role, project root; "wait for instructions" | 0 calls |
| `recover` | Engram lookup, handoff, repository inspection, `READY` | several calls |

The first tab must use `key: "orchestrator"`; it is the one that receives focus.

## Starting the agents

`agentorch start` brings up the agents of the registered roles that are not
running. `agentorch start <role>` touches only that role.

When an agent has died but its tab survives, the tab is replaced with
`tab.new --argv` and the session recorded in the registry is resumed; nothing is
ever typed into a shell. `--fresh` decides between that recorded session and a
new one.

When the tab or its terminal no longer exists, the role is reported as a failure
and nothing is created — unless `--recreate` is given, which creates the tab
again with the recorded `session_id` and stores the new ids and pid. Closing a
tab therefore means parking that role: `agentorch start` will not wake it, and
`--recreate` is how you bring it back without re-adopting the whole project.

A terminal that exists but is running something that is not a shell is never
closed and never typed into, whatever the flags say: that tab may hold someone
else's work. The role is reported as a failure.

| Flag | What it does |
| --- | --- |
| `--recreate` | Recreate a tab that has disappeared, resuming its session. Without it, a missing tab is a failure and nothing is created. |
| `--fresh` | A new session instead of resuming the recorded one. |

## Catching a running agent up

`agentorch recover <role>` sends one short catch-up message to that role's
running agent: read your newest handoff, compare its `git.head` with
`git rev-parse HEAD`, treat the working tree as the source of truth, look the
role up in Engram, and answer with what is done, what is pending and what the
repository contradicts.

It does not replace the session. No tab is created, closed, moved or focused,
the session id stays the same, the registry is not written and no handoff is
opened or written; the answer arrives in the agent's own tab. It needs an agent
already running in that terminal: a role with no agent is refused and needs
`agentorch start <role>`, and the terminal running the command is refused like
the swap's guard.

## Listing the team

`agentorch ls` answers "does `agents.json` match what is on screen?": one line
per declared role, in declaration order, with its key, name, terminal, state and
session; then the live tabs that are not in the team; then a summary with the
declared, adopted and alive counts. A declared role that was never adopted shows
`not adopted`, which is the case neither `status` nor `discover` can see.
`ls --json` gives the same data to scripts. It is read-only — it never creates,
closes, moves or focuses a tab and never writes the registry — and it does not
replace `agentorch status`, which stays the one that rules on divergence. When
the registry or `herdr-app ls` cannot be read it prints what it can, shows `?`
for the counts it cannot compute and exits non-zero.

## What it does not do

- It does not start Pi in tabs that already existed; only in tabs it creates.
- It does not manage handoffs, context or session replacement yet.
- It is not published on PyPI.

## Development

```bash
uv run --extra test pytest -q
```

## License

GPL-3.0-or-later. See `LICENSE`.
