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
from .commands.rename import rename
from .commands.start import start
from .commands.status import status
from .commands.templates import templates
from .errors import AgentorchError
from .output import error
from .project import configure_project


def main() -> int:
    parser = argparse.ArgumentParser(prog="agentorch",
        description="Bootstrap y recuperación de spaces/tabs Herdr.")
    parser.add_argument("--version", action="version", version=f"Agentorch {VERSION}")
    parser.add_argument("--project", metavar="PATH",
                        help="Directorio del proyecto (por defecto, el actual).")
    sub = parser.add_subparsers(dest="command")
    for name, help_text in (
        ("init", "Crear o recuperar el space y sus tabs."),
        ("discover", "Listar agentes declarados y proponer un agents.json."),
        ("status", "Comparar el registro con lo que Herdr reporta ahora."),
        ("doctor", "Comprobar las precondiciones que agentorch necesita."),
        ("start", "Arrancar los agentes que no están en marcha."),
        ("rename", "Renombrar la tab de un rol."),
        ("templates", "Listar los equipos predefinidos."),
    ):
        child = sub.add_parser(name, help=help_text)
        if name == "init":
            child.add_argument("--plain", action="store_true",
                               help="No abrir la entrevista; materializar directamente.")
        child.add_argument("--project", metavar="PATH", default=argparse.SUPPRESS,
                           help="Directorio del proyecto (por defecto, el actual).")
        if name == "discover":
            child.add_argument("--live", action="store_true",
                               help="Incluir las tabs abiertas en Herdr y el rol que "
                                    "cada una parece tener.")
            child.add_argument("--json", action="store_true",
                               help="Salida JSON completa, con ids de tab y terminal.")
        if name == "templates":
            child.add_argument("--json", action="store_true",
                               help="Salida JSON para scripts.")
        if name == "status":
            child.add_argument("--json", action="store_true",
                               help="Salida JSON para scripts.")
        if name == "doctor":
            child.add_argument("--json", action="store_true",
                               help="Salida JSON para scripts.")
        if name == "rename":
            child.add_argument("role", help="Rol del registro.")
            child.add_argument("name", help="Nombre nuevo de la tab.")
        if name == "start":
            child.add_argument("role", nargs="?",
                               help="Arrancar solo este rol.")
            child.add_argument("--fresh", action="store_true",
                               help="Sesión nueva en vez de reanudar la existente.")
            child.add_argument("--recreate", action="store_true",
                               help="Recrear las tabs que se hayan cerrado.")
    handoff_parser = sub.add_parser("handoff", help="Documentos de handoff.")
    handoff_parser.add_argument("--project", metavar="PATH", default=argparse.SUPPRESS,
                                help="Directorio del proyecto (por defecto, el actual).")
    handoff_sub = handoff_parser.add_subparsers(dest="handoff_command")
    run_parser = handoff_sub.add_parser(
        "run", help="Pedir el handoff a un agente y validarlo.")
    run_parser.add_argument("role", nargs="?", help="Rol del registro.")
    run_parser.add_argument("--all", action="store_true",
                            help="Todos los roles, en secuencia.")
    run_parser.add_argument("--swap", action="store_true",
                            help="Reemplazar la sesión tras validar el handoff.")
    run_parser.add_argument("--timeout", type=float, default=300.0,
                            help="Segundos de espera por agente (300 por defecto).")
    run_parser.add_argument("--force", action="store_true",
                            help="Volver a pedir el handoff aunque ya haya uno válido.")
    validate_parser = handoff_sub.add_parser("validate", help="Validar un handoff.")
    validate_parser.add_argument("path", help="Ruta del fichero de handoff.")
    validate_parser.add_argument("--json", action="store_true",
                                 help="Salida JSON para scripts.")
    validate_parser.add_argument("--check-head", action="store_true",
                                 help="Comparar git.head con el commit actual.")
    args = parser.parse_args()
    try:
        configure_project(Path(args.project) if getattr(args, "project", None) else None)
    except AgentorchError as exc:
        error(str(exc))
        return 1
    if args.command == "init":
        call = lambda: init(plain=getattr(args, "plain", False))
    elif args.command == "discover":
        call = lambda: discover(live=getattr(args, "live", False),
                                as_json=getattr(args, "json", False))
    elif args.command == "status":
        call = lambda: status(as_json=getattr(args, "json", False))
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
    elif args.command == "handoff" and getattr(args, "handoff_command", None) == "run":
        call = lambda: run_handoff_command(
            role=args.role, all_roles=getattr(args, "all", False),
            swap=getattr(args, "swap", False),
            timeout=getattr(args, "timeout", 300.0),
            force=getattr(args, "force", False))
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
