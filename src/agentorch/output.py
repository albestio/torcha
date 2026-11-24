"""CLI output helpers."""

from __future__ import annotations

import sys

def log(message: str) -> None:
    print(f"[agentorch] {message}")

def error(message: str) -> None:
    print(f"[agentorch] ERROR: {message}", file=sys.stderr)


def note(message: str) -> None:
    """A message for the human, on stderr, so stdout stays machine-readable."""
    print(f"[agentorch] {message}", file=sys.stderr)
