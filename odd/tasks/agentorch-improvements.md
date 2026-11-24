# agentorch improvements

Feature: close the defects that the first real end-to-end runs exposed in `agentorch` 0.3.0, before the first commit.
Read this file until `## Log`, then work only on the task you were given.

## Specs

**S1 — `start` must not type a program into a shell.** When a role's tab still exists and its terminal no longer has an agent, `agentorch start` must launch Pi by replacing that tab, never by injecting a command string. Evidence of the defect: `src/agentorch/commands/start.py:130` built `" ".join(shlex.quote(part) for part in argv)` and passed it to `send_text`; `hc send` wraps injected text in `<hc from="…">…</hc>`, which a bash receives literally and dies with `syntax error near unexpected token 'newline'`.
Observable: for that role the run issues `herdr-app do tab.close --id <old tab> --confirmed true` and `herdr-app do tab.new --name <role> --space <space_id> --folder <project> --argv '["pi","--session-id",…,"@.agentorch/bootstrap/<key>.md"]'`; **no** text is injected into any terminal for that role; the registry holds the new `tab_id`, `terminal_id`, `pid` and `session_id`; exit code 0.

**S2 — `--recreate` must honour `--fresh`.** `_recreate` never received `fresh`, so `agentorch start --recreate --fresh` silently resumed the old session instead of starting a new one.
Observable: with `fresh=True` the `--session-id` in the created tab's `--argv` differs from the registry's previous id and the registry is updated to the new id; without `fresh`, both equal the previous id ("resume the conversation, do not start another").

**S3 — the `start` behaviours that already worked must keep working.** A role whose agent is already running is reported as `ya está en marcha` and skipped. A terminal that is not a shell is refused with `el terminal no es un shell` and is not closed. With `--recreate` omitted, a missing tab reports the hint containing `--recreate` and the run fails. `start <role>` touches only that role. With `pi.bootstrap: "none"`, the role is skipped instead of launched.

**S4 — `_recreate` must take the ids from `herdr-app ls`, not from `tab.new`'s echo.** `init` and `_swap` both re-read the workspace (`wait_for_apps` + `extract_tab_ids`) because the echo is not the settled truth. A test must make the fake return a stale id from `tab.new` and show the registry keeps the one `ls` reports.

**S5 — the `--recreate` log line must state what actually happened.** It updated `entry["session_id"]` and then tested that same value to choose between `reanudada` and `sesión nueva`, so it always said `reanudada`. A fresh recreate must be reported as a new session.

**S6 — the `git` block a swap accepts must match the repository now.** `validate_handoff` checks the shape of `git` but compares it with nothing; only the manual `handoff validate --check-head` looked at the repository. So the document that `handoff run --swap` accepted and handed to a successor could state a `git.head` that no longer existed, disarming the successor's own staleness rule ("compare its `git.head` with `git rev-parse HEAD`").
Observable: `handoff run <role>` fails with a problem naming both shas when the repository HEAD differs from the `git.head` the agent wrote, and succeeds when they match; `RELEVO` states that `git` is measured by agentorch and must not be edited; a handoff that validates today still validates when HEAD has not moved.

**S7 — the skeleton must list every named tab with a live agent, except the setup tab.** `skeleton_from_live` (`src/agentorch/live.py:160`) ends with `for tab in ordered[:max_tabs]` and `max_tabs: int = 5`, so a team of six loses its sixth member silently. Observed in `career-ops` on 2026-11-24: seven tabs, all `renamed` with a live agent — `Senior Orchestrator, Scout, Communicator, Auditor, Builder, Coach, Agentorch` — and `agents.json` came out with five, `Coach` missing. `Agentorch` is the setup tab a previous interview renamed via `_mark_setup_tab`; it must never be adopted as a role.
Observable: with that same live state the skeleton contains `Coach` and does not contain `Agentorch`; any tab left out is named on stderr instead of dropped in silence. `proposal_from_live`, which shares the cap, follows the same rule for `discover` and for `init`'s fallback path.

**S8 — the team size limit is 10 and it is configurable.** The limit is not a hidden constant: the default is **10** and a project can change it in its own configuration.
Observable: with no configuration present the limit is 10 (a live state with twelve named role tabs yields ten, and the two left out are named on stderr); with the limit set to a different positive integer in the configuration, that value is used; an invalid value (zero, negative, not an integer) is refused with a diagnostic rather than silently ignored.
Note for the implementer: at `init` time the configuration does not exist yet — `start_interview` builds the skeleton *before* `write_default_config` — so the value has to come from the existing configuration **when there is one** and from the default otherwise. Do not invent a second config file for it.

**S9 — every text agentorch writes to the human is in English.** All CLI output (`log`, `note`, `error` in `src/agentorch/output.py` callers across `commands/*.py`), the argparse help and usage strings, and `RELEVO` — the prompt agentorch sends to a running agent — are English. Observed today: `Tab existente recuperada`, `ya está en marcha`, `el terminal no es un shell; no se envía nada a ciegas`, `deja fuera`, `El space … del registro ya no existe`, `No abrir la entrevista; materializar directamente.`
Observable: no CLI output produced by the package contains Spanish prose; `agentorch --help` and every `agentorch <cmd> --help` are English; `RELEVO` is English. Handoff documents written by the agents and the arbitrary text of tab names are not affected. Internal code comments and docstrings are out of scope: this is about what the tool says, not how it is written.

## Tasks

| ID | Specs | Route | Commit | Task |
| --- | --- | --- | --- | --- |
| T1 | S1, S2, S3, S4, S5 | writer `gentle-ai-worker`, then full suite | not committed (repo has no commits) | Rewrite `start`'s launch path over `tab.close` + `tab.new --argv`, honour `--fresh` in `_recreate`, take the ids from `ls`, fix the recreate log label, and refresh the stale test expectations. **Done**: 153 green. |
| T2 | S6 | writer `gentle-ai-worker`, then independent verify (Risk item 3: `RELEVO` is a mirrored prompt) | not committed | Pin the `git` block in `RELEVO` and make the swap reject a handoff whose `git.head` no longer matches the repository. **Done**: 157 green, verify pending. |
| T3 | S7, S8 | writer `gentle-ai-worker` | not committed | Raise the team limit to a configurable 10, exclude the setup tab by its marker and by the tab running the command, and name any tab left out. **Done**: 169 green. |
| T4 | S9 | writer `gentle-ai-worker`, own commit after T1-T3 land | not committed | Translate every CLI message, help text and `RELEVO` into English and update the tests that assert those strings. |

**Open design question (not a spec yet)**: `discover --live` *sees* every live tab, but `init` never promotes an unlisted live tab into a role. Detection exists only when the skeleton is seeded (no `agents.json`); afterwards `init` reconciles what the file declares and stays silent about the rest, which is why a live `Coach` tab went unnoticed across two runs. Whether `init` (or `discover`) should report "this project has N named tabs with a live agent that are not in the team" is a product decision, deliberately not taken here. Evidence: `src/agentorch/commands/init.py` (`unfilled_roles`, `start_interview`) and the career-ops case in L8/L11.

## Log

**L1** (user, verbatim): "Lanza los subagentes que necesites para analizar, planificar y luego implementar mejoras"

**L2** (context, end-to-end run of 2026-11-24 in `/home/albestio/Code/tabcabin`): `init` with a real interview and `handoff run <role> --swap` both work. Two defects remained open and two more were found in that run: `start.py` typed its launch into a shell, so `start` could not work and its two `--recreate` tests were the only reds; an agent-written handoff carried a stray `git_branch: null`; and a swap launched the successor with the configured `greet` bootstrap, so it never read the handoff it had just been given (now `_swap` writes `recover`, and the successor verified `git.head` and declared `READY`).

**L3** (user, verbatim): "Me refiero principalmente a arreglar bugs. Tienes acceso a las sesiones de tabcabin via intercom"
→ Scope decision: only defects. Refinements (dead code, inlining, renaming) are out unless a task needs them to land its fix. The tabcabin agents are available over intercom as field evidence and as the place to reproduce a fix, which supersedes the earlier restriction that this conversation must not talk to tabcabin.

**L4** (correction, 2026-11-24): the `git_branch: null` defect reported in L2 does **not** exist as stated. The document stores the branch at `git.branch`; the inspection script read a non-existent top-level `git_branch` key and printed `None`. `validate_handoff` (`src/agentorch/handoff.py:148`) already rejects an empty or non-string `branch`.

**L5** (evidence, 2026-11-24): the two red `start` tests failed for two different reasons. `test_start_recreate_fresh_starts_a_new_session` was a real bug: `_recreate` ignored `fresh`. `test_start_recreate_resumes_the_old_session` was a stale expectation: it asserted `entry["pid"] == 9000`, the fake's artifact for the old typed launch.

**L6** (evidence, audit `mwv9q8mo-1-ccfu`, 2026-11-24): the two reds were not caused by the typed transport. `_recreate` already used `tab.new --argv`; it failed because it ignored `fresh` (S2) and because it trusted `tab.new`'s echo instead of re-reading `ls` (S4). The typed path only affected the *other* branch, the one with a live shell. Also `start.py:110` always logged `reanudada` (S5), and `RELEVO` never pinned the `git` object, which is how a stray `git_branch: null` survived validation (S6). Dead code (`send_keys`, `terminals_of_space`, `bootstrap.py import json`) is a refinement, out of scope: only what a fix leaves behind gets removed. `is_shell` stays: S3 needs the refusal for a terminal running something unknown.

**L7** (decision, 2026-11-24): S6 narrowed while briefing T2. Rejecting unknown top-level keys is a refinement that widens the contract's blast radius for little gain; the defect is that the accepted handoff's `git` block was never compared with the repository. The stray `git_branch: null` was only the symptom.

**L12** (independent verify `mwvahtfd-5-c6bi`, 2026-11-24): S1-S8 all PASS, S9 out of scope. It found two blockers in the just-committed tree, both now fixed: a recreated tab was resolved **by name only**, so two tabs sharing a role name made the registry adopt the other one (reproduced: it ended on a bare shell and orphaned the new session), and a failing `tab.new` escaped `start()` while the registry kept the id of the tab that had just been closed. Resolution is now by identity: the new tab is the one `ls` shows with that name and whose id was not in the space before the create, with the echo only as a last resort; and a failed create clears the entry before reporting. Two tests pin it. Still open from that report: `discover` never passes `own_tab_id`, so the invoking tab can be proposed as a role; the `--argv` session id in S2 is not asserted by the existing tests (only the registry one); `_create_tab`'s `config` argument is unused; and the suite's 169-green claim depends on `pi` being on `PATH` for `test_a_loose_tab_in_the_space_is_not_a_team_tab`.

**L11** (user, verbatim): "Pensaba que teníamos una forma de detectar agentes adicionales. Guardamos y seguimos mañana"
→ Recorded as an open design question, not a defect: live-tab detection exists, live-tab *promotion* does not. Session closed with T4 (S9, English texts) pending for the next session, plus the three carried-over items noted in L10 and the two T3 risks (the echoed-id fallback has no test; excluding the own tab can leave a skeleton without an orchestrator when `init` runs from a team tab).

**L10** (user, verbatim): "por cierto, creo que en los logs de agentorch debería tener todo textos en inglés"
→ S9 added. Sequenced as its own unit and its own commit, after the bug fixes, because it rewrites every message the suite asserts on and would otherwise bury those fixes in a mechanical diff. `RELEVO` is included: it is a prompt agentorch authors, and it changes what the agents read (risk item 3), so it gets verified like any other contract.

**L9** (user, verbatim): "Max tabs debería ser 10, y debería poder cambiarse desde alguna config sencillamente"
→ S8 added: the limit becomes 10 by default and configurable in the project's own configuration, on top of the exclusion of the setup tab and the loud reporting that S7 already required.

**L8** (field bug, 2026-11-24, project `career-ops`): the interview did not list the `Coach` tab although it had a live Pi session. Reproduced read-only against that workspace: `inspect_space` returns seven tabs, all `renamed` with `has_agent`, and `skeleton_from_live` returns five because of `ordered[:max_tabs]` with the default 5. `Coach` is the sixth; `Agentorch` is the seventh, a setup tab left renamed by a previous interview. The cap fails both ways: it drops a real role and does not filter the setup tab.
