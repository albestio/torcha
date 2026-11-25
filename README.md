# agentorch

Bootstrap a team of [Pi](https://pi.dev) coding agents in
[Herdr](https://github.com/) workspaces.

`agentorch init` prepares a workspace for the project in the current directory:
it creates or recovers a Herdr space, creates the configured tabs, starts one Pi
session per tab with a bootstrap prompt, and leaves the focus on the first tab.

## Status

Early prototype: `init`, `discover`, `status`, `doctor`, `start`, `rename`,
`handoff` and `templates` exist, but there is no memory integration yet. Do not
expect stability.

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
ever typed into a shell. The same happens when the tab or its terminal no longer
exists at all — Herdr was closed, the tab was deleted — which is the most common
accident and why recreating is the **default**: the tab is created again with the
recorded `session_id`, the registry is updated with the new ids and pid, and the
role is reported as recreated. `--fresh` decides between that recorded session
and a new one, in both paths.

A terminal that exists but is running something that is not a shell is never
closed and never typed into, whatever the flags say: that tab may hold someone
else's work. The role is reported as a failure.

| Flag | What it does |
| --- | --- |
| `--recreate` | Recreate a tab that has disappeared, resuming its session. This is the default; the flag is still accepted so existing habits and aliases keep working. |
| `--no-recreate` | Refuse instead: the role is reported as a failure, the registry is left untouched, and the run exits 1. |
| `--fresh` | A new session instead of resuming the recorded one. |

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
