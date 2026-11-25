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
running agent: read your newest handoff (the newest file by modification time),
compare its `git.head` with `git rev-parse HEAD`, treat the working tree as the
source of truth, look the role up in Engram, and answer with what is done, what
is pending and what the repository contradicts. The message names the project
and the role, and it has a branch for each empty source: with no handoff, or
with nothing in Engram for that role, the agent is told to say so and continue
instead of reporting a comparison it could not make.

It does not replace the session. No tab is created, closed, moved or focused,
the session id stays the same, the registry is not written and no handoff is
opened or written; the answer arrives in the agent's own tab. Nothing is sent
unless the target is that role's own tab: the terminal is looked up in the live
workspace and must belong to the tab id the registry records for it, and to the
same name when both sides report one — otherwise the run is refused, says which
tab it found and asks for `agentorch start <role>`, because delivering one
role's handoff path to another agent is worse than not sending. A role with no
agent and an entry with no terminal are refused the same way, and the terminal
running the command is refused like the swap's guard. An agent that is mid-turn
is not reported as answered: the message is sent, queues behind its current
turn, and the run says so.

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

## Status: what decides a handoff

`agentorch status` still rules on divergence: per registered role it reports
`alive`, `down`, `missing` or `moved`, prints a summary and exits 1 when any role
is `missing` or `moved`. Those states, that rule, the exit code and `--json` do
not change. Under each role line it now adds the three facts that decide who
needs a handoff:

```
  orchestrator  alive       pid 500
      handoff  2h ago · head 8eff889 · prepared
      drift    2 commit(s) since that head · 1 uncommitted file(s)
      tokens   176,283 tokens · model demo-model · about 88% of a 200,000-token window
  worker_1      alive       pid 501
      handoff  no handoff: nothing to compare
      drift    nothing to compare: there is no handoff
      tokens   no session id in the registry: the tokens are unknown
2 of 2 role(s) alive
```

Where each number comes from (`[agentorch] `, which prefixes every line, is
omitted here):

| Line | Source |
| --- | --- |
| `handoff` | The newest file in `.agentorch/handoffs/<key>/` by modification time: its age from `created_at` (the file's mtime when the document has none) and the `git.head` the agent recorded. |
| `drift` | `git rev-list --count <handoff head>..HEAD` and `git status --porcelain`, measured in the project. A head that is no longer an ancestor of `HEAD` — a rebase, a rewritten branch — says so instead of printing a count it cannot count. |
| `tokens` | The last message of the role's Pi transcript that carries a `usage` block: `usage.totalTokens` with the model name. The transcript is found by its session id under Pi's own session store (`$PI_CODING_AGENT_DIR`, default `~/.pi/agent`), never by a guessed path. |
| percentage | The window and the percentage come from whichever source can be identified: the role's **own** presence block in its transcript first, otherwise the model's `contextWindow` from Pi's catalogue combined with the last turn's `totalTokens`, otherwise nothing but the tokens and the sentence `no context window known: no percentage`. |

Pi writes, beside each message, the figures its own status bar shows
(`contextPct`, `contextWindow`, `contextTokens`). That block is the number the
human already read, so it wins over anything agentorch could divide out — but
only when it can be identified as this role's own. A transcript also stores the
presence blocks of **other** sessions, because an intercom tool result is
recorded with the sender's block inside it, and taking one of those paints this
role with a foreign percentage: a role at 473,271 tokens of a 1,000,000-token
window read as `about 6%` until the identity check was added. A block is
accepted only when its `id` equals the role's session id, and the last such
block wins, as in the `tokens` line, because a session can change models.

Without a block of its own the catalogue supplies the window —
`models-store.json` first, then a hand-written `models.json`, keyed by model id
or name — and `totalTokens` is divided by it. A catalogue entry that is not a
positive integer is not an answer. When neither source yields a window, the
tokens appear alone and agentorch does not estimate: `no context window known:
no percentage`. A percentage Pi stated without stating the window is still
shown, as `about 6% of its context window` followed by `the window size is
unknown`.

Every source is optional and read-only. A role with no handoff, no session id, no
readable transcript, an unreadable document, or a store that is not there is said
per role on its own line; none of them makes the command fail, and nothing is
written or sent to an agent. `--json` carries the same fields as `handoff`,
`drift` and `usage` objects per role, with the raw values (`age_seconds`, `head`,
`commits`, `ancestor`, `dirty`, `dirty_files`, `total_tokens`,
`context_window`, `percent`) next to the sentence that explains them.

Because `drift` reports what `git status` says, keep agentorch's runtime state out
of the tree — this repository ignores `.agentorch/handoffs/` and
`.agentorch/registry.json` — or every role will read as dirty.

## What it does not do

- It does not start Pi in tabs that already existed; only in tabs it creates.
- It does not write handoffs, edit context or replace sessions; `status` only
  reads them.
- It is not published on PyPI.

## Development

```bash
uv run --extra test pytest -q
```

## License

GPL-3.0-or-later. See `LICENSE`.
