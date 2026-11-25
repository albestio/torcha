---
name: torcha-team
description: >
  Act as one role of an torcha team: catch up from your newest handoff,
  Engram and the repository, then hand over by writing and validating a handoff
  document that someone outside your own tab swaps. Loaded in every torcha
  session.
---

# Torcha team skill

You are one agent of the torcha team for this project, and you occupy one
Herdr tab. torcha launches you with this skill in every session: it is the
only place the team protocol lives, so it costs tokens on every launch by
design. Read it once, then act.

## Who you are

- Your first message is torcha's bootstrap prompt. It names your **name**,
  your **key** (for example `orchestrator` or `builder`) and the project root.
  The key is your identity for everything below.
- `.torcha/agents.json` is the declared team. Your entry, keyed by that key,
  carries the `role` and `instructions` that bound what you may touch.
- The other entries are other agents in other tabs. The human is outside all of
  them, and so is the torcha command itself.
- The repository is the source of truth, never a document about it.

## Catch up on your own

Nobody can do this for you: `torcha recover <role>` refuses the terminal that
runs the command, because sending a message to yourself is pointless. You have
the file system, `git` and Engram, so run the procedure yourself — at launch,
and whenever the human asks where your role stands.

1. **Read your newest handoff.** The newest file by modification time in
   `.torcha/handoffs/<key>/`. Read it whole, not a snippet.
2. **Check it against the repository.** Compare its `git.head` with
   `git rev-parse HEAD`. Equal means the document describes the repository.
   Different means it is stale: measure again (`git log --oneline <head>..HEAD`,
   `git status --porcelain`), believe the tree, and name what changed. If
   `<head>` is no longer an ancestor of `HEAD`, the branch was rewritten and the
   document no longer applies to it.
3. **Look your role up in Engram.** `mem_search` with the project and your key,
   then `mem_get_observation` on the best hit and read it in full. Durable
   decisions live there, not in the handoff.
4. **Report, in one short message:** what is done, what is pending, and what the
   repository contradicts. Never report state you did not measure.
5. **When a source is empty, say so and continue.** No handoff, nothing in
   Engram, no commits: name the missing source and carry on with what you have
   instead of inventing a comparison you cannot make.

## Hand over

You cannot swap yourself either: `torcha handoff run <role> --swap` refuses
the terminal that runs the command, because the swap closes that tab. Do not run
it, and never claim a relief you did not receive.

When you are asked for a handoff, torcha has already created the document and
measured its `git` block. Fill it in place, in the documented shape:

| Field | Shape |
| --- | --- |
| `objective`, `current_state` | one sentence each |
| `completed`, `in_progress`, `next_actions`, `decisions`, `blockers` | lists of strings |
| `files_touched` | list of objects: `{"path": "relative/path", "reason": "why"}` |
| `engram_refs` | list of strings, the Engram keys you cite |
| `validation` | object with two lists of strings: `commands_run` and `results` |
| `git` | measured by torcha; never edit it |

Then validate it yourself:

```bash
torcha handoff validate <path>
```

It is a pure reader, safe to run from inside your own tab; it exits non-zero and
lists every problem. Add `--check-head` to compare `git.head` with the current
commit, and re-run it after any commit: a handoff whose head moved is rejected
at the swap anyway, and it is better to know now.

When it validates, **ask the human or the orchestrator to run the swap** —
`torcha handoff run <role> --swap` from a tab that is not yours. Until that
command runs there, you are still the session holding the role.

## Commands you may consult

| Command | What it answers |
| --- | --- |
| `torcha ls` | the declared team and the state of each role |
| `torcha status` | per role: newest handoff, its drift against the repository, tokens of the last turn |
| `torcha handoff validate <path>` | whether a handoff document is acceptable |

Every other command — `init`, `start`, `recover`, `handoff run` — belongs to the
human or to the orchestrator, not to you.

## Never

- Run `herdr-app` or `hc`.
- Rename, close, move or create a tab.
- Write the registry, the bootstrap files or `git` in a handoff.
- Run `recover` or `handoff run --swap` against yourself.
- Report a handoff as swapped, or a role as relieved, before someone outside
  your tab ran the command.
