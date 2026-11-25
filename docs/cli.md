# agentorch command line reference

What exactly you can type, what each thing does, and what each command exits
with. The README explains *why* and *when*; this file is the *what*.

It is not hand-maintained prose alone: `tests/test_agentorch.py` builds every
parser `agentorch.cli` defines — the top-level one and each subcommand's — and
fails, naming the option, when a flag, a positional or a subcommand exists in the
code and not here, or here and not in the code. A command added to the parser
without a section below is a red test, not a stale document.

## Conventions

- Every line of normal output starts with `[agentorch] ` and goes to stdout.
- Messages for the human — warnings and refusals — go to stderr with the same
  prefix, so stdout stays readable by a script.
- A failure caught by agentorch prints `[agentorch] ERROR: <reason>` to stderr.
- Every command accepts `-h` / `--help`, which prints its own help and exits 0.
  Those two are therefore not repeated in the tables below.
- Exit code **2** is argparse's own: an unknown flag, an unknown subcommand, a
  missing required argument or a malformed value. The message goes to stderr and
  nothing is executed.
- Exit code **1** is a refusal or a failed run; what went wrong is on stderr, as
  a `note` line or as `[agentorch] ERROR: <reason>`. Exit code **0** is success.

## Shared options

### `--project PATH`

Every command line accepts it, either at the top level or at its own level:
`agentorch --project PATH <command>` and `agentorch <command> --project PATH` are
the same thing. It decides which project is acted on — the directory holding
`.agentorch/` — and defaults to the current directory. The path must already
exist; a directory that does not raises
`The project directory does not exist: <path>` and exit 1, before anything else
happens.

The parsers declare it with argparse's `SUPPRESS` default, so a `--project`
given at one level is not overwritten by a level that omits it.

`agentorch handoff` is a group: `--project` belongs to it and must come **before**
the subcommand (`agentorch handoff --project PATH run <role>`). `handoff run` and
`handoff validate` define no `--project` of their own, so putting it after them
is a usage error, exit 2.

### `--json`

Where it exists it prints one JSON object on stdout, with nothing else on
stdout; human-facing notes still go to stderr. It exists on `init`, `discover`,
`status`, `ls`, `doctor`, `templates` and `handoff validate`. It is not a global
flag — `agentorch start --json` and `agentorch handoff run --json` are usage
errors. `init` is the one command whose normal output is a narration of what it
did rather than a report, so with `--json` that narration moves to stderr and the
object is left alone on stdout. The exit code does not change with `--json`.

## `agentorch`

The entry point. It takes the shared options, validates `--project`, and
dispatches to one subcommand; with no subcommand at all it prints the same help
`--help` prints; it never runs a command of its own.

```text
usage: agentorch [-h] [--version] [--project PATH] {init,discover,status,ls,doctor,start,recover,rename,templates,handoff} ...
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--version` | Print `Agentorch <version>` on stdout and exit 0. |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The help was printed, or `--version` printed the version. |
| 1 | `--project` points at something that is not an existing directory. |
| 2 | Usage error. |

## `agentorch init`

Create or recover the project's Herdr space, write a default `agents.json` when
there is none, optionally open the setup interview in the current terminal, create
the configured tabs and start one Pi session per tab.

It also reports, and only reports. A named live tab with an agent that
the configuration does not declare is named at the end of the run, after the
summary, with the role `init` would add for it: the key the role name derives and
the live name verbatim, which is what the skeleton would write. Nothing is added
to `agents.json`, no tab is created for it and the focus does not move: the file
is left for you to edit. A named tab with no agent is a different message from the
same run, the one that points at `agentorch start <role> --recreate`; the setup
tab, a tab Herdr still names after its number and the tab running the command are
never reported, and a workspace whose tabs all belong to the team says nothing
extra.

```text
usage: agentorch init [-h] [--plain] [--json] [--project PATH]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--plain` | Do not open the interview; materialise directly. Without it, an interview is offered when there is no `agents.json` or a role is still empty, and only when both stdin and stdout are a terminal. |
| `--json` | Print one JSON object on stdout — `{"space_id": …, "outside_team": […]}` — and move the run's progress lines to stderr, so stdout holds nothing else. Each `outside_team` entry carries the tab's `name`, `tab_id`, `terminal_id` and `app`, plus `suggested_role` with the `key` and `name` `init` would add. The list is empty when every live tab belongs to the team. The exit code does not change. |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Space and tabs reconciled, the registry says `ready`. |
| 1 | A precondition failed (not a git repository and the input is not interactive, `git` or `herdr-app` not on PATH), Herdr refused a step, the configuration is invalid, or the interview closed leaving roles unfilled — in that last case nothing is applied. |
| 2 | Usage error. |

## `agentorch discover`

Report what the project already declares and, optionally, what the live workspace
already runs, then print a proposed `agents.json`.

```text
usage: agentorch discover [-h] [--project PATH] [--live] [--json]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |
| `--live` | Include the tabs open in Herdr and the role each one appears to have. Names the named tabs it leaves out because no agent runs in them. |
| `--json` | Full JSON output, with tab and terminal ids, instead of the proposal printed as JSON alone. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | A proposal was printed, or there was nothing to propose — saying so is not a failure. |
| 1 | The workspace or the configuration could not be read (`herdr-app ls` failed, `max_tabs` is invalid). |
| 2 | Usage error. |

## `agentorch status`

Compare the registry with what Herdr reports now, and add per role the newest
handoff, the drift since it, and the tokens the role's last turn used.

```text
usage: agentorch status [-h] [--project PATH] [--json]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |
| `--json` | Print the registry state, every role with its `handoff`, `drift` and `usage` objects, and the summary, instead of the text report. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No role is `missing` or `moved`. |
| 1 | At least one role is `missing` or `moved` — the registry no longer describes reality — or the registry or the live workspace could not be read. |
| 2 | Usage error. |

## `agentorch ls`

List one line per role declared in `agents.json` against the live workspace, then
the live tabs outside the team, then the declared, adopted and alive counts.

```text
usage: agentorch ls [-h] [--project PATH] [--json]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |
| `--json` | Print the same data as `space`, `roles`, `undeclared`, `summary` and `errors`. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Everything it reads was read. Declared roles that are `not adopted` are information, not a failure. |
| 1 | The registry or `herdr-app ls` could not be read; the report is still printed with `?` where a count cannot be computed, and the reason is named on stderr. Also 1 when `agents.json` is invalid. |
| 2 | Usage error. |

## `agentorch doctor`

Check the preconditions agentorch needs — interpreter, `git`, repository,
`herdr-app`, `hc`, configuration, `pi`, the bootstrap files, registry,
writability — and report. It changes nothing.

```text
usage: agentorch doctor [-h] [--project PATH] [--json]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |
| `--json` | Print `checks` (each with `name`, `state`, `detail`) and a `summary` with the failing and warning check names. |

The `bootstrap` check compares each role's `.agentorch/bootstrap/<key>.md` with
what `pi.bootstrap` renders and names the role and the file when they disagree —
the same disagreement that makes `agentorch start` refuse the launch. It is a
`warn`, never a `fail`: the report does not change the exit code of a project
that is otherwise healthy, and `agentorch init` is what reconciles the files. A
project where no bootstrap file has been written yet is not reported.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No check is `fail`. A `warn` check — no `agents.json`, no registry, a bootstrap file that does not hold the configured mode — keeps the exit code at 0. |
| 1 | At least one check is `fail`. |
| 2 | Usage error. |

## `agentorch start`

Start the agents of the registered roles that are not running, closing and
recreating a role's tab when its terminal has no agent, and never typing a
command string into a shell.

```text
usage: agentorch start [-h] [--project PATH] [--fresh] [--recreate] [role]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |
| `role` | Start only this role. Optional: without it every registered role is visited. A role that is not in the registry is a failure, exit 1. |
| `--fresh` | A new session instead of resuming the recorded one. It decides between the two on both paths that create a tab: replacing the tab of a role whose agent died, and `--recreate`. |
| `--recreate` | Recreate the tabs that have been closed. Without it a missing tab is reported as a failure naming the flag, and nothing is created. The parser accepts it together with `--fresh`; the pair means "recreate the tab and start a new session". |

Both paths that launch compare the prompt on disk with what `pi.bootstrap`
renders: a role whose file holds another mode's text, or has no file at all, is
refused — naming the file and the mode it was written with — and nothing is
closed, created or written. `agentorch init` reconciles the file; with
`pi.bootstrap: "none"` no session is launched, so nothing is compared.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No role reported a problem. A role already running is counted as skipped, and skipping is not a failure. |
| 1 | At least one role failed: a tab or terminal missing without `--recreate`, a terminal that is not a shell, a bootstrap file that does not hold the configured mode, a tab that could not be created, an agent that did not appear in time, a role that is not in the registry, a space the registry names but Herdr no longer has, or a live workspace that could not be read at all. |
| 2 | Usage error. |

## `agentorch recover`

Send one catch-up message to a role's running agent and return, without touching
the tab, the session id, the registry or any handoff.

```text
usage: agentorch recover [-h] [--project PATH] role
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |
| `role` | The role in the registry, running in its own tab. Required. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The message was sent, or queued behind the agent's current turn — the run says which. |
| 1 | Nothing was sent: the role is not in the registry, the entry has no terminal, no agent is running there, the terminal is not in the tab the registry records for the role, the terminal is the one running this command, or herdr-core refused the send. |
| 2 | Usage error, including the missing `role`. |

## `agentorch rename`

Rename a role's tab in Herdr and record the new name in the registry.

```text
usage: agentorch rename [-h] [--project PATH] role name
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). |
| `role` | Role in the registry. Required. |
| `name` | New name of the tab. Required; a name that is empty after stripping is refused. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The tab was renamed and the registry updated. |
| 1 | The name is empty, the role is not in the registry, the entry has no `tab_id`, the tab no longer exists, or `herdr-app` could not be read or refused the rename. |
| 2 | Usage error, including a missing `role` or `name`. |

## `agentorch templates`

List the team templates bundled with the package.

```text
usage: agentorch templates [-h] [--project PATH] [--json]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above). `templates` reads only the bundled files, so the project has to exist but is not otherwise used. |
| `--json` | Print `{"templates": [...]}` instead of one line per template. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The templates were listed, or the JSON was printed. |
| 1 | No template is available at all. |
| 2 | Usage error. |

## `agentorch handoff`

The group for handoff documents. On its own it prints the help of its
subcommands and does nothing else.

```text
usage: agentorch handoff [-h] [--project PATH] {run,validate} ...
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `--project` | `--project PATH`, the project directory to act on; the current one by default. Shared by every command (see above), and here it must come before `run` or `validate`. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The help was printed. |
| 1 | `--project` points at something that is not an existing directory. |
| 2 | Usage error, including an unknown subcommand or a `--project` placed after `run` or `validate`. |

## `agentorch handoff run`

Ask a running agent to write its handoff, validate the result against the schema
and the repository, and optionally replace the session with it.

```text
usage: agentorch handoff run [-h] [--all] [--swap] [--use-existing] [--timeout TIMEOUT] [--force] [role]
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `role` | Role in the registry. Optional only because `--all` exists: one role or `--all`, not both, and neither is refused. These three rules are enforced by the command, not by the parser. |
| `--all` | Every role, in sequence. The run stops at the first failure and says the other roles were not touched. Cannot be combined with a `role`; the command refuses the pair. |
| `--swap` | Replace the session after validating the handoff: close the tab, relaunch with a new session id and the `recover` bootstrap, and mark the document `consumed`. Refused when `pi.bootstrap` is `none`, or when the role is no longer in `agents.json`. With `--swap` the agent is always asked again, even when a valid handoff already exists. |
| `--use-existing` | Reuse the newest handoff already on disk instead of asking the agent for another one. Requires `--swap`: without it the run is refused, because there is no session to replace and nothing is sent or written. Cannot be combined with `--force`; the command refuses the pair. The `git.head` check is not waived — a repository that moved since the document was written is refused, naming both shas — and a role with no valid prepared handoff falls back to asking, saying so. |
| `--timeout` | Seconds to wait per agent, as a float (300 by default). It bounds both the wait for the document to be written and the wait for a mid-turn agent to finish before a swap. |
| `--force` | Ask for the handoff again even when there is already a valid one. Without it, a role that already has a valid prepared handoff is skipped — except with `--swap`, which asks again regardless, so `--force` only changes a run without `--swap`. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Every targeted role ended with a written and validated document, or was skipped for already having one. |
| 1 | A flag combination the command refuses (`--use-existing` without `--swap`, `--use-existing` with `--force`, `--all` with a role, neither of them), a role that is not in the registry, a document that did not validate or whose `git.head` no longer matches the repository, or a swap that failed. |
| 2 | Usage error. |

## `agentorch handoff validate`

Validate one handoff document on disk: the schema, the ids, the secrets scan and,
on request, `git.head` against the current commit.

```text
usage: agentorch handoff validate [-h] [--json] [--check-head] path
```

### Arguments and options

| Name | What it does |
| --- | --- |
| `path` | Path to the handoff file. Required. |
| `--json` | Print `{"valid": ..., "problems": [...], "path": ...}` instead of the text report. |
| `--check-head` | Compare `git.head` with the current commit and add a problem naming both shas when the repository has moved. When the current commit cannot be read, the run says it was not checked and does not invent a problem. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The document is valid. |
| 1 | At least one problem, or the file does not exist or is not readable JSON. |
| 2 | Usage error, including the missing `path`. |
