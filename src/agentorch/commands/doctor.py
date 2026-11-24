"""The doctor command: check the preconditions agentorch needs.

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
from ..config import load_config
from ..errors import AgentorchError
from ..herdr import core_report
from ..output import log, note
from ..registry import load_registry

OK, WARN, FAIL = "ok", "warn", "fail"


def _check_python() -> tuple[str, str]:
    current = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        return OK, f"{current} (requiere >=3.10)"
    return FAIL, f"{current}; se requiere >=3.10"


def _check_binary(name: str) -> tuple[str, str]:
    path = which(name)
    return (OK, path) if path else (FAIL, "no está en PATH")


def _check_repo() -> tuple[str, str]:
    result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                            cwd=project.PROJECT_DIR, text=True,
                            capture_output=True, check=False)
    if result.returncode == 0 and result.stdout.strip() == "true":
        return OK, str(project.PROJECT_DIR)
    return FAIL, f"{project.PROJECT_DIR} no es un repositorio git"


def _check_herdr_app() -> tuple[str, str]:
    path = which("herdr-app")
    if path is None:
        return FAIL, "no está en PATH"
    result = subprocess.run(["herdr-app", "--version"], text=True,
                            capture_output=True, check=False)
    version = (result.stdout or "").strip() or "versión desconocida"
    return OK, f"{version} ({path})"


def _check_core() -> tuple[str, str]:
    if which("hc") is None:
        return FAIL, "no está en PATH"
    ok, detail = core_report()
    return (OK if ok else FAIL), detail


def _check_config() -> tuple[tuple[str, str], str]:
    """Returns the check and the configured pi executable."""
    if not project.CONFIG_FILE.exists():
        return (WARN, "no hay agents.json; 'init' creará uno por defecto"), "pi"
    try:
        config = load_config()
    except AgentorchError as exc:
        return (FAIL, str(exc)), "pi"
    executable = config["pi"]["executable"]
    mode = config["pi"]["bootstrap"]
    return (OK, f"{len(config['tabs'])} tab(s), bootstrap={mode}, pi={executable}"), executable


def _check_pi(executable: str) -> tuple[str, str]:
    path = which(executable)
    return (OK, path) if path else (FAIL, f"'{executable}' no está en PATH")


def _check_registry() -> tuple[str, str]:
    if not project.REGISTRY_FILE.exists():
        return WARN, "no hay registry; ejecuta 'agentorch init'"
    try:
        registry = load_registry()
    except AgentorchError as exc:
        return FAIL, str(exc)
    status = registry.get("status")
    if status == "ready":
        space = (registry.get("herdr") or {}).get("space_id")
        return OK, f"listo, space {space}"
    detail = f"estado {status!r}"
    if registry.get("error"):
        detail += f": {registry['error']}"
    return WARN, detail


def _check_writable() -> tuple[str, str]:
    directory = project.AGENTORCH_DIR if project.AGENTORCH_DIR.exists() else project.PROJECT_DIR
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".agentorch-doctor-"):
            pass
    except OSError as exc:
        return FAIL, f"no se puede escribir en {directory}: {exc}"
    return OK, str(directory)


def doctor(as_json: bool = False) -> int:
    config_check, executable = _check_config()
    checks = [
        ("python", _check_python()),
        ("git", _check_binary("git")),
        ("repositorio", _check_repo()),
        ("herdr-app", _check_herdr_app()),
        ("herdr-core", _check_core()),
        ("config", config_check),
        ("pi", _check_pi(executable)),
        ("registry", _check_registry()),
        ("permisos", _check_writable()),
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
    log(f"{len(checks)} comprobación(es) · {len(failures)} fallo(s), "
        f"{len(warnings)} aviso(s)")
    if failures:
        note("Ejecuta 'agentorch init' cuando las precondiciones estén resueltas.")
    return 1 if failures else 0
