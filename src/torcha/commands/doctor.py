"""The doctor command: check the preconditions torcha needs.

It only reports. Fixing is `init`'s job, and a diagnostic that mutates the system
it is diagnosing is not a diagnostic.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from shutil import which

from .. import project
from ..bootstrap import bootstrap_disagreement
from ..config import load_config
from ..errors import TorchaError
from ..herdr import core_report
from ..output import log, note
from ..registry import load_registry

OK, WARN, FAIL = "ok", "warn", "fail"


def _check_python() -> tuple[str, str]:
    current = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        return OK, f"{current} (requires >=3.10)"
    return FAIL, f"{current}; requires >=3.10"


def _check_binary(name: str) -> tuple[str, str]:
    path = which(name)
    return (OK, path) if path else (FAIL, "not on PATH")


def _check_repo() -> tuple[str, str]:
    result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                            cwd=project.PROJECT_DIR, text=True,
                            capture_output=True, check=False)
    if result.returncode == 0 and result.stdout.strip() == "true":
        return OK, str(project.PROJECT_DIR)
    return FAIL, f"{project.PROJECT_DIR} is not a git repository"


def _check_herdr_app() -> tuple[str, str]:
    path = which("herdr-app")
    if path is None:
        return FAIL, "not on PATH"
    result = subprocess.run(["herdr-app", "--version"], text=True,
                            capture_output=True, check=False)
    version = (result.stdout or "").strip() or "unknown version"
    return OK, f"{version} ({path})"


def _check_core() -> tuple[str, str]:
    if which("hc") is None:
        return FAIL, "not on PATH"
    ok, detail = core_report()
    return (OK if ok else FAIL), detail


def _check_config() -> tuple[tuple[str, str], str]:
    """Returns the check and the configured pi executable."""
    if not project.CONFIG_FILE.exists():
        return (WARN, "there is no agents.json; 'init' will create a default one"), "pi"
    try:
        config = load_config()
    except TorchaError as exc:
        return (FAIL, str(exc)), "pi"
    executable = config["pi"]["executable"]
    mode = config["pi"]["bootstrap"]
    return (OK, f"{len(config['tabs'])} tab(s), bootstrap={mode}, pi={executable}"), executable


def _check_pi(executable: str) -> tuple[str, str]:
    path = which(executable)
    return (OK, path) if path else (FAIL, f"'{executable}' is not on PATH")


def _check_bootstrap() -> tuple[str, str]:
    """Report the files `pi` reads that do not hold the configured mode.

    It is a finding, never a failure: nothing here is broken enough to stop the
    tool, and a disagreement is reconciled by `torcha init`. Before the first
    `init` there is no directory and no `pi` session has read anything, so a
    project that never wrote prompts is not reported.
    """
    if not project.CONFIG_FILE.exists():
        return OK, "no agents.json; there is nothing to compare"
    try:
        config = load_config()
    except TorchaError as exc:
        return OK, f"the configuration could not be read: {exc}"
    mode = config["pi"]["bootstrap"]
    if mode == "none":
        return OK, "bootstrap is none; no prompt is read"
    if not project.BOOTSTRAP_DIR.is_dir():
        return OK, "no bootstrap file has been written yet"
    problems = []
    for item in config.get("tabs") or []:
        problem = bootstrap_disagreement(item["key"], item, mode)
        if problem is not None:
            problems.append(f"{item['key']}: {problem}")
    if problems:
        return WARN, "; ".join(problems)
    return OK, f"{len(config.get('tabs') or [])} file(s) match bootstrap={mode}"


def _check_registry() -> tuple[str, str]:
    if not project.REGISTRY_FILE.exists():
        return WARN, "there is no registry; run 'torcha init'"
    try:
        registry = load_registry()
    except TorchaError as exc:
        return FAIL, str(exc)
    status = registry.get("status")
    if status == "ready":
        space = (registry.get("herdr") or {}).get("space_id")
        return OK, f"ready, space {space}"
    detail = f"state {status!r}"
    if registry.get("error"):
        detail += f": {registry['error']}"
    return WARN, detail


def _check_writable() -> tuple[str, str]:
    directory = project.TORCHA_DIR if project.TORCHA_DIR.exists() else project.PROJECT_DIR
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".torcha-doctor-"):
            pass
    except OSError as exc:
        return FAIL, f"cannot write to {directory}: {exc}"
    return OK, str(directory)


def doctor(as_json: bool = False) -> int:
    config_check, executable = _check_config()
    checks = [
        ("python", _check_python()),
        ("git", _check_binary("git")),
        ("repository", _check_repo()),
        ("herdr-app", _check_herdr_app()),
        ("herdr-core", _check_core()),
        ("config", config_check),
        ("pi", _check_pi(executable)),
        ("bootstrap", _check_bootstrap()),
        ("registry", _check_registry()),
        ("permissions", _check_writable()),
    ]

    failures = [name for name, (state, _) in checks if state == FAIL]
    warnings = [name for name, (state, _) in checks if state == WARN]

    if as_json:
        print(json.dumps({
            "checks": [{"name": name, "state": state, "detail": detail}
                       for name, (state, detail) in checks],
            "summary": {"total": len(checks), "failures": failures,
                        "warnings": warnings},
        }, indent=2, ensure_ascii=False))
        return 1 if failures else 0

    width = max(len(name) for name, _ in checks)
    for name, (state, detail) in checks:
        log(f"  {name:<{width}}  {state:<5} {detail}")
    log(f"{len(checks)} check(s) · {len(failures)} failure(s), "
        f"{len(warnings)} warning(s)")
    if failures:
        note("Run 'torcha init' once the preconditions are resolved.")
    return 1 if failures else 0
