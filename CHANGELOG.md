# Changelog

Notable changes to torcha. The format follows Keep a Changelog and the project
uses semantic versioning.

## [0.4.0] - 2026-11-25

First release with a usable command surface, after adopting two real workspaces
and fixing what they exposed.

### Added

- `torcha ls`: the declared team against the live workspace, with `not adopted`
  for a role that never entered the registry and the live tabs outside the team
  named; counts summarised in one line.
- `torcha recover <role>`: a catch-up sent to a running agent. No tab, no
  session id and no handoff touched.
- `torcha status`, per role: the newest handoff and its age, the drift against
  the repository (commits since that head, rewritten branch, dirty tree) and the
  tokens of its last turn, with a context percentage only when a real window can
  be resolved.
- `handoff run --swap --use-existing`: reuse a handoff that already validates
  instead of asking for another, keeping the HEAD check and stating its age.
- `--json` for `init`, alongside the commands that already had it.
- A packaged team skill, loaded on every launch with `--skill`, teaching an agent
  to catch up on its own and to ask for a relief it cannot perform.
- `docs/cli.md`: every command, option and exit code, with a test that fails when
  the CLI grows undocumented.

### Changed

- Every message, help text and prompt is in English.
- The team limit is 10 and configurable as `max_tabs`; the setup tab and the tab
  running the command are never roles, and a tab the limit cuts is named.
- `torcha start` refuses a bootstrap file that disagrees with `pi.bootstrap`
  and points at `init`; `doctor` reports the same disagreement.
- `torcha init` names the live tabs outside the team and the role it would add,
  writing nothing.
- Closing a tab parks a role: `start` does not recreate it without `--recreate`.

### Fixed

- Nothing is typed into a shell. Launching Pi replaces the tab with
  `tab.new --argv`, because `hc send` envelopes text and a bash dies on it.
- A swap launches the successor with the `recover` bootstrap, so it reads the
  handoff it was given.
- `start --recreate` honours `--fresh` and takes tab ids from the workspace
  rather than from `tab.new`'s echo.
- A recreated tab is resolved by identity, not by name; a failed create clears the
  registry instead of leaving it pointing at a tab that is gone.
- An accepted handoff must state the HEAD measured at validation time.
- The interview asks only the pending roles, treats a role as pending while either
  field is empty, and leaves the focus in the tab whose logs matter.
- The agent-less warning is one line per command, never about the caller's own tab,
  and now also fires on the reconcile path.
- `status` never borrows another session's context percentage.
