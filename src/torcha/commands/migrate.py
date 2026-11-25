"""The migrate command: copy the old runtime data directory to its new name.

The rename moved the data directory from `.agentorch/` to `.torcha/`. An adopted
project still holds the old one, so this command copies it, verifies the copy and
leaves the original in place: nothing is moved, nothing is deleted, and nothing
migrates on its own. The copy is only trusted after the file count matches, every
copied file is byte-identical and the agents configuration and the registry read
back through the loaders the rest of the tool uses.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import project
from ..config import load_config
from ..errors import TorchaError
from ..output import log
from ..registry import load_registry

CONFIG_NAME = "agents.json"
REGISTRY_NAME = "registry.json"


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _verify(source: Path, copy: Path) -> list[str]:
    """Check the copy against its source and return the copied relative names."""
    original = _files(source)
    copied = _files(copy)
    if len(original) != len(copied):
        raise TorchaError(
            f"The copy is incomplete: {source} has {len(original)} file(s) and "
            f"{copy} has {len(copied)}.")
    for path in original:
        relative = _relative(source, path)
        target = copy / relative
        if not target.is_file() or target.read_bytes() != path.read_bytes():
            raise TorchaError(
                f"The copy is wrong: {target} does not match {path}.")
    return [_relative(source, path) for path in original]


def _read_back(copy: Path) -> list[str]:
    """Read through the loaders the tool depends on, when the copy carries them."""
    checked = []
    if (copy / CONFIG_NAME).exists():
        load_config()
        checked.append(CONFIG_NAME)
    if (copy / REGISTRY_NAME).exists():
        load_registry()
        checked.append(REGISTRY_NAME)
    return checked


def migrate() -> int:
    legacy, current = project.legacy_dir(), project.TORCHA_DIR
    if legacy.exists() and current.exists():
        raise TorchaError(
            f"Both {legacy} and {current} exist: refusing to guess which one is "
            f"current. Remove one of them by hand and run 'torcha migrate' again.")
    if not legacy.exists():
        log(f"Nothing to migrate: {legacy} does not exist and {current} is "
            f"already the project's data directory.")
        return 0
    if not legacy.is_dir():
        raise TorchaError(f"The old data path is not a directory: {legacy}")

    shutil.copytree(legacy, current)
    names = _verify(legacy, current)
    checked = _read_back(current)

    log(f"Copied {len(names)} file(s) from {legacy} to {current}:")
    for name in names:
        log(f"  {name}")
    verified = f"{len(names)} file(s)"
    if checked:
        verified += f", with {', '.join(checked)} read back"
    log(f"Verified the copy: {verified}.")
    log(f"The original is still in place, unchanged: {legacy}.")
    return 0
