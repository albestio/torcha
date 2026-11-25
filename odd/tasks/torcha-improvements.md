# torcha improvements

Feature: close the defects that the first real end-to-end runs exposed in `torcha` 0.3.0, before the first commit.
Read this file until `## Log`, then work only on the task you were given.

## Specs

**S1 — `start` must not type a program into a shell.** When a role's tab still exists and its terminal no longer has an agent, `torcha start` must launch Pi by replacing that tab, never by injecting a command string. Evidence of the defect: `src/torcha/commands/start.py:130` built `" ".join(shlex.quote(part) for part in argv)` and passed it to `send_text`; `hc send` wraps injected text in `<hc from="…">…</hc>`, which a bash receives literally and dies with `syntax error near unexpected token 'newline'`.
Observable: for that role the run issues `herdr-app do tab.close --id <old tab> --confirmed true` and `herdr-app do tab.new --name <role> --space <space_id> --folder <project> --argv '["pi","--session-id",…,"@.torcha/bootstrap/<key>.md"]'`; **no** text is injected into any terminal for that role; the registry holds the new `tab_id`, `terminal_id`, `pid` and `session_id`; exit code 0.

**S2 — `--recreate` must honour `--fresh`.** `_recreate` never received `fresh`, so `torcha start --recreate --fresh` silently resumed the old session instead of starting a new one.
Observable: with `fresh=True` the `--session-id` in the created tab's `--argv` differs from the registry's previous id and the registry is updated to the new id; without `fresh`, both equal the previous id ("resume the conversation, do not start another").

**S3 — the `start` behaviours that already worked must keep working.** A role whose agent is already running is reported as `ya está en marcha` and skipped. A terminal that is not a shell is refused with `el terminal no es un shell` and is not closed. With `--recreate` omitted, a missing tab reports the hint containing `--recreate` and the run fails. `start <role>` touches only that role. With `pi.bootstrap: "none"`, the role is skipped instead of launched.

**S4 — `_recreate` must take the ids from `herdr-app ls`, not from `tab.new`'s echo.** `init` and `_swap` both re-read the workspace (`wait_for_apps` + `extract_tab_ids`) because the echo is not the settled truth. A test must make the fake return a stale id from `tab.new` and show the registry keeps the one `ls` reports.

**S5 — the `--recreate` log line must state what actually happened.** It updated `entry["session_id"]` and then tested that same value to choose between `reanudada` and `sesión nueva`, so it always said `reanudada`. A fresh recreate must be reported as a new session.

**S6 — the `git` block a swap accepts must match the repository now.** `validate_handoff` checks the shape of `git` but compares it with nothing; only the manual `handoff validate --check-head` looked at the repository. So the document that `handoff run --swap` accepted and handed to a successor could state a `git.head` that no longer existed, disarming the successor's own staleness rule ("compare its `git.head` with `git rev-parse HEAD`").
Observable: `handoff run <role>` fails with a problem naming both shas when the repository HEAD differs from the `git.head` the agent wrote, and succeeds when they match; `RELEVO` states that `git` is measured by torcha and must not be edited; a handoff that validates today still validates when HEAD has not moved.

**S7 — the skeleton must list every named tab with a live agent, except the setup tab.** `skeleton_from_live` (`src/torcha/live.py:160`) ends with `for tab in ordered[:max_tabs]` and `max_tabs: int = 5`, so a team of six loses its sixth member silently. Observed in `career-ops` on 2026-11-24: seven tabs, all `renamed` with a live agent — `Senior Orchestrator, Scout, Communicator, Auditor, Builder, Coach, Torcha` — and `agents.json` came out with five, `Coach` missing. `Torcha` is the setup tab a previous interview renamed via `_mark_setup_tab`; it must never be adopted as a role.
Observable: with that same live state the skeleton contains `Coach` and does not contain `Torcha`; any tab left out is named on stderr instead of dropped in silence. `proposal_from_live`, which shares the cap, follows the same rule for `discover` and for `init`'s fallback path.

**S8 — the team size limit is 10 and it is configurable.** The limit is not a hidden constant: the default is **10** and a project can change it in its own configuration.
Observable: with no configuration present the limit is 10 (a live state with twelve named role tabs yields ten, and the two left out are named on stderr); with the limit set to a different positive integer in the configuration, that value is used; an invalid value (zero, negative, not an integer) is refused with a diagnostic rather than silently ignored.
Note for the implementer: at `init` time the configuration does not exist yet — `start_interview` builds the skeleton *before* `write_default_config` — so the value has to come from the existing configuration **when there is one** and from the default otherwise. Do not invent a second config file for it.

**S9 — every text torcha writes to the human is in English.** All CLI output (`log`, `note`, `error` in `src/torcha/output.py` callers across `commands/*.py`), the argparse help and usage strings, and `RELEVO` — the prompt torcha sends to a running agent — are English. Observed today: `Tab existente recuperada`, `ya está en marcha`, `el terminal no es un shell; no se envía nada a ciegas`, `deja fuera`, `El space … del registro ya no existe`, `No abrir la entrevista; materializar directamente.`
Observable: no CLI output produced by the package contains Spanish prose; `torcha --help` and every `torcha <cmd> --help` are English; `RELEVO` is English. Handoff documents written by the agents and the arbitrary text of tab names are not affected. Internal code comments and docstrings are out of scope: this is about what the tool says, not how it is written.

**S10 — a named tab excluded for having no live agent is reported.** `skeleton_from_live` requires `renamed and has_agent` (S7), so a named tab whose Pi died simply disappears from the skeleton, exactly as silently as the old five-tab cap did. Observed in `career-ops` on 2026-11-25: the `Coach` tab was named and present but its terminal had no program (`app=None`), so nothing was offered to the interview and nothing was said about it.
Observable: when a named tab is skipped because no agent is running in it, the run says so on stderr and names the tab and a way forward (`torcha start <role> --recreate` once it is a role, or starting Pi in that tab). A tab excluded for being the setup marker, or as a bare unnamed tab, is not reported.

**S11 — the interview must ask only the roles that are empty, and say the truth about the rest.** `_interview_prompt` (`src/torcha/commands/init.py`) writes "Every `role` and `instructions` is empty. Fill them from what each agent tells you" and the setup skill instructs "**Ask every agent in the list.**" Both are written for a first-time seed. When `init` runs on an existing configuration with some roles pending — which is exactly what `unfilled_roles()` triggers it for — the prompt lies, the spawned Pi asks the five agents that were already written, and their agent-written prose is exposed to being rewritten.
Observable: with one pending role among filled ones, the generated interview prompt names only that role as the subject of the interview and states that the others are filled and must not be touched; the setup skill carries the same rule; and the prompt contains no claim that every role is empty when one is not. A first-time seed, where every role is empty, keeps the current wording and behaviour.

**S12 — after the setup interview, the terminal keeps the focus and the logs.** `init` ends by selecting the space and the orchestrator tab unconditionally (`src/torcha/commands/init.py:434-437`), so the moment the interview's Pi exits — including when the human closes it to finish — the view jumps away from the pane where torcha is printing its summary and results.
Observable: when this run started an interview in the current pane, the run issues no `tab.select` or `space.select` towards `tabs[0]`, and instead logs where the orchestrator lives and that the logs stay in this tab. When no interview runs (plain `init`, or a configuration with nothing pending), the focus still goes to `tabs[0]`, which is deliberate feedback for a manual action. Reordering the orchestrator to position 1 is unaffected.

**S13 — a role is pending while either of its two fields is empty.** `unfilled_roles()` (`src/torcha/commands/init.py`) only looks at `role`, so a role that has a `role` but no `instructions` is considered done and nothing ever completes it. That is exactly the shape `initial_tabs` and `discover` produce, whose placeholder reads `Not declared in the repository; describe it.` and whose `instructions` stay empty; S11's wording then tells the agent not to touch a field nobody ever wrote.
Observable: with a configuration where one role has `role` but empty `instructions` and another is fully written, `init` treats the first as pending and the interview prompt names it, saying which of its two fields is still empty; the fully written role is untouched. A role with both fields written stays out of the interview, and the first-time seed keeps working as it does today.

**S14 — `torcha ls` lists the declared team against reality.** A human must be able to answer "does the configuration match what is on screen?" without reading `herdr-app ls` and `agents.json` by hand. Today it cannot: `status` compares the **registry** with Herdr and never sees a role declared in `agents.json` but never adopted — which is exactly how `Coach` stayed invisible — and `discover` lists live tabs without knowing the declared team.
Observable: `torcha ls` prints one line per role declared in `agents.json`, in declaration order, carrying at least the key, the name, the terminal, the state and the session; then names the live tabs that are not in the team. A summary line states the three counts — declared, adopted, alive — so the human can compare numbers at a glance. States are the ones `status` already uses (`alive`, `down`, `missing`, `moved`) plus `not adopted` for a declared role with no registry entry. `ls --json` gives the same data machine-readable. The command is read-only: it never creates, closes or focuses a tab, and it does not replace `status`, which stays the one that rules on divergence.

**S15 — closing a tab parks the role, so `start` must not recreate it.** An agent whose work is out of focus is put to sleep by closing its tab and woken later, deliberately. A `start` that recreates missing tabs by default wakes every parked role at once and destroys that workflow. This spec replaced an earlier version of itself that asked for the opposite; see L20.
Observable: with a registered role whose tab no longer exists, a plain `torcha start` reports the role as a failure naming `--recreate`, creates nothing and leaves the registry untouched, exit 1. With `--recreate` the tab is created, the recorded `session_id` resumed and the registry updated with the new ids and pid, exit 0. A session whose tab survives is still resumed either way. A terminal that exists but runs something which is not a shell is never closed under any flag.

**S16 — changing `pi.bootstrap` must reach the files `pi` reads.** The mode is not consulted at launch: it is rendered into `.torcha/bootstrap/<key>.md`, and only two places write those files — `init` (configured mode) and the swap (`recover` for that role). `start` does not. So editing `agents.json` from `greet` to `recover` and running `torcha start` launches the agent with the **old** prompt on disk, and nothing says so. Observed while answering a question about the modes on 2026-11-25: `grep -c 'Recovery protocol' .torcha/bootstrap/*.md` returned 0 for a configuration that claimed `recover` would be in effect.
Observable: when the file on disk does not hold exactly what the configured mode renders, the launch refuses that role, names the file and the mode it was written for, and tells the human to run `torcha init` to reconcile it; nothing is overwritten and the registry is untouched. `doctor` reports the same disagreement as a finding. When the file matches, the launch proceeds as today, and a swap still renders `recover` for the role it is about to relaunch.

**S17 — `recover` on demand, inside a running session.** A role that has been parked or idle for a long time needs to catch up on the world, not to be replaced. Today the recovery protocol only reaches an agent at launch, where nobody is watching, or forced by a swap, which destroys the session.
Observable: `torcha recover <role>` sends a catch-up message to that role's live agent and returns without touching the tab, the session id, the registry or the handoff; the agent answers in its own tab with what is done, what is pending and what the repository contradicts, after comparing its handoff's `git.head` with the current HEAD. The target is confirmed to be that role's own tab, not merely a terminal running the configured executable: a registry entry whose tab id no longer matches must be refused, because sending the wrong role's handoff path to another agent is worse than not sending; a tab that was merely renamed is a warning, not a refusal, since the id is the identity and the name is the human's label. A role with no running agent is refused with a message pointing at `start`, the terminal running the command is refused like the swap's guard, and an agent that is mid-turn is reported as queued rather than as answered. When there is no handoff, or Engram has nothing for the role, the prompt says to report that and continue instead of asking for a comparison that cannot be made. The prompt is its own text, neither the launch bootstrap nor `RELEVO`, and it names the project and the role.
| T11 | S16 | writer `gentle-ai-worker` | not committed | Make the bootstrap files follow `pi.bootstrap` at launch, or fail loudly when they disagree; surface it in `doctor`. |

**S18 — `status` carries the per-role detail that decides a handoff.** `status` says `alive` and stops, which answers nothing about the question the tool exists for: is this role close to filling its context, and is its handoff still true? The data is available without disturbing any agent.
Observable: for each registered role, `status` reports the newest handoff for that role — its age and its `git.head` — how far the repository has moved since (`git rev-list --count <handoff head>..HEAD`, and whether the working tree is dirty), and the tokens consumed by that role's last turn, read from its Pi session transcript. A percentage of the context window is shown only when the window is resolvable; otherwise the tokens are shown alone and the gap is stated, never guessed. A role with no handoff, no session id or no readable transcript says so per role instead of omitting the column. `--json` carries the same fields. Reading these sources never writes anything and never sends anything to an agent.
Note for the implementer: the transcript records `usage.totalTokens` and `model` per message but **not** the context window, so the percentage needs a window from somewhere else; treat it as best-effort and degrade loudly. The session store lives outside the project under Pi's own directory — read it defensively, by globbing the session id, and never fail the command because it is missing.

**S19 — every launched agent carries the team skill.** An agent can play neither half of the handoff protocol through the CLI: `recover` refuses the terminal that runs the command, because sending a message to yourself is pointless, and `handoff run --swap` refuses it too, because the swap closes that tab. The procedure therefore has to be in the agent's own context, and a skill that must be discovered on demand is one an agent can skip. Observed: the only packaged skill is `skills/setup/SKILL.md`, loaded by `init` for the interview; `pi_argv()` launches agents with the bootstrap reference alone.
Observable: `pi_argv()` returns `<executable> --skill <absolute path to the packaged skills/torcha/SKILL.md> [--session-id <id>] @.torcha/bootstrap/<key>.md` for every agent it launches, resolved from the package so the target project needs nothing; `bootstrap: "none"` still returns no argv at all; the setup interview's argv is unchanged. The skill teaches catching up — newest handoff by modification time, its `git.head` against `git rev-parse HEAD`, the working tree as the truth, the role in Engram, an honest report of what is done, pending and contradicted, and saying so and continuing when either source is empty — and handing over — the document's required shape, `torcha handoff validate <path>` run from inside, and the swap run by the human or the orchestrator from a tab that is not the agent's. The cost is accepted: tokens in every session, by design. The README states the same, including the cost.
**S21 — a swap may reuse a handoff that already exists.** After a relief, the document is already written and validated; asking the agent to write it again costs a turn and rewrites what was just agreed. `handoff run <role> --swap --use-existing` uses the newest handoff that already validates instead of asking for a new one.
Observable: with a valid handoff on disk, `--swap --use-existing` relaunches the session with that document, states its age in the message, and never sends `RELEVO`. The HEAD check is not waived: if the repository moved since the document was written, the run refuses and says to ask for a new one. Used without `--swap`, the flag is refused with a message saying why. A role with no valid handoff on disk falls back to asking, and says so.
**S22 — every option is documented where a test can notice drift.** The CLI has grown past what a README paragraph can hold. `docs/cli.md` carries, per command, its positionals, every flag, what each does and the exit codes; a test asserts that every option the parsers define appears in that file, so the documentation cannot fall behind the code in silence.

**S20 — `init` reports live tabs outside the team and suggests, without writing.** `ls` names them and `init` stays silent, so a team can drift from its workspace without the command that reconciles the team mentioning it.
Observable: at the end of a run, `init` names the live tabs with an agent that are not declared in `agents.json` and states the role it would add for each, in one line; it writes nothing to the configuration, and `--json` carries the same list. A workspace whose tabs all belong to the team says nothing extra.

## Tasks

| ID | Specs | State | Commit | Task |
| --- | --- | --- | --- | --- |
| T1 | S1-S5 | done | `4cd0bdc`, `9c77c33` | `start` launches with close+`--argv`, honours `--fresh`, takes the ids from `ls`, and reports what it did. |
| T2 | S6 | done | `4cd0bdc` | An accepted handoff must state the HEAD measured now. |
| T3 | S7, S8 | done | `4cd0bdc` | Team limit 10 and configurable; the setup tab and the caller are never roles; a cut tab is named. |
| T4 | S9 | done | `2e37b31` | Every message, help text and prompt in English. |
| T5 | S10 | done | `85c700c`, `958052e` | A named tab excluded for having no agent is reported once, never about the caller. |
| T6 | S11 | done | `d7cc78f` | The interview asks only the pending roles, and the skill says the same. |
| T7 | S12 | done | `d7cc78f` | An interview keeps the focus and the logs in its own tab. |
| T8 | S13 | done | `16ca274` | A role is pending while either field is empty, and the prompt says which. |
| T9 | S14 | done | `e3eb3a2` | `torcha ls`: the declared team against the live workspace, counts summarised. |
| T10 | S15 | superseded | `9c0f53c`, reverted in `69ab89b` | `start` recreated a closed tab by default; closing a tab parks a role, so it was undone. |
| T11 | S16 | dropped | - | Folded into T18, which owns the same spec. |
| T12 | S17 | done | `601b2a1`, `5417ac0` | `torcha recover <role>`: a catch-up inside a live session, no swap and no relaunch. |
| T14 | S18 | done | `266a634`, `e69357c` | `status` shows handoff age, drift and tokens; the percentage only when the window is real. |
| T15 | S19 | done | `1c75206` | The team skill ships with every launch and teaches catching up and asking for a relief. |
| T16 | S21 | done | `659b6ab` | `--swap --use-existing` reuses a validated handoff, keeping the HEAD check. |
| T17 | S22 | done | `ebf41b2` | `docs/cli.md` plus the drift test that fails when the CLI grows undocumented. |
| T18 | S16 | done | `88a39e1` | The bootstrap file wins: a launch refuses a stale one and points at `init`; `doctor` reports it. |
| T19 | S20 | done | `b592d7c` | `init` names the live tabs outside the team and the role it would add, writing nothing. |

## Log
**L1** (user, verbatim): "Lanza los subagentes que necesites para analizar, planificar y luego implementar mejoras"


**L2** (context, end-to-end run of 2026-11-24 in `/home/albestio/Code/tabcabin`): `init` with a real interview and `handoff run <role> --swap` both work. Two defects remained open and two more were found in that run: `start.py` typed its launch into a shell, so `start` could not work and its two `--recreate` tests were the only reds; an agent-written handoff carried a stray `git_branch: null`; and a swap launched the successor with the configured `greet` bootstrap, so it never read the handoff it had just been given (now `_swap` writes `recover`, and the successor verified `git.head` and declared `READY`).


**L3** (user, verbatim): "Me refiero principalmente a arreglar bugs. Tienes acceso a las sesiones de tabcabin via intercom"
→ Scope decision: only defects. Refinements (dead code, inlining, renaming) are out unless a task needs them to land its fix. The tabcabin agents are available over intercom as field evidence and as the place to reproduce a fix, which supersedes the earlier restriction that this conversation must not talk to tabcabin.


**L4** (correction, 2026-11-24): the `git_branch: null` defect reported in L2 does **not** exist as stated. The document stores the branch at `git.branch`; the inspection script read a non-existent top-level `git_branch` key and printed `None`. `validate_handoff` (`src/torcha/handoff.py:148`) already rejects an empty or non-string `branch`.


**L5** (evidence, 2026-11-24): the two red `start` tests failed for two different reasons. `test_start_recreate_fresh_starts_a_new_session` was a real bug: `_recreate` ignored `fresh`. `test_start_recreate_resumes_the_old_session` was a stale expectation: it asserted `entry["pid"] == 9000`, the fake's artifact for the old typed launch.


**L6** (evidence, audit `mwv9q8mo-1-ccfu`, 2026-11-24): the two reds were not caused by the typed transport. `_recreate` already used `tab.new --argv`; it failed because it ignored `fresh` (S2) and because it trusted `tab.new`'s echo instead of re-reading `ls` (S4). The typed path only affected the *other* branch, the one with a live shell. Also `start.py:110` always logged `reanudada` (S5), and `RELEVO` never pinned the `git` object, which is how a stray `git_branch: null` survived validation (S6). Dead code (`send_keys`, `terminals_of_space`, `bootstrap.py import json`) is a refinement, out of scope: only what a fix leaves behind gets removed. `is_shell` stays: S3 needs the refusal for a terminal running something unknown.


**L7** (decision, 2026-11-24): S6 narrowed while briefing T2. Rejecting unknown top-level keys is a refinement that widens the contract's blast radius for little gain; the defect is that the accepted handoff's `git` block was never compared with the repository. The stray `git_branch: null` was only the symptom.


**L8** (field bug, 2026-11-24, project `career-ops`): the interview did not list the `Coach` tab although it had a live Pi session. Reproduced read-only against that workspace: `inspect_space` returns seven tabs, all `renamed` with `has_agent`, and `skeleton_from_live` returns five because of `ordered[:max_tabs]` with the default 5. `Coach` is the sixth; `Torcha` is the seventh, a setup tab left renamed by a previous interview. The cap fails both ways: it drops a real role and does not filter the setup tab.


**L9** (user, verbatim): "Max tabs debería ser 10, y debería poder cambiarse desde alguna config sencillamente"
→ S8 added: the limit becomes 10 by default and configurable in the project's own configuration, on top of the exclusion of the setup tab and the loud reporting that S7 already required.


**L10** (user, verbatim): "por cierto, creo que en los logs de torcha debería tener todo textos en inglés"
→ S9 added. Sequenced as its own unit and its own commit, after the bug fixes, because it rewrites every message the suite asserts on and would otherwise bury those fixes in a mechanical diff. `RELEVO` is included: it is a prompt torcha authors, and it changes what the agents read (risk item 3), so it gets verified like any other contract.


**L11** (user, verbatim): "Pensaba que teníamos una forma de detectar agentes adicionales. Guardamos y seguimos mañana"
→ Recorded as an open design question, not a defect: live-tab detection exists, live-tab *promotion* does not. Session closed with T4 (S9, English texts) pending for the next session, plus the three carried-over items noted in L10 and the two T3 risks (the echoed-id fallback has no test; excluding the own tab can leave a skeleton without an orchestrator when `init` runs from a team tab).


**L12** (independent verify `mwvahtfd-5-c6bi`, 2026-11-24): S1-S8 all PASS, S9 out of scope. It found two blockers in the just-committed tree, both now fixed: a recreated tab was resolved **by name only**, so two tabs sharing a role name made the registry adopt the other one (reproduced: it ended on a bare shell and orphaned the new session), and a failing `tab.new` escaped `start()` while the registry kept the id of the tab that had just been closed. Resolution is now by identity: the new tab is the one `ls` shows with that name and whose id was not in the space before the create, with the echo only as a last resort; and a failed create clears the entry before reporting. Two tests pin it. Still open from that report: `discover` never passes `own_tab_id`, so the invoking tab can be proposed as a role; the `--argv` session id in S2 is not asserted by the existing tests (only the registry one); `_create_tab`'s `config` argument is unused; and the suite's 169-green claim depends on `pi` being on `PATH` for `test_a_loose_tab_in_the_space_is_not_a_team_tab`.


**L13** (user report, 2026-11-25, project `career-ops`): "faltó por detectar un agente por el límite de max". Measured read-only: the space holds five tabs running `pi` and two without a program — `Coach` and a tab named `7`. With five live agents and a limit of 10 nothing is cut, so the cause is not `max_tabs`: `Coach`'s terminal has no agent, and S7 requires `has_agent`, so the skeleton drops it. The real gap is that this exclusion is silent → S10 / T5.


**L14** (user, 2026-11-25, live in `career-ops`): "Digiste que solo detectaría Coach, pero parece que va a entrevistar a todos los agentes brevemente". Confirmed in the code: the prompt asserts that every role is empty and the setup skill says "Ask every agent in the list", so a config with one pending role re-interviews and invites rewriting the five already written. Corrected in the running interview by an intercom message; recorded as S11/T6. My earlier claim that only Coach would be interviewed was wrong.


**L15** (user, verbatim): "Algo que noto y no me gusta es que cuando mato la sesión de interview, manda el foco al tab de Orchestrator. Si estoy terminando la interview, lo normal es quedarme dentro de esa tab tras cerrar la sesión de Pi, para ver los logs de torcha"
→ S12/T7. This supersedes the earlier decision, recorded in `torcha/poc-state`, that focus always returns to `tabs[0]`: it holds for runs without an interview, not for the pane where the human just finished one.


**L16** (independent verify `mwvtwhy7-4-p427`, 2026-11-25): S9, S11 and S12 PASS, S10 PARTIAL with one blocker, S10's own-tab exclusion missing on two of four call sites, and one undisclosed change: `doctor --json`'s `checks[].name` moved from `repositorio`/`permisos` to `repository`/`permissions` alongside the rest of the English sweep. Nothing reads it, but it is a machine-readable value that the commit message did not mention — same class as the `status` state tokens, which it did. Its residual risk on S11 became S13/T8; the S10 blocker and the own-tab gaps were fixed in `958052e`.


**L17** (user, verbatim): "Necesitamos un comando torcha ls , que liste los agentes registrados en el json. Así es facil comprobar si corresponde al número de agentes en las tabs"
→ S14/T9. It is not a duplicate of `status` (registry against Herdr) nor of `discover` (live tabs): the gap is the declared team in `agents.json` joined with adoption, which is where a role like `Coach` disappeared.


**L18** (user, verbatim): "y no tendría sentido que el comportamiento de --recreate fuera un fallback de start? Me refiero a que si start falla en algún role porque no existe la tab, que automáticamente se recreara la tab y se restableciera la sesión"
→ Accepted as S15/T10, with one guard kept: a terminal running something that is not a shell is still refused without closing anything, because that tab may hold someone else's work. The flag inverts rather than disappears: `--no-recreate` is the refusal, `--recreate` stays accepted as the default so existing muscle memory and aliases keep working.


**L19** (finding, 2026-11-25, while answering how to switch to `recover`): `pi.bootstrap` is rendered into the bootstrap files by `init` and by the swap only; `start` never rewrites them, so editing the configuration and running `start` launches the agent with the previous prompt in silence. Recorded as S16/T11.


**L20** (user, verbatim): "Estoy satisfecho con el comportamiento actual de start. Las tabs cerradas no se levantan solas, las sesiones cerradas sí se levantan en las tabs abiertas. Va bien para poner a dormir agentes que no están trabajando en esta parte del proyecto, y que se pueden resucitar más adelante con un init." — and then, choosing among the options put to him: "Revertir S15: cerrar tab = dormir el agente".
This reverses L18's decision. Closing a tab is a deliberate act that parks a role; `start` must not undo it. Reverted in `69ab89b`, S15 rewritten to say the opposite, T10 superseded.


**L21** (user questions, 2026-11-25): can an agent run `recover` on itself, is `recover` the same as `handoff run`, what to do about the `<hc from=…>` envelope, and does `handoff run` need the `run`. Answers recorded in the conversation: `recover` and `handoff run` both refuse to target the terminal running the command, so neither can be self-service — the agent executes the protocol itself, which is what a skill gives; `handoff run` writes and validates a document while `recover` reads and reports, so they are adjacent but not the same; the envelope is added by `hc` and Pi does not strip it, so it arrives literally and is harmless provenance; and `handoff` has a second subcommand (`validate`), so `run` earns its keep. Also: the transcript carries `usage.totalTokens` and `model` but no context window, which is why S18 degrades instead of inventing a percentage.


**L22** (user decisions, 2026-11-25, asked and answered with the trade-offs spelled out): (a) when the bootstrap file on disk disagrees with `pi.bootstrap`, the launch **refuses and names the file** — the file wins, nothing is overwritten, and `torcha init` is the explicit way to reconcile; (b) `init` **reports and suggests** live tabs outside the team instead of adding them — the configuration changes only by human hand.


**L23** (decision closed, 2026-11-25): the open question about promoting live tabs outside the team was answered in L22 and implemented in `b592d7c`: `init` reports them and names the role it would add, writing nothing. The question no longer lives in `## Specs`.
