# Security policy

## What torcha touches

Worth knowing before you report something, because the blast radius is unusual
for a CLI:

- It **executes local binaries** found on `PATH`: `herdr-app` and `hc` for the
  workspace, and `pi` to launch an agent.
- It **writes inside the project**: `.torcha/agents.json`, `registry.json`,
  the bootstrap prompts, handoff documents and `last-ls.json`.
- It **reads** the Pi session store under `~/.pi` to report context usage, and
  `models-store.json` for a model's window. Read-only.
- It **sends prompts to running agents** — `RELEVO` when it asks for a handoff,
  `CATCH_UP` when a human asks one to catch up.
- It makes **no network requests** of its own.

The last two together are the interesting surface: a handoff document, a
`README`, or anything an agent reads is untrusted input that can carry
instructions. torcha does not sanitise that, and cannot: it treats the working
tree as the source of truth on purpose. If you run it on a repository you do not
trust, expect the agents in it to read whatever is there.

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository (Security →
Report a vulnerability). If it is not enabled, open a normal issue asking for a
private channel and say only that you have a security report — no details until
there is somewhere private to put them.

Useful in a report:

- the version (`torcha --version`) and the commit if you are on a branch;
- which command, with which flags, against what kind of workspace;
- what an attacker gains: a write outside the project, a command executed that
  should not be, a secret disclosed, a tab closed that should not be;
- a reproduction that does not require your real workspace.

Please do not include real handoff documents or session transcripts. They carry
conversation content and often credentials.

## What is not a vulnerability

- An agent doing something unwise after reading an untrusted repository. That is
  the design: the tree is the source of truth. Report it as a documentation
  problem if the risk is not stated clearly where a user would read it.
- A prompt-injection payload in a handoff document. Same reason: torcha
  transports documents, it does not vet their content.
- Anything that requires an attacker who can already write to your project
  directory or your `PATH`.

## Supported versions

The latest minor release gets fixes. This project is pre-1.0: while the minor
version is `0`, a breaking change may arrive in a minor bump, and the changelog
says so.
