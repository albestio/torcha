"""Agentorch command line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__ as VERSION
from .commands.discover import discover
from .commands.doctor import doctor
from .commands.handoff import run as run_handoff_command
from .commands.handoff import validate as validate_handoff_command
from .commands.init import init
from .commands.ls import ls
from .commands.recover import recover as recover_command
from .commands.rename import rename
from .commands.start import start
from .commands.status import status
from .commands.templates import templates
from .errors import AgentorchError
from .output import error
from .project import configure_project


def main() -> int:
    parser = argparse.ArgumentParser(prog="agentorch",
        description="Bootstrap and recovery of Herdr spaces and tabs.")
    parser.add_argument("--version", action="version", version=f"Agentorch {VERSION}")
    parser.add_argument("--project", metavar="PATH",
                        help="Project directory (the current one by default).")
    sub = parser.add_subparsers(dest="command")
    for name, help_text in (
        ("init", "Create or recover the space and its tabs."),
        ("discover", "List declared agents and propose an agents.json."),
        ("status", "Compare the registry with what Herdr reports now."),
        ("ls", "List the declared team against the live workspace."),
        ("doctor", "Check the preconditions agentorch needs."),
        ("start", "Start the agents that are not running."),
        ("recover", "Ask a running agent to catch up without replacing its session."),
        ("rename", "Rename a role's tab."),
        ("templates", "List the bundled teams."),
    ):
        child = sub.add_parser(name, help=help_text)
        if name == "init":
            child.add_argument("--plain", action="store_true",
                               help="Do not open the interview; materialise directly.")
            child.add_argument("--json", action="store_true",
                               help="JSON output for scripts: the live tabs outside "
                                    "the team and the role each one would add.")
        child.add_argument("--project", metavar="PATH", default=argparse.SUPPRESS,
                           help="Project directory (the current one by default).")
        if name == "discover":
            child.add_argument("--live", action="store_true",
                               help="Include the tabs open in Herdr and the role "
                                    "each one appears to have.")
            child.add_argument("--json", action="store_true",
                               help="Full JSON output, with tab and terminal ids.")
        if name == "templates":
            child.add_argument("--json", action="store_true",
                               help="JSON output for scripts.")
        if name in ("status", "ls"):
            child.add_argument("--json", action="store_true",
                               help="JSON output for scripts.")
        if name == "doctor":
            child.add_argument("--json", action="store_true",
                               help="JSON output for scripts.")
        if name == "rename":
            child.add_argument("role", help="Role in the registry.")
            child.add_argument("name", help="New name of the tab.")
        if name == "recover":
            child.add_argument("role", help="Role in the registry, running in its "
                                            "own tab.")
        if name == "start":
            child.add_argument("role", nargs="?",
                               help="Start only this role.")
            child.add_argument("--fresh", action="store_true",
                               help="A new session instead of resuming the existing one.")
            child.add_argument("--recreate", action="store_true",
                               help="Recreate the tabs that have been closed.")
    handoff_parser = sub.add_parser("handoff", help="Handoff documents.")
    handoff_parser.add_argument("--project", metavar="PATH", default=argparse.SUPPRESS,
                                help="Project directory (the current one by default).")
    handoff_sub = handoff_parser.add_subparsers(dest="handoff_command")
    run_parser = handoff_sub.add_parser(
        "run", help="Ask an agent for its handoff and validate it.")
    run_parser.add_argument("role", nargs="?", help="Role in the registry.")
    run_parser.add_argument("--all", action="store_true",
                            help="Every role, in sequence.")
    run_parser.add_argument("--swap", action="store_true",
                            help="Replace the session after validating the handoff.")
    run_parser.add_argument("--use-existing", action="store_true",
                            help="Reuse the newest handoff already on disk instead "
                                 "of asking the agent for another one. Requires "
                                 "--swap, and the git.head check still applies.")
    run_parser.add_argument("--timeout", type=float, default=300.0,
                            help="Seconds to wait per agent (300 by default).")
    run_parser.add_argument("--force", action="store_true",
                            help="Ask for the handoff again even when there "
                                 "is already a valid one.")
    validate_parser = handoff_sub.add_parser("validate", help="Validate a handoff.")
    validate_parser.add_argument("path", help="Path to the handoff file.")
    validate_parser.add_argument("--json", action="store_true",
                                 help="JSON output for scripts.")
    validate_parser.add_argument("--check-head", action="store_true",
                                 help="Compare git.head with the current commit.")
    args = parser.parse_args()
    try:
        configure_project(Path(args.project) if getattr(args, "project", None) else None)
    except AgentorchError as exc:
        error(str(exc))
        return 1
    if args.command == "init":
        call = lambda: init(plain=getattr(args, "plain", False),
                            as_json=getattr(args, "json", False))
    elif args.command == "discover":
        call = lambda: discover(live=getattr(args, "live", False),
                                as_json=getattr(args, "json", False))
    elif args.command == "status":
        call = lambda: status(as_json=getattr(args, "json", False))
    elif args.command == "ls":
        call = lambda: ls(as_json=getattr(args, "json", False))
    elif args.command == "doctor":
        call = lambda: doctor(as_json=getattr(args, "json", False))
    elif args.command == "templates":
        call = lambda: templates(as_json=getattr(args, "json", False))
    elif args.command == "rename":
        call = lambda: rename(args.role, args.name)
    elif args.command == "start":
        call = lambda: start(role=getattr(args, "role", None),
                             fresh=getattr(args, "fresh", False),
                             recreate=getattr(args, "recreate", False))
    elif args.command == "recover":
        call = lambda: recover_command(args.role)
    elif args.command == "handoff" and getattr(args, "handoff_command", None) == "run":
        call = lambda: run_handoff_command(
            role=args.role, all_roles=getattr(args, "all", False),
            swap=getattr(args, "swap", False),
            timeout=getattr(args, "timeout", 300.0),
            force=getattr(args, "force", False),
            use_existing=getattr(args, "use_existing", False))
    elif args.command == "handoff" and getattr(args, "handoff_command", None) == "validate":
        call = lambda: validate_handoff_command(
            args.path, as_json=getattr(args, "json", False),
            check_head=getattr(args, "check_head", False))
    else:
        parser.print_help()
        return 0
    try:
        return call()
    except AgentorchError as exc:
        error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
