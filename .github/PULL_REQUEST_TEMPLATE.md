## What this changes

<!-- One behaviour. If it is three, it is three pull requests. -->

## How you know it works

<!--
Paste the test names, and say what they would catch. "Tests pass" alone does not
tell a reviewer whether the new rule is pinned or merely not contradicted.
-->

- [ ] One failing test per rule before the fix
- [ ] `python -m pytest -q` is green
- [ ] `docs/cli.md` updated if a command, option or exit code changed (a test
      fails when it is not)
- [ ] `CHANGELOG.md` updated
- [ ] Nothing in the diff needs a real workspace to verify

## Risk

<!--
Which of these does the change touch? A wrong answer here is worse than "none".
1 data or irreversible effects, 2 security, 3 a contract others consume (a flag,
a prompt an agent reads, a file format), 4 concurrency, 5 delivery or
environment, 6 nothing would catch a regression.
-->

Risk: none / item N (why)
