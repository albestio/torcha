"""CLI output helpers."""

from __future__ import annotations

import sys

def log(message: str) -> None:
    print(f"[torcha] {message}")

def error(message: str) -> None:
    print(f"[torcha] ERROR: {message}", file=sys.stderr)


def note(message: str) -> None:
    """A message for the human, on stderr, so stdout stays machine-readable."""
    print(f"[torcha] {message}", file=sys.stderr)
