# Third-party skills vendored in this repository

These skills are not ours. They are copied verbatim from the
[TestMu AI agent-skills](https://github.com/LambdaTest/agent-skills) repository,
which distributes them under the MIT license (declared in each `SKILL.md`
frontmatter as `license: MIT`).

They live in `.pi/skills/` so that Pi discovers them as project skills and any
contributor's agent gets the same conventions we use.

| Skill | Source | Why it is here |
| --- | --- | --- |
| `pytest-skill` | `LambdaTest/agent-skills/pytest-skill` | The project's tests are pytest; this pins the conventions (parametrize, `pytest.raises(match=)`, `tmp_path`/`monkeypatch` fixtures). |
| `cicd-pipeline-skill` | `LambdaTest/agent-skills/cicd-pipeline-skill` | Reusable workflow skeleton for CI. The examples are Node/Playwright; a note at the top of the file explains what to replace. |

Only these two were judged applicable. The upstream list has 49 test-automation
skills; the rest target other languages, mobile, browsers, or vendor clouds.

If you update a file, keep the frontmatter intact and re-check it against
upstream. If a skill stops being used, delete it rather than leaving it to rot.
