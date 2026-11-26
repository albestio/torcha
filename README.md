# torcha

[![tests](https://github.com/albestio/torcha/actions/workflows/ci.yml/badge.svg)](https://github.com/albestio/torcha/actions/workflows/ci.yml)

Give your coding agents a team, a memory and a handover.

`torcha` coordinates a team of [Pi](https://pi.dev) coding agents living in
[Herdr](https://herdr.dev) tabs: it records who they are, brings them up, hands
one over to a successor, and reports what state each is in.

It is **agnostic about the model** — Pi can point at Anthropic, OpenAI, a local
server or anything else, and torcha neither reads nor configures that — and it is
coupled to **one program**: the `pi` binary and the flags it accepts.

`torcha init` prepares a workspace for the project in the current directory:
it creates or recovers a Herdr space, creates the configured tabs, starts one Pi
session per tab with a bootstrap prompt, and leaves the focus on the first tab.

## Status

Early prototype: `init`, `discover`, `ls`, `status`, `doctor`, `start`,
`recover`, `rename`, `handoff` and `templates` exist, but there is no memory
integration yet. Do not expect stability.

[`docs/cli.md`](docs/cli.md) is the reference: every command, its exact usage,
what each flag and positional does and the exit codes it can return. This README
is the other half — when and why to reach for each command — and a test keeps the
reference from falling behind the code in silence.

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
torcha init
```

Use `--project <path>` to target another directory instead of the current one.

## What it creates

Only `.torcha/` in the target project:

```
.torcha/
├── agents.json     # the team: one entry per tab (commit this)
├── registry.json   # Herdr ids for this machine (do not commit)
└── bootstrap/      # generated prompts (do not commit)
```

`init` writes a default `agents.json` if there is none. Edit it to change the
tabs, their names and their roles.

## Migrating a project adopted before the rename

A project set up before the rename still keeps its data in `.agentorch/`. The
tool does not move it on its own: every command refuses that layout and points
at `torcha migrate`, which copies `.agentorch/` to `.torcha/`, verifies the copy
and leaves the original untouched. Run it once per project, check that the tool
works against `.torcha/`, and remove the old directory yourself when you are
satisfied.

That file is seeded from what the workspace already runs — the named tabs with a
live agent — and after that `init` only reports. A named live tab with an agent
that the configuration does not declare is named at the end of every run, after
the summary, with the role it would add: the key that role name derives and the
live name verbatim, which is exactly what the skeleton would write. Nothing is
added to the file, no tab is created for it and the focus does not move; the edit
is yours. `torcha init --json` carries the same list, with the tab and
terminal ids, for a script. A named tab whose agent is gone is a different
warning, the one that points at `torcha start <role> --recreate`, and the tabs
that are never roles — the setup tab, Herdr's bare numeric default and the tab
running the command — are not reported at all.

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
instead of disappearing silently. The setup tab (`Torcha`) and the tab the
command runs in never count as roles.

`pi.bootstrap` accepts `none`, `greet` or `recover`:

| Mode | What the agent receives | Cost |
| --- | --- | --- |
| `none` | No prompt at all | 0 calls |
| `greet` | Identity, role, project root; "wait for instructions" | 0 calls |
| `recover` | Engram lookup, handoff, repository inspection, `READY` | several calls |

The mode is not consulted at launch: `init` renders it into
`.torcha/bootstrap/<key>.md`, and that file is what `pi` reads as its first
message. The file is therefore authoritative. Editing `agents.json` from `greet`
to `recover` changes nothing until `torcha init` renders the file again, so
`torcha start` refuses to launch a role whose file does not hold exactly what
the configured mode renders — or is missing — naming the file and the mode it was
written with, then leaving the tab, the registry and the file untouched.
`torcha doctor` reports the same disagreement as a finding without failing a
healthy project, and `torcha init` is the way to reconcile it. The swap is the
one exception, with a reason: it renders `recover` for the role it is about to
relaunch, so its file always matches.

The first tab must use `key: "orchestrator"`; it is the one that receives focus.

## The team skill, loaded everywhere

Every agent `torcha` launches receives the packaged team skill as well, with
`--skill <package>/skills/torcha/SKILL.md`, whatever `pi.bootstrap` says. It
teaches the agent what no command can do for it: how to catch up on its own from
its newest handoff, `git rev-parse HEAD` and Engram, and how to hand over — fill
the document torcha created, validate it with `torcha handoff validate`,
then ask the human or the orchestrator to run the swap, because neither the swap
nor `torcha recover` can target the tab running the command. The path comes
from the package, so the target project needs nothing. This costs tokens in
every session, by design: a skill an agent must discover on demand is one it can
skip. With `pi.bootstrap: "none"` no session is launched, so no skill is loaded
either.

## Starting the agents

`torcha start` brings up the agents of the registered roles that are not
running. `torcha start <role>` touches only that role.

When an agent has died but its tab survives, the tab is replaced with
`tab.new --argv` and the session recorded in the registry is resumed; nothing is
ever typed into a shell. `--fresh` decides between that recorded session and a
new one.

When the tab or its terminal no longer exists, the role is reported as a failure
and nothing is created — unless `--recreate` is given, which creates the tab
again with the recorded `session_id` and stores the new ids and pid. Closing a
tab therefore means parking that role: `torcha start` will not wake it, and
`--recreate` is how you bring it back without re-adopting the whole project.

A terminal that exists but is running something that is not a shell is never
closed and never typed into, whatever the flags say: that tab may hold someone
else's work. The role is reported as a failure.

Every flag of `torcha start`, what it does on each path and the exit codes are
in [`docs/cli.md`](docs/cli.md#torcha-start); the paragraphs above are the
workflow those flags implement.

## Catching a running agent up

`torcha recover <role>` sends one short catch-up message to that role's
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
tab it found and asks for `torcha start <role>`, because delivering one
role's handoff path to another agent is worse than not sending. A role with no
agent and an entry with no terminal are refused the same way, and the terminal
running the command is refused like the swap's guard. An agent that is mid-turn
is not reported as answered: the message is sent, queues behind its current
turn, and the run says so.

## Listing the team

`torcha ls` answers "does `agents.json` match what is on screen?": one line
per declared role, in declaration order, with its key, name, terminal, state and
session; then the live tabs that are not in the team; then a summary with the
declared, adopted and alive counts. A declared role that was never adopted shows
`not adopted`, which is the case neither `status` nor `discover` can see.
`ls --json` gives the same data to scripts. It is read-only — it never creates,
closes, moves or focuses a tab and never writes the registry — and it does not
replace `torcha status`, which stays the one that rules on divergence. When
the registry or `herdr-app ls` cannot be read it prints what it can, shows `?`
for the counts it cannot compute and exits non-zero.

## Asking for a handoff

`torcha handoff run <role>` asks a running agent to write its handoff. It
creates the document with the `git` block measured by torcha, sends `RELEVO`
— a prompt listing every field and the shape each one has — waits for the agent
to fill it in, and validates the result: the schema, the ids, the secrets scan,
and the `git.head` against the repository as it is now. A document that declares
a head the repository has moved past is refused with both shas named, because a
successor that compares the handoff with `git rev-parse HEAD` would otherwise
inherit a state that is no longer true. Without `--swap` the document is left
`prepared`; a role that already has a valid one is skipped, unless `--force`
asks for a fresh one anyway.

`--swap` goes one step further: it closes the tab, relaunches the session with a
new session id and the `recover` bootstrap, and marks the accepted document
`consumed`, so the successor reads the document it was handed instead of being
greeted into an empty context.

After a relief the document is already written and validated, so asking for it
again costs a turn and rewrites what was just agreed. `--use-existing` reuses
the newest handoff that already validates instead: nothing is sent to the agent,
no new document is created and the document is left exactly as written. The run
states the document's age in words (`reusing the handoff written 2h ago`), so
reusing something from last week is visible rather than silent.

Every flag of `torcha handoff run` — including `--all` and `--timeout`, and
the combinations the command refuses — is in
[`docs/cli.md`](docs/cli.md#torcha-handoff-run); the paragraphs above are the
relief this implements.

Reuse is only as good as the document on disk. The `git.head` check is not
waived: a repository that moved since the document was written is refused,
naming both shas and asking for a new handoff. The file is also validated
again before it is used, so one that stopped being `prepared`, or whose
`agent_id` or `project` no longer matches, is not eligible and an older valid
document is chosen instead of it. And when a role has no valid prepared handoff
at all, the run says it is falling back to asking the agent — `no valid prepared
handoff on disk; falling back to asking the agent` — instead of quietly doing
the other thing.

## Status: what decides a handoff

`torcha status` still rules on divergence: per registered role it reports
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

Where each number comes from (`[torcha] `, which prefixes every line, is
omitted here):

| Line | Source |
| --- | --- |
| `handoff` | The newest file in `.torcha/handoffs/<key>/` by modification time: its age from `created_at` (the file's mtime when the document has none) and the `git.head` the agent recorded. |
| `drift` | `git rev-list --count <handoff head>..HEAD` and `git status --porcelain`, measured in the project. A head that is no longer an ancestor of `HEAD` — a rebase, a rewritten branch — says so instead of printing a count it cannot count. |
| `tokens` | The last message of the role's Pi transcript that carries a `usage` block: `usage.totalTokens` with the model name. The transcript is found by its session id under Pi's own session store (`$PI_CODING_AGENT_DIR`, default `~/.pi/agent`), never by a guessed path. |
| percentage | The window and the percentage come from whichever source can be identified: the role's **own** presence block in its transcript first, otherwise the model's `contextWindow` from Pi's catalogue combined with the last turn's `totalTokens`, otherwise nothing but the tokens and the sentence `no context window known: no percentage`. |

Pi writes, beside each message, the figures its own status bar shows
(`contextPct`, `contextWindow`, `contextTokens`). That block is the number the
human already read, so it wins over anything torcha could divide out — but
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
tokens appear alone and torcha does not estimate: `no context window known:
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

Because `drift` reports what `git status` says, keep torcha's runtime state out
of the tree — this repository ignores `.torcha/handoffs/` and
`.torcha/registry.json` — or every role will read as dirty.

## What it is not

- **Not a runner for other agent CLIs.** It drives `pi`. Claude Code and Codex
  are different programs with different flags and their own session stores; using
  them would need an adapter, and none ships today.
- **Not a model or provider manager.** Choosing a model, holding a key and
  talking to an API are Pi's job. torcha launches a process and reads what that
  process leaves on disk.
- **Not a terminal multiplexer.** Herdr owns tabs, panes and focus; torcha asks
  it to create, close and select things.
- **Not a memory of its own.** Durable knowledge belongs to Engram; torcha keeps
  the registry, the bootstrap files and the handoff documents, nothing else.
- **Not automatic about migrations.** A project whose data still sits in the old
  directory is refused with instructions, never migrated on the quiet.
- **Not on PyPI.** Install it from the repository.

## Development

```bash
uv run --extra test pytest -q
```

The suite is hermetic: it runs against a fake `herdr-app`/`hc` written in the test
file and needs no workspace, no terminal and no network. Someone cloning this
repository on a fresh machine gets a green run — a test that needs a real binary
skips.

[`CONTRIBUTING.md`](CONTRIBUTING.md) has the setup, the rules a change has to
meet, and where each piece lives. [`docs/cli.md`](docs/cli.md) is the reference
for every command and option, and a test fails when it falls behind the code.

## Security

It shells out to local binaries and sends prompts to running agents; what that
means, and how to report a problem privately, is in [`SECURITY.md`](SECURITY.md).

## License

GPL-3.0-or-later. See `LICENSE`.
