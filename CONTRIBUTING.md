# Contributing

Thanks for looking. This document is about getting a change merged without
wasting your time.

## What this is

`torcha` adopts a team of coding agents that already live in Herdr tabs,
writes down who they are, and lets them hand over to a successor without losing
what they knew. It shells out to `herdr-app` and `hc`; it never talks to a model
itself.

## Requirements

- Python 3.10 or newer.
- [`uv`](https://docs.astral.sh/uv/) is recommended, not required.
- To use it against a real workspace: Herdr (`herdr-app`, `hc`) and Pi (`pi`) on
  `PATH`. To work on the code: none of that is needed.

## Development setup

```bash
git clone <this repository> && cd torcha
uv tool install --editable . --force   # installs the `torcha` command from your tree
# or, without uv:
python -m pip install -e ".[test]"
```

An editable install means your edits are live: there is no build step while you
work. Two things do not refresh on their own:

- the recorded and reported version, which is cached by the tool installer
  (`uv tool install --editable . --force --no-cache` after bumping it);
- the skill files, only if you installed from a wheel instead of the tree.

## Tests

```bash
python -m pytest -q
```

The suite is hermetic. It runs every command against a fake `herdr-app` and `hc`
built inside `tests/test_torcha.py`, so it needs no workspace, no terminal and
no network. A test that needs a real binary must **skip** when it is missing,
never fail: someone cloning this repository on a fresh machine must get a green
run.

Two exceptions worth knowing:

- `test_the_wheel_carries_the_files_a_launch_depends_on` builds a wheel with `uv`
  and inspects it, because every launch passes `--skill <package>/skills/…` and
  an editable install hides a package that ships without it. It skips when `uv`
  is unavailable.
- Nothing in the suite reads your real `~/.pi` store: the fixture for it points
  at a temporary directory.

## What a change needs

- **Tests first** for a behaviour change: one failing test per rule, then the
  fix. A change that only moves text around says so and still runs the suite.
- **A documented option**: `torcha` has a test that fails when a parser
  option is not in `docs/cli.md`. Add the row or the suite will tell you.
- **The changelog**: `CHANGELOG.md` has an entry per release, grouped by added,
  changed and fixed. Add your line under the unreleased heading if there is one.
- **English** in code, messages, comments, prompts and documentation. Tab names
  and handoff documents belong to the agent that wrote them, so they are whatever
  they are.
- **A small diff.** One behaviour per pull request. If a change needs three
  unrelated fixes, that is three pull requests.

## Where things live

| Path | What |
| --- | --- |
| `src/torcha/` | the package; one module per concern, `commands/` per command |
| `src/torcha/skills/` | the two prompts packaged with the tool: the setup interview and the team skill every agent loads |
| `tests/test_torcha.py` | the whole suite, including the fake Herdr |
| `docs/cli.md` | every command, option and exit code |
| `odd/tasks/torcha-improvements.md` | the feature document: specs, tasks with the commit that holds each, and a log of decisions and field bugs |

## Proposing something bigger

Open an issue before writing code when the change alters a contract — a flag's
meaning, the shape of `agents.json` or `registry.json`, what a prompt asks an
agent to do. Those are cheap to discuss and expensive to undo.

For a bug, the most useful report says what you ran, what happened, what you
expected, and the output of `torcha --version` and `torcha doctor`. Never
paste a handoff document or a session transcript without reading it first: they
carry whatever was in the conversation.
