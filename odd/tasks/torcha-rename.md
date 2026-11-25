# Rename to torcha

Feature: rename the project from `torcha` to `torcha` without losing an adopted
project, its handoffs or its history.
Read this file until `## Log`, then work only on the task you were given.

## Specs

**S1 — one name, everywhere.** The distribution, the import package, the console
script, the runtime data directory, the packaged skill directory, the docs and
every message say `torcha`. Measured before the change: 372 lowercase
occurrences in `src` + `tests`, 114 of the capitalised form, 105 of the data
directory, plus five structural identifiers that are not prose (`prog=`,
`TORCHA_DIR`, the `skills/torcha/` path, `SETUP_TAB_NAME`, hatch's version
path).
Observable: `grep -ri torcha` over the tracked tree returns only the
migration code that must still recognise the old name, the changelog entry and
the historical log entries.

**S2 — a project already adopted keeps working, and nothing is moved behind the
human's back.** `torcha migrate` copies `.torcha/` to `.torcha/`, verifies the
copy (file count and a re-read of the registry and agents config) and leaves the
original untouched. Every other command refuses a project that still has
`.torcha/` and no `.torcha/`, naming `torcha migrate`; it never migrates on
its own.
Observable: on a project with `.torcha/`, `torcha status` refuses and points
at `migrate`; after `torcha migrate` the data is in `.torcha/`, the old directory
is still there and identical, and `status` works. Running `migrate` twice is
safe and says it has nothing to do. A project with both directories is refused
with both paths named, because guessing which one is current is worse than
asking.

**S3 — the setup-tab marker recognises its old name.** An existing project has a
tab named `Torcha` that `_mark_setup_tab` created. It must not become an
adoptable role: the marker check accepts both names, while new setup tabs are
named `Torcha`.

**S4 — the rename is a release, not a quiet edit.** `0.5.0`, a `Renamed` section
in the changelog stating what an existing user has to run, and the wheel test
asserting the *new* skill path is inside the package.
Observable: `CHANGELOG.md` has the entry; the packaging test looks for
`torcha/skills/torcha/SKILL.md` and `torcha/skills/setup/SKILL.md`.

## Tasks

| ID | Specs | State | Commit | Task |
| --- | --- | --- | --- | --- |
| R1 | S1 | pending | - | Move the package and the test file, sweep the three spellings, fix `pyproject`, and keep the suite green. |
| R2 | S2, S3 | pending | - | `torcha migrate` plus the refusal guard, and the marker that accepts `Torcha`. |
| R3 | S4 | pending | - | Release 0.5.0: changelog, reinstall, and the two real projects verified. |

## Log

**L1** (user, verbatim): "Vamos a renombrar el proyecto a Torcha. Necesito un plan para renombrar todo"

**L2** (user decisions, 2026-11-25, asked with the trade-offs spelled out):
(a) "Comando migrate explícito" — a project with `.torcha/` is migrated by
`torcha migrate`, copying and verifying, never automatically;
(b) "Renombrar y reescribir todo" — the v2 specification and this project's
feature document are renamed and their mentions rewritten, rather than archived.

**L3** (risk recorded at planning time): S16 makes the rename a stop, not a
silent upgrade. The bootstrap file on disk in every adopted project holds the old
text, so once the rendered text changes those files are stale and `start` refuses
until `init` runs again. That is the rule the human chose in L22 of
`torcha-improvements.md`, and it turns `init` into a mandatory migration step.
