#!/usr/bin/env python3
"""Agentorch: crea o recupera un space de Herdr y sus tabs configuradas."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "0.2.0"
PROJECT_DIR = Path(__file__).resolve().parent.parent
PROJECT_NAME = PROJECT_DIR.name
AGENTORCH_DIR = PROJECT_DIR / ".agentorch"
CONFIG_FILE = AGENTORCH_DIR / "agents.json"
REGISTRY_FILE = AGENTORCH_DIR / "registry.json"


class AgentorchError(Exception):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(f"[agentorch] {message}")


def error(message: str) -> None:
    print(f"[agentorch] ERROR: {message}", file=sys.stderr)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                     dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run_app(args: list[str], *, allow_error: bool = False) -> str:
    command = ["herdr-app", *args]
    log(f"Ejecutando: {' '.join(command)}")
    result = subprocess.run(command, cwd=PROJECT_DIR, text=True,
                            capture_output=True, check=False)
    if result.returncode and not allow_error:
        detail = (result.stderr or result.stdout).strip()
        raise AgentorchError(
            f"herdr-app devolvió código {result.returncode}: "
            f"{' '.join(command)}" + (f"\n{detail}" if detail else "")
        )
    return result.stdout.strip()


def parse_json_output(output: str, operation: str) -> Any:
    # Algunas versiones pueden añadir mensajes antes/después del objeto JSON.
    decoder = json.JSONDecoder()
    for index, char in enumerate(output):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
            return value
        except json.JSONDecodeError:
            continue
    raise AgentorchError(
        f"No se pudo interpretar como JSON la salida de '{operation}'. "
        f"Salida recibida:\n{output[:3000]}"
    )


def load_config() -> list[dict[str, str]]:
    if not CONFIG_FILE.exists():
        raise AgentorchError(f"No existe el archivo de configuración: {CONFIG_FILE}")
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentorchError(f"No se pudo leer {CONFIG_FILE}: {exc}") from exc

    tabs = raw.get("tabs") if isinstance(raw, dict) else None
    if not isinstance(tabs, list) or not tabs:
        raise AgentorchError("agents.json debe contener una lista no vacía en 'tabs'.")

    result: list[dict[str, str]] = []
    keys, names = set(), set()
    for item in tabs:
        if not isinstance(item, dict):
            raise AgentorchError("Cada elemento de 'tabs' debe ser un objeto.")
        key, name = item.get("key"), item.get("name")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise AgentorchError(f"Clave de tab no válida: {key!r}")
        if not isinstance(name, str) or not name.strip():
            raise AgentorchError(f"Nombre de tab no válido para {key!r}.")
        if key in keys or name.casefold() in names:
            raise AgentorchError(f"Clave o nombre de tab duplicado: {key!r} / {name!r}")
        keys.add(key)
        names.add(name.casefold())
        result.append({"key": key, "name": name.strip()})

    if result[0]["key"] != "orchestrator":
        raise AgentorchError("La primera tab debe tener key='orchestrator'.")
    return result


def norm_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return os.path.abspath(os.path.expanduser(value))


def first_string(obj: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def objects_with_key(value: Any, wanted: str):
    """Recorre el árbol JSON y devuelve objetos cuyo campo coincide."""
    if isinstance(value, dict):
        if wanted in value:
            yield value
        for child in value.values():
            yield from objects_with_key(child, wanted)
    elif isinstance(value, list):
        for child in value:
            yield from objects_with_key(child, wanted)


def get_spaces(ls_data: Any) -> list[dict[str, Any]]:
    if isinstance(ls_data, dict):
        for obj in objects_with_key(ls_data, "spaces"):
            spaces = obj.get("spaces")
            if isinstance(spaces, list):
                return [x for x in spaces if isinstance(x, dict)]
    # Formato alternativo: el array raíz contiene los spaces.
    if isinstance(ls_data, list):
        return [x for x in ls_data if isinstance(x, dict)
                and any(k in x for k in ("tabs", "folder", "path"))]
    raise AgentorchError(
        "La salida de 'herdr-app ls' no contiene una lista reconocible de spaces. "
        "Se ha guardado la salida en .agentorch/last-ls.json."
    )


def space_folder(space: dict[str, Any]) -> str | None:
    for key in ("folder", "cwd", "path", "directory"):
        path = norm_path(space.get(key))
        if path:
            return path
    # Algunas respuestas exponen el directorio en el primer terminal.
    for obj in objects_with_key(space, "cwd"):
        path = norm_path(obj.get("cwd"))
        if path:
            return path
    return None


def space_id(space: dict[str, Any]) -> str | None:
    return first_string(space, "id", "space_id", "space")


def tabs_of(space: dict[str, Any]) -> list[dict[str, Any]]:
    tabs = space.get("tabs")
    if isinstance(tabs, list):
        return [t for t in tabs if isinstance(t, dict)]
    return []


def tab_name(tab: dict[str, Any]) -> str | None:
    return first_string(tab, "name", "label", "title")


def tab_id(tab: dict[str, Any]) -> str | None:
    return first_string(tab, "id", "tab_id")


def extract_tab_ids(tab: dict[str, Any]) -> dict[str, str | None]:
    pane = terminal = None
    # Algunas versiones exponen pane_id directamente; otras usan panes[].id.
    for obj in objects_with_key(tab, "pane_id"):
        value = obj.get("pane_id")
        if isinstance(value, str) and value:
            pane = value
            break
    if pane is None:
        for obj in objects_with_key(tab, "panes"):
            values = obj.get("panes")
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        pane = first_string(item, "pane_id", "id")
                        if pane:
                            break
            if pane:
                break
    for obj in objects_with_key(tab, "terminal_id"):
        value = obj.get("terminal_id")
        if isinstance(value, str) and value:
            terminal = value
            break
    if terminal is None:
        for obj in objects_with_key(tab, "terminal"):
            value = obj.get("terminal")
            if isinstance(value, str) and value:
                terminal = value
            elif isinstance(value, dict):
                terminal = first_string(value, "terminal_id", "id")
            if terminal:
                break
    if terminal is None:
        for obj in objects_with_key(tab, "terminals"):
            values = obj.get("terminals")
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        terminal = first_string(item, "terminal_id", "id")
                        if terminal:
                            break
            if terminal:
                break
    return {"terminal_id": terminal, "pane_id": pane}


def registry_template(tabs: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "status": "initializing",
        "project": {"name": PROJECT_NAME, "path": str(PROJECT_DIR)},
        "herdr": {"space_id": None, "tabs": {
            item["key"]: {
                "name": item["name"], "tab_id": None,
                "terminal_id": None, "pane_id": None
            } for item in tabs
        }},
        "updated_at": timestamp(),
        "error": None,
    }


def save_registry(registry: dict[str, Any]) -> None:
    registry["updated_at"] = timestamp()
    write_json_atomic(REGISTRY_FILE, registry)


def init() -> int:
    log(f"Agentorch v{VERSION}")
    log(f"Proyecto: {PROJECT_NAME}")
    log(f"Directorio: {PROJECT_DIR}")

    from shutil import which
    if which("herdr-app") is None:
        raise AgentorchError("No se encuentra 'herdr-app' en PATH.")
    tabs_config = load_config()
    AGENTORCH_DIR.mkdir(parents=True, exist_ok=True)
    registry = registry_template(tabs_config)
    save_registry(registry)

    try:
        # 1. Inspeccionar la ventana en ejecución y localizar el space por carpeta.
        log("Consultando spaces existentes en Herdr...")
        ls_output = run_app(["ls"])
        try:
            ls_data = parse_json_output(ls_output, "herdr-app ls")
        except AgentorchError:
            write_json_atomic(AGENTORCH_DIR / "last-ls.json",
                              {"stdout": ls_output, "saved_at": timestamp()})
            raise
        spaces = get_spaces(ls_data)
        matches = [s for s in spaces if space_folder(s) == str(PROJECT_DIR)]

        if len(matches) > 1:
            ids = [space_id(s) for s in matches]
            raise AgentorchError(
                f"Hay varios spaces asociados a {PROJECT_DIR}: {ids}. "
                "No se modificó ninguno; resuelve el duplicado manualmente."
            )

        if matches:
            space = matches[0]
            sid = space_id(space)
            if not sid:
                raise AgentorchError("Se encontró el space del proyecto, pero no se pudo extraer su ID.")
            log(f"Space existente recuperado: {sid}")
        else:
            # 2. Crear el space con la primera tab (Orquestador).
            log("No existe un space asociado a esta carpeta. Creándolo...")
            output = run_app([
                "do", "space.new", "--name", PROJECT_NAME,
                "--folder", str(PROJECT_DIR),
                "--tab", tabs_config[0]["name"],
                "--focus", "true",
            ])
            created = parse_json_output(output, "space.new")
            sid = first_string(created, "space", "space_id", "id")
            if not sid:
                raise AgentorchError(f"space.new no devolvió un ID de space: {output}")
            log(f"Space creado: {sid}")

        registry["herdr"]["space_id"] = sid
        save_registry(registry)

        # 3. Releer el estado antes de crear tabs para evitar duplicados.
        ls_data = parse_json_output(run_app(["ls"]), "herdr-app ls")
        current_spaces = get_spaces(ls_data)
        current = next((s for s in current_spaces if space_id(s) == sid), None)
        if current is None:
            raise AgentorchError(f"El space {sid} no aparece en la segunda consulta 'ls'.")
        existing = { (tab_name(t) or "").casefold(): t for t in tabs_of(current) }

        # 4. Crear solo las tabs ausentes.
        for index, item in enumerate(tabs_config):
            key, name = item["key"], item["name"]
            found = existing.get(name.casefold())
            if found:
                log(f"Tab existente recuperada: {name}")
                continue
            # La primera tab se crea junto con el space.new.
            if index == 0 and not matches:
                continue
            log(f"Creando tab: {name}")
            output = run_app([
                "do", "tab.new", "--name", name, "--space", sid,
                "--folder", str(PROJECT_DIR), "--focus", "false",
            ])
            parse_json_output(output, f"tab.new ({name})")

        # 5. Obtener IDs definitivos (tab, terminal y pane) desde ls.
        final_data = parse_json_output(run_app(["ls"]), "herdr-app ls")
        final_spaces = get_spaces(final_data)
        final_space = next((s for s in final_spaces if space_id(s) == sid), None)
        if final_space is None:
            raise AgentorchError(f"No se pudo verificar el space {sid} después de crear las tabs.")
        final_tabs = tabs_of(final_space)
        by_name = {(tab_name(t) or "").casefold(): t for t in final_tabs}

        for item in tabs_config:
            name, key = item["name"], item["key"]
            tab = by_name.get(name.casefold())
            if tab is None:
                raise AgentorchError(f"La tab '{name}' no aparece en el estado final de Herdr.")
            tid = tab_id(tab)
            ids = extract_tab_ids(tab)
            if not tid:
                raise AgentorchError(f"No se pudo recuperar tab_id para '{name}'.")
            registry["herdr"]["tabs"][key].update({
                "tab_id": tid,
                "terminal_id": ids["terminal_id"],
                "pane_id": ids["pane_id"],
            })
            save_registry(registry)
            log(f"{name}: tab={tid}, terminal={ids['terminal_id']}, pane={ids['pane_id']}")

        registry["status"] = "ready"
        registry["error"] = None
        save_registry(registry)
        log("Inicialización y reconciliación completadas.")
        log(f"Tabs verificadas: {len(tabs_config)}")
        log(f"Registry: {REGISTRY_FILE}")
        log("No se han iniciado agentes Pi.")
        return 0

    except Exception as exc:
        registry["status"] = "partial"
        registry["error"] = str(exc)
        save_registry(registry)
        error(str(exc))
        error(f"Consulta el diagnóstico y registry en: {AGENTORCH_DIR}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="agentorch",
        description="Bootstrap y recuperación de spaces/tabs Herdr.")
    parser.add_argument("--version", action="version", version=f"Agentorch {VERSION}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="Crear o recuperar el space y sus tabs.")
    args = parser.parse_args()
    if args.command == "init":
        try:
            return init()
        except AgentorchError as exc:
            error(str(exc))
            return 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
