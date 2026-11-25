"""Tests for src/torcha.py.

The suite never talks to a real Herdr window. A fake `herdr-app` is placed on
PATH and keeps its state in a JSON file, so every assertion is about what the
tool asked Herdr to do and what it wrote to the registry.

Run with: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import zipfile
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_DIR = Path(os.environ.get(
    "TORCHA_SRC",
    str(Path(__file__).resolve().parent.parent / "src"),
))

TABS = [
    {"key": "orchestrator", "name": "Orquestador", "role": "Coordina.",
     "instructions": "- Reparte el trabajo."},
    {"key": "worker_1", "name": "Worker 1", "role": "Investiga.",
     "instructions": "- Investiga y reporta."},
    {"key": "worker_2", "name": "Worker 2", "role": "Implementa.",
     "instructions": "- Implementa y prueba."},
    {"key": "worker_3", "name": "Worker 3", "role": "Revisa.",
     "instructions": "- Revisa lo implementado."},
    {"key": "worker_4", "name": "Worker 4", "role": "Prueba.",
     "instructions": "- Prueba de extremo a extremo."},
]

# A stand-in for the real binary: same command shapes, no window.
FAKE_HERDR = '''#!/usr/bin/env python3
import json, os, sys

STATE = os.environ["FAKE_HERDR_STATE"]


def load():
    with open(STATE) as fh:
        return json.load(fh)


def save(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def options(argv):
    opts, index = {}, 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("--"):
            index += 1
            continue
        key = token[2:]
        value = "true"
        if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            value = argv[index + 1]
            index += 1
        opts[key] = value
        index += 1
    return opts


def shown(state):
    """A copy of the spaces as `ls` reports them, honouring the app delay."""
    view = json.loads(json.dumps(state["spaces"]))
    for space in state["spaces"]:
        for tab in space["tabs"]:
            for terminal in tab["terminals"]:
                delay = terminal.get("app_delay", 0)
                if delay > 0:
                    terminal["app_delay"] = delay - 1
                    for seen in view:
                        if seen["id"] == space["id"]:
                            for tab_seen in seen["tabs"]:
                                if tab_seen["id"] == tab["id"]:
                                    for terminal_seen in tab_seen["terminals"]:
                                        if terminal_seen["terminal"] == terminal["terminal"]:
                                            terminal_seen["app"] = None
                                            terminal_seen["status"] = None
    return view


def new_tab(state, name, argv, delay, folder=None):
    number = sum(len(space["tabs"]) for space in state["spaces"]) + len(state["spaces"]) + 1
    tab = {
        "id": "tb%02d" % number,
        "name": name,
        "active": False,
        "settled": False,
        "terminals": [{
            "terminal": "t%02d" % number,
            "pane": "p%02d" % number,
            "cwd": folder,
            "app": "pi",
            "status": "working",
            "app_delay": delay,
            "pid": 1000 + number,
        }],
    }
    if argv is not None:
        tab["argv"] = argv
    return tab


def main(argv):
    if argv == ["--version"]:
        print("herdr-app test")
        return 0

    state = load()
    state.setdefault("calls", [])
    state["calls"].append(argv)

    if argv == ["ls"]:
        if state.get("ls_fails"):
            print(json.dumps({"error": "the app is not running"}))
            return 1
        view = shown(state)
        save(state)
        print(json.dumps({"spaces": view}))
        return 0

    if len(argv) < 2 or argv[0] != "do":
        print(json.dumps({"error": "unknown command %r" % argv}))
        return 1

    command, opts = argv[1], options(argv[2:])
    delay = state.get("app_delay_default", 0)

    if command == "space.new":
        space = {
            "id": "sp%02d" % (len(state["spaces"]) + 1),
            "name": opts.get("name"),
            "folder": opts.get("folder"),
            "active": True,
            "tabs": [new_tab(state, opts.get("tab", "1"), opts.get("argv"), delay,
                             opts.get("folder"))],
        }
        space["tabs"][0]["active"] = True
        state["spaces"].append(space)
        save(state)
        tab = space["tabs"][0]
        print(json.dumps({"space": space["id"], "tab": tab["id"],
                          "terminal": tab["terminals"][0]["terminal"]}))
        return 0

    if command == "tab.new":
        space = next((s for s in state["spaces"] if s["id"] == opts.get("space")), None)
        if space is None:
            print(json.dumps({"error": "no such space"}))
            return 1
        tab = new_tab(state, opts.get("name", "1"), opts.get("argv"), delay,
                      opts.get("folder"))
        space["tabs"].append(tab)
        # Un id de eco no es la verdad: `ls` es quien la dice.
        echo = state.get("tab_new_echo") or {"tab": tab["id"],
                                             "terminal": tab["terminals"][0]["terminal"]}
        save(state)
        print(json.dumps(echo))
        return 0

    if command == "tab.close":
        for space in state["spaces"]:
            space["tabs"] = [t for t in space["tabs"] if t["id"] != opts.get("id")]
        save(state)
        print(json.dumps({"ok": True}))
        return 0

    if command in ("space.select", "tab.select", "space.close"):
        save(state)
        print(json.dumps({"ok": True}))
        return 0

    if command == "tab.rename":
        for space in state["spaces"]:
            for tab in space["tabs"]:
                if tab["id"] == opts.get("id"):
                    tab["name"] = opts.get("name")
        save(state)
        print(json.dumps({"ok": True}))
        return 0

    if command == "tab.move":
        tab_id, index = opts.get("id"), int(opts.get("index", "1"))
        for space in state["spaces"]:
            ids = [tab["id"] for tab in space["tabs"]]
            if tab_id in ids:
                tab = space["tabs"].pop(ids.index(tab_id))
                space["tabs"].insert(index - 1, tab)
        save(state)
        print(json.dumps({"ok": True}))
        return 0

    print(json.dumps({"error": "unknown command %r" % command}))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


FAKE_HC = '''#!/usr/bin/env python3
import json, os, sys

STATE = os.environ["FAKE_HERDR_STATE"]


def _save(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def main(argv):
    with open(STATE) as fh:
        state = json.load(fh)
    state.setdefault("hc_calls", []).append(argv)

    if argv == ["server", "start"]:
        if state.get("hc_start_fails"):
            print(json.dumps({"error": "cannot start"}))
            return 1
        state["hc_down"] = False
        _save(state)
        print(json.dumps({"ok": True}))
        return 0

    if argv == ["ls"]:
        if state.get("hc_down"):
            _save(state)
            print(json.dumps({"error": "core not running"}))
            return 1
        terminals = []
        for space in state["spaces"]:
            for tab in space["tabs"]:
                for terminal in tab["terminals"]:
                    terminals.append({
                        "address": terminal["terminal"],
                        "cwd": terminal.get("cwd"),
                        "agent": "pi" if terminal.get("app") else "bash",
                        "status": terminal.get("status"),
                        "where": "%s / %s" % (space.get("name"), tab.get("name")),
                    })
        _save(state)
        print(json.dumps({"terminals": terminals}))
        return 0

    if argv[:1] == ["kill"] and len(argv) == 2:
        for space in state["spaces"]:
            for tab in space["tabs"]:
                for terminal in tab["terminals"]:
                    if terminal["terminal"] == argv[1]:
                        terminal["app"] = None
                        terminal["pid"] = None
                        terminal["status"] = None
                        _save(state)
                        print(json.dumps({"ok": True}))
                        return 0
        _save(state)
        print(json.dumps({"error": "unknown terminal"}))
        return 1

    if argv[:1] == ["send"] and len(argv) >= 3:
        if state.get("hc_send_fails"):
            _save(state)
            print(json.dumps({"error": "the core refused the send"}))
            return 1
        address, text = argv[1], " ".join(argv[2:])
        state.setdefault("hc_sent", []).append([address, text])
        for space in state["spaces"]:
            for tab in space["tabs"]:
                for terminal in tab["terminals"]:
                    if terminal["terminal"] == address:
                        if text.startswith("pi"):
                            terminal["app"] = "pi"
                            terminal["pid"] = state.get("next_pid", 9000)
                            terminal["status"] = "working"
                        _save(state)
                        print(json.dumps({"ok": True}))
                        return 0
        _save(state)
        print(json.dumps({"error": "unknown terminal"}))
        return 1

    if argv[:1] == ["keys"] and len(argv) >= 3:
        state.setdefault("hc_keys", []).append([argv[1]] + argv[2:])
        for space in state["spaces"]:
            for tab in space["tabs"]:
                for terminal in tab["terminals"]:
                    if terminal["terminal"] == argv[1] and "ctrl+d" in argv[2:]:
                        terminal["app"] = None
                        terminal["pid"] = None
                        terminal["status"] = None
        _save(state)
        print(json.dumps({"ok": True}))
        return 0

    if argv[:1] == ["wait"] and len(argv) >= 2:
        if "--output" in argv:
            ok = bool(state.get("hc_ready", True))
        else:
            ok = not state.get("hc_wait_fails")
        _save(state)
        print(json.dumps({"ok": ok}))
        return 0 if ok else 1

    if len(argv) != 2 or argv[0] != "get":
        _save(state)
        print(json.dumps({"error": "unsupported"}))
        return 1

    for space in state["spaces"]:
        for tab in space["tabs"]:
            for terminal in tab["terminals"]:
                if terminal["terminal"] == argv[1]:
                    _save(state)
                    running = bool(terminal.get("app"))
                    fg = terminal.get("fg_argv") or (
                        ["pi"] if running else ["/usr/bin/bash"])
                    print(json.dumps({"address": argv[1],
                                      "foreground": {"name": fg[0],
                                                     "pid": terminal.get("pid"),
                                                     "argv": fg},
                                      "status": {"app": terminal.get("app"),
                                                 "state": terminal.get("status")}}))
                    return 0
    _save(state)
    print(json.dumps({"error": "unknown terminal"}))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


def load_modules():
    """Importa el paquete desde SRC_DIR y expone los módulos que usa la suite."""
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    for name in [n for n in list(sys.modules) if n == "torcha" or n.startswith("torcha.")]:
        del sys.modules[name]

    import torcha.bootstrap
    import torcha.commands.discover
    import torcha.commands.doctor
    import torcha.commands.handoff
    import torcha.commands.init
    import torcha.commands.ls
    import torcha.commands.recover
    import torcha.commands.rename
    import torcha.commands.start
    import torcha.commands.status
    import torcha.commands.templates
    import torcha.templates
    import torcha.config
    import torcha.discovery
    import torcha.errors
    import torcha.git
    import torcha.herdr
    import torcha.live
    import torcha.project

    return SimpleNamespace(
        init=torcha.commands.init.init,
        TorchaError=torcha.errors.TorchaError,
        load_config=torcha.config.load_config,
        parse_bootstrap=torcha.config.parse_bootstrap,
        bootstrap_text=torcha.bootstrap.bootstrap_text,
        pi_argv=torcha.bootstrap.pi_argv,
        extract_tab_ids=torcha.herdr.extract_tab_ids,
        tab_app=torcha.herdr.tab_app,
        get_spaces=torcha.herdr.get_spaces,
        time=torcha.herdr.time,
        sys=torcha.git.sys,
        paths=torcha.project,
        discovery=torcha.discovery,
        live=torcha.live,
        discover=torcha.commands.discover.discover,
        config=torcha.config,
        herdr=torcha.herdr,
        init_module=torcha.commands.init,
        ls=torcha.commands.ls.ls,
        status=torcha.commands.status.status,
        handoff=torcha.handoff,
        handoff_command=torcha.commands.handoff,
        start=torcha.commands.start.start,
        recover=torcha.commands.recover.recover,
        recover_module=torcha.commands.recover,
        rename=torcha.commands.rename.rename,
        templates=torcha.templates,
        templates_command=torcha.commands.templates.templates,
        doctor=torcha.commands.doctor.doctor,
        doctor_module=torcha.commands.doctor,
    )


class Project:
    """A throwaway project wired to a fake Herdr."""

    def __init__(self, root: Path, module, state: Path, bin_dir: Path):
        self.root = root
        self.module = module
        self.state = state
        self.bin_dir = bin_dir

    def read_state(self):
        return json.loads(self.state.read_text())

    def calls(self):
        return self.read_state()["calls"]

    def commands(self):
        return [call[1] for call in self.calls() if len(call) > 1 and call[0] == "do"]

    def options_for(self, command):
        found = []
        for call in self.calls():
            if len(call) > 1 and call[0] == "do" and call[1] == command:
                opts, index = {}, 2
                while index < len(call):
                    if call[index].startswith("--"):
                        key = call[index][2:]
                        value = "true"
                        if index + 1 < len(call) and not call[index + 1].startswith("--"):
                            value = call[index + 1]
                            index += 1
                        opts[key] = value
                    index += 1
                found.append(opts)
        return found

    def registry(self):
        return json.loads((self.root / ".torcha" / "registry.json").read_text())

    def bootstrap(self, key):
        return (self.root / ".torcha" / "bootstrap" / f"{key}.md").read_text()


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=root, check=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "herdr-app"
    fake.write_text(FAKE_HERDR)
    fake.chmod(0o755)
    core = bin_dir / "hc"
    core.write_text(FAKE_HC)
    core.chmod(0o755)

    state = tmp_path / "herdr-state.json"
    state.write_text(json.dumps({"spaces": [], "calls": []}))

    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_HERDR_STATE", str(state))

    module = load_modules()
    torcha_dir = root / ".torcha"
    monkeypatch.setattr(module.paths, "PROJECT_DIR", root)
    monkeypatch.setattr(module.paths, "PROJECT_NAME", root.name)
    monkeypatch.setattr(module.paths, "TORCHA_DIR", torcha_dir)
    monkeypatch.setattr(module.paths, "CONFIG_FILE", torcha_dir / "agents.json")
    monkeypatch.setattr(module.paths, "REGISTRY_FILE", torcha_dir / "registry.json")
    monkeypatch.setattr(module.paths, "BOOTSTRAP_DIR", torcha_dir / "bootstrap")

    torcha_dir.mkdir(parents=True, exist_ok=True)
    (torcha_dir / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi", "bootstrap": "greet"}, "tabs": TABS}))

    return Project(root, module, state, bin_dir)


# --- configuration and prompt text -----------------------------------------


@pytest.mark.parametrize("value,expected", [
    ("greet", "greet"),
    ("RECOVER", "recover"),
    ("none", "none"),
    (True, "greet"),
    (False, "none"),
])
def test_parse_bootstrap_accepts_modes_and_legacy_bools(project, value, expected):
    assert project.module.parse_bootstrap(value) == expected


def test_parse_bootstrap_rejects_unknown_value(project):
    with pytest.raises(project.module.TorchaError, match="pi.bootstrap"):
        project.module.parse_bootstrap("loud")


def test_greet_prompt_does_not_ask_for_repository_inspection(project):
    text = project.module.bootstrap_text(TABS[1], "greet")
    assert "Worker 1" in text
    assert str(project.root) in text
    assert "git status" not in text
    assert "mem_search" not in text
    assert "Do not run any command" in text


def test_recover_prompt_reads_the_handoff_first(project):
    """The file exists; the Engram pointer does not yet, so the file goes first."""
    text = project.module.bootstrap_text(TABS[0], "recover")
    assert ".torcha/handoffs/orchestrator/" in text
    assert "git rev-parse HEAD" in text
    assert "mem_search" in text
    assert "READY" in text
    # El handoff y su validación contra el repo van antes que Engram.
    assert text.index("handoffs/orchestrator") < text.index("mem_search")
    assert text.index("git rev-parse HEAD") < text.index("mem_search")


def test_config_rejects_pi_executable_with_arguments(project):
    (project.root / ".torcha" / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi --model x"}, "tabs": TABS}))
    with pytest.raises(project.module.TorchaError, match="pi.executable"):
        project.module.load_config()


@pytest.mark.parametrize("value", [0, -1, "ten", 2.5, True])
def test_an_invalid_max_tabs_is_refused(project, value):
    """El tope del equipo se lee del proyecto, y se valida: no se ignora."""
    (project.root / ".torcha" / "agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "max_tabs": value, "tabs": TABS}))

    with pytest.raises(project.module.TorchaError, match="max_tabs"):
        project.module.load_config()


# --- Herdr output parsing --------------------------------------------------


def test_extract_tab_ids_reads_the_real_ls_shape(project):
    tab = {"id": "tb1", "terminals": [{"terminal": "t1", "pane": "p1", "app": "pi"}]}
    assert project.module.extract_tab_ids(tab) == {"terminal_id": "t1", "pane_id": "p1"}


def test_tab_app_reads_the_application_from_the_terminal(project):
    tab = {"terminals": [{"terminal": "t1", "app": "pi"}]}
    assert project.module.tab_app(tab) == "pi"
    assert project.module.tab_app({"terminals": [{"terminal": "t1"}]}) is None


def test_get_spaces_finds_the_space_list(project):
    payload = {"spaces": [{"id": "sp1", "folder": "/tmp/x", "tabs": []}]}
    assert project.module.get_spaces(payload) == [{"id": "sp1", "folder": "/tmp/x", "tabs": []}]


# --- init ------------------------------------------------------------------


def test_init_creates_one_space_and_every_configured_tab(project):
    assert project.module.init() == 0

    state = project.read_state()
    assert len(state["spaces"]) == 1
    names = [tab["name"] for tab in state["spaces"][0]["tabs"]]
    assert names == [tab["name"] for tab in TABS]
    assert project.commands().count("space.new") == 1
    assert project.commands().count("tab.new") == 4


def test_init_starts_pi_with_its_bootstrap_file_in_every_created_tab(project):
    assert project.module.init() == 0

    for options in project.options_for("space.new") + project.options_for("tab.new"):
        argv = json.loads(options["argv"])
        assert argv[0] == "pi"
        assert argv[1] == "--skill"
        assert Path(argv[2]).is_file()          # the packaged team skill ships
        assert argv[3] == "--session-id"
        uuid.UUID(argv[4])
        reference = argv[5]
        assert reference.startswith("@.torcha/bootstrap/")
        assert (project.root / reference.lstrip("@")).is_file()


def test_init_writes_one_bootstrap_file_per_role(project):
    assert project.module.init() == 0
    for tab in TABS:
        text = project.bootstrap(tab["key"])
        assert tab["name"] in text
        assert tab["role"] in text


def test_init_second_run_creates_nothing_and_does_not_fail(project):
    assert project.module.init() == 0
    created = (project.commands().count("space.new"),
               project.commands().count("tab.new"))
    assert created == (1, 4)

    assert project.module.init() == 0
    assert (project.commands().count("space.new"),
            project.commands().count("tab.new")) == created
    assert len(project.read_state()["spaces"][0]["tabs"]) == len(TABS)


def test_init_focuses_only_the_first_configured_tab(project):
    assert project.module.init() == 0

    state = project.read_state()
    orchestrator = state["spaces"][0]["tabs"][0]
    selected = [options["id"] for options in project.options_for("tab.select")]
    assert selected == [orchestrator["id"]]
    spaces = [options["id"] for options in project.options_for("space.select")]
    assert spaces == [state["spaces"][0]["id"]]


def test_init_records_ids_and_application_in_the_registry(project):
    assert project.module.init() == 0

    registry = project.registry()
    assert registry["status"] == "ready"
    assert registry["error"] is None
    for tab in TABS:
        entry = registry["herdr"]["tabs"][tab["key"]]
        assert entry["tab_id"]
        assert entry["terminal_id"]
        assert entry["pane_id"]
        assert entry["app"] == "pi"


def test_init_waits_for_the_application_to_report_itself(project):
    project.state.write_text(json.dumps(
        {"spaces": [], "calls": [], "app_delay_default": 1}))
    project.module.time.sleep = lambda _seconds: None

    assert project.module.init() == 0
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["app"] == "pi"


def test_an_interview_keeps_the_focus_and_the_logs_in_this_tab(project, monkeypatch,
                                                              capsys):
    """Closing the interview's Pi must not jump away from torcha's logs."""
    (project.root / ".torcha/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    def fake_interview(candidates, seen=None, say=None):
        (project.root / ".torcha/agents.json").write_text(json.dumps({
            "pi": {"executable": "pi", "bootstrap": "greet"},
            "tabs": [{"key": "orchestrator", "name": "Orquestador",
                      "role": "Coordinates.", "instructions": ""}]}))
        return project.module.init_module.Interview(ran=True)

    monkeypatch.setattr(project.module.init_module, "start_interview", fake_interview)

    assert project.module.init() == 0

    # La entrevista ocupó esta tab: el foco no se mueve a la del orquestador.
    assert project.options_for("space.select") == []
    assert project.options_for("tab.select") == []
    out = capsys.readouterr().out
    tid = project.registry()["herdr"]["tabs"]["orchestrator"]["tab_id"]
    assert f"Orchestrator: Orquestador ({tid})." in out
    assert "stay in this tab" in out


def test_a_configuration_with_nothing_pending_still_focuses_the_orchestrator(
        project, monkeypatch):
    """The focus is deliberate feedback for a manual run: keep it."""
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)
    called = {}
    monkeypatch.setattr(project.module.init_module, "start_interview",
                        lambda candidates, seen=None, say=None:
                        called.setdefault("ran", True))

    assert project.module.init() == 0

    assert "ran" not in called
    space = project.read_state()["spaces"][0]
    selected = [options["id"] for options in project.options_for("tab.select")]
    assert selected == [space["tabs"][0]["id"]]
    assert [options["id"] for options in project.options_for("space.select")] == \
        [space["id"]]


def test_init_moves_the_orchestrator_to_the_first_position(project):
    # A space already exists with the four workers, but no orchestrator.
    workers = [dict(tab, key=tab["key"]) for tab in TABS[1:]]
    tabs = [
        {"id": f"tb{i + 2}", "name": tab["name"], "active": False, "settled": False,
         "terminals": [{"terminal": f"t{i + 2}", "pane": f"p{i + 2}",
                        "cwd": str(project.root), "app": "pi", "status": "idle"}]}
        for i, tab in enumerate(workers)
    ]
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": str(project.root),
        "active": True, "tabs": tabs,
    }], "calls": []}))

    assert project.module.init() == 0
    moves = project.options_for("tab.move")
    assert len(moves) == 1
    assert moves[0]["index"] == "1"


def test_second_run_does_not_wait_for_tabs_it_did_not_start(project):
    # Tabs that exist but never reported an application: exactly the case where
    # waiting on every configured tab would burn the whole deadline.
    tabs = [
        {"id": f"tb{i}", "name": tab["name"], "active": i == 1, "settled": False,
         "terminals": [{"terminal": f"t{i}", "pane": f"p{i}",
                        "app": None, "status": None}]}
        for i, tab in enumerate(TABS, start=1)
    ]
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": str(project.root),
        "active": True, "tabs": tabs,
    }], "calls": []}))

    assert project.module.init() == 0
    # Three reads: locate the space, re-read before creating, verify at the end.
    # Any extra read means the tool polled for tabs it never started.
    assert project.calls().count(["ls"]) == 3
    assert project.registry()["status"] == "ready"


def test_bootstrap_none_launches_pi_without_a_prompt(project):
    (project.root / ".torcha" / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi", "bootstrap": "none"}, "tabs": TABS}))

    assert project.module.init() == 0
    for options in project.options_for("space.new") + project.options_for("tab.new"):
        assert "argv" not in options


def test_every_launched_agent_loads_the_packaged_team_skill(project):
    """La skill del equipo viaja en el argv: no se descubre, se carga siempre."""
    agent = "22222222-2222-4222-8222-222222222222"
    argv = project.module.pi_argv(
        {"pi": {"executable": "pi", "bootstrap": "greet"}}, TABS[0],
        session_id=agent)

    assert argv[0] == "pi"
    assert argv[1] == "--skill"
    skill = Path(argv[2])
    assert skill.is_absolute()
    assert skill.is_file()                       # viaja con el paquete
    assert skill.parent.name == "torcha" and skill.name == "SKILL.md"
    assert argv[argv.index("--session-id") + 1] == agent
    assert "@.torcha/bootstrap/orchestrator.md" in argv


def test_bootstrap_none_builds_no_argv_at_all(project):
    argv = project.module.pi_argv(
        {"pi": {"executable": "pi", "bootstrap": "none"}}, TABS[0],
        session_id="22222222-2222-4222-8222-222222222222")
    assert argv is None


def test_the_setup_interview_does_not_load_the_team_skill(project, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command

        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr(project.module.init_module.subprocess, "run", fake_run)
    project.module.init_module._run_interview(Path("/tmp/x.md"), "pi")

    setup = str(project.module.init_module.SETUP_SKILL)
    assert captured["command"] == ["pi", "--skill", setup, "@/tmp/x.md"]


# --- the git precondition --------------------------------------------------


def test_init_refuses_to_run_outside_a_repository_without_a_terminal(
        project, tmp_path, monkeypatch):
    # Outside any repository: `tmp_path` is not inside the fixture's repo.
    plain = tmp_path / "outside"
    plain.mkdir()
    monkeypatch.setattr(project.module.paths, "PROJECT_DIR", plain)
    monkeypatch.setattr(project.module.paths, "TORCHA_DIR", plain / ".torcha")
    monkeypatch.setattr(project.module.paths, "CONFIG_FILE", plain / ".torcha" / "agents.json")
    monkeypatch.setattr(project.module.paths, "REGISTRY_FILE", plain / ".torcha" / "registry.json")
    monkeypatch.setattr(project.module.paths, "BOOTSTRAP_DIR", plain / ".torcha" / "bootstrap")
    monkeypatch.setattr(project.module.sys.stdin, "isatty", lambda: False)

    with pytest.raises(project.module.TorchaError,
                       match="is not a git repository"):
        project.module.init()

    # Nothing was created and Herdr was never called.
    assert not (plain / ".torcha").exists()
    assert project.calls() == []


def test_init_runs_the_git_check_before_touching_herdr(project):
    assert project.module.init() == 0
    calls = project.calls()
    assert calls and calls[0] == ["ls"]
    assert project.registry()["status"] == "ready"


# --- discovery of declared agents ------------------------------------------


def write_agent(path, name, description, extra=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nBody.\n")


def test_parse_frontmatter_reads_scalars_and_block_scalars(project):
    text = "---\nname: lead\ndescription: >\n  Coordinates the\n  whole team.\n---\n"
    fields = project.module.discovery.parse_frontmatter(text)
    assert fields["name"] == "lead"
    assert fields["description"] == "Coordinates the whole team."


def test_parse_frontmatter_returns_empty_without_a_block(project):
    assert project.module.discovery.parse_frontmatter("# Title\n\nProse.\n") == {}


def test_slug_produces_keys_the_config_validator_accepts(project):
    slug = project.module.discovery.slug
    assert slug("SDD Verify") == "sdd_verify"
    assert slug("job-builder") == "job_builder"
    assert slug("123") == "agent_123"
    assert slug("!!!") == "agent"


def test_scan_finds_project_agents_and_skips_undeclared_files(project):
    write_agent(project.root / ".pi/agents/lead.md", "lead", "Coordinates the team.")
    write_agent(project.root / ".pi/agents/builder.md", "builder", "Implements changes.")
    (project.root / ".pi/agents/modes.md").write_text("# Modes\n\nProse only.\n")

    found = project.module.discovery.scan(project.root, user_home=project.root / "nohome")
    assert [c.name for c in found] == ["builder", "lead"]
    assert all(c.scope == "project" for c in found)


def test_scan_deduplicates_the_same_role_across_sources(project):
    write_agent(project.root / ".claude/agents/reviewer.md", "reviewer", "Reviews code.")
    write_agent(project.root / ".cursor/agents/reviewer.md", "reviewer", "Reviews code too.")

    found = project.module.discovery.scan(project.root, user_home=project.root / "nohome")
    assert len(found) == 1
    assert found[0].source == "claude"


def test_scan_skips_a_file_with_a_name_but_no_description(project):
    (project.root / ".pi/agents/half.md").parent.mkdir(parents=True, exist_ok=True)
    (project.root / ".pi/agents/half.md").write_text("---\nname: half\n---\n\nBody.\n")

    found = project.module.discovery.scan(project.root, user_home=project.root / "nohome")
    assert found == []


def test_scan_reads_user_agents_when_the_project_declares_none(project):
    home = project.root / "home"
    write_agent(home / ".pi/agent/agents/helper.md", "helper", "Helps out.")

    found = project.module.discovery.scan(project.root, user_home=home)
    assert [c.name for c in found] == ["helper"]
    assert found[0].scope == "user"


def test_choose_puts_a_declared_orchestrator_first(project):
    discovery = project.module.discovery
    candidates = [
        discovery.Candidate("builder", "builder", "Implements.", "pi", "project", "p"),
        discovery.Candidate("lead", "lead", "Runs the team.", "pi", "project", "p"),
    ]
    tabs = discovery.choose(candidates)
    assert tabs[0] == {"key": "orchestrator", "name": "Orchestrator",
                       "role": "Runs the team."}


def test_choose_synthesises_an_orchestrator_when_none_is_declared(project):
    tabs = project.module.discovery.choose([])
    assert tabs == [project.module.discovery.DEFAULT_ORCHESTRATOR]


def test_choose_does_not_elect_an_agent_that_merely_mentions_lead(project):
    """Real case: "Indexes lead sources" must not beat "Job-search orchestrator".

    Neither name states a role, so only the descriptions can decide.
    """
    discovery = project.module.discovery
    candidates = [
        discovery.Candidate("job_scout", "job-scout",
                            "Indexes lead sources (job fairs, portals).",
                            "pi", "project", "p"),
        discovery.Candidate("job_triage", "job-triage",
                            "Job-search orchestrator. Owns triage.",
                            "pi", "project", "p"),
    ]
    assert discovery.orchestrator_score(candidates[0]) == 0
    assert discovery.orchestrator_score(candidates[1]) == 1
    assert [tab["name"] for tab in discovery.choose(candidates)] == ["Orchestrator", "Scout"]


def test_choose_prefers_a_name_that_states_the_role(project):
    discovery = project.module.discovery
    candidates = [
        discovery.Candidate("helper", "helper", "Says it coordinates things.",
                            "pi", "project", "p"),
        discovery.Candidate("lead", "lead", "Runs the team.", "pi", "project", "p"),
    ]
    tabs = discovery.choose(candidates)
    assert tabs[0] == {"key": "orchestrator", "name": "Orchestrator",
                       "role": "Runs the team."}


def test_role_name_strips_the_project_namespace_and_seniority(project):
    role_name = project.module.discovery.role_name
    assert role_name("job-scout", {"job"}) == "Scout"
    assert role_name("Senior Orchestrator") == "Orchestrator"
    assert role_name("Porteador Implementer") == "Porteador Implementer"
    # Seniority alone is still the only name there is.
    assert role_name("job-senior", {"job"}) == "Senior"
    # Stripping the prefix would leave nothing but a digit.
    assert role_name("Worker 1", {"worker"}) == "Worker 1"


def test_repeated_prefixes_are_discovered_not_assumed(project):
    prefixes = project.module.discovery.repeated_prefixes
    assert prefixes(["job-scout", "job-auditor"]) == {"job"}
    assert prefixes(["scout", "auditor"]) == set()
    assert prefixes(["Scout"]) == set()
    # Families are per token: one prefixed family does not hide the others.
    assert prefixes(["job-scout", "job-auditor", "repro"]) == {"job"}


def test_choose_names_roles_not_the_project_prefix(project):
    discovery = project.module.discovery
    candidates = [
        discovery.Candidate("job_senior", "job-senior", "Job-search orchestrator.",
                            "pi", "project", "p"),
        discovery.Candidate("job_scout", "job-scout", "Indexes sources.",
                            "pi", "project", "p"),
        discovery.Candidate("job_auditor", "job-auditor", "Audits state.",
                            "pi", "project", "p"),
    ]
    assert [(tab["key"], tab["name"]) for tab in discovery.choose(candidates)] == [
        ("orchestrator", "Orchestrator"), ("scout", "Scout"), ("auditor", "Auditor"),
    ]


def test_choose_caps_tabs_and_keeps_keys_unique(project):
    discovery = project.module.discovery
    candidates = [
        discovery.Candidate("dup", "dup", f"Role {i}", "pi", "project", "p")
        for i in range(8)
    ]
    tabs = discovery.choose(candidates, max_tabs=3)
    assert len(tabs) == 3
    assert len({tab["key"] for tab in tabs}) == 3


def test_init_generates_the_config_from_declared_agents(project):
    (project.root / ".torcha/agents.json").unlink()
    write_agent(project.root / ".pi/agents/lead.md", "lead", "Orchestrates the team.")
    write_agent(project.root / ".pi/agents/builder.md", "builder", "Implements changes.")

    assert project.module.init() == 0

    config = json.loads((project.root / ".torcha/agents.json").read_text())
    assert [tab["key"] for tab in config["tabs"]] == ["orchestrator", "builder"]
    assert config["tabs"][0]["name"] == "Orchestrator"


def test_init_seeds_the_config_from_named_tabs_with_sessions_first(project):
    """The team in use beats the catalogue: named live tabs win, active first."""
    (project.root / ".torcha/agents.json").unlink()
    write_agent(project.root / ".pi/agents/catalogued.md", "catalogued",
                "Declared but not running.")
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": str(project.root), "active": True,
        "tabs": [
            {"id": "tb1", "name": "Orchestrator", "active": True,
             "terminals": [{"terminal": "t1", "pane": "p1",
                            "cwd": str(project.root), "app": "pi",
                            "status": "idle"}]},
            {"id": "tb2", "name": "Builder", "active": False,
             "terminals": [{"terminal": "t2", "pane": "p2",
                            "cwd": str(project.root), "app": "pi",
                            "status": "working"}]},
            {"id": "tb3", "name": "Idle", "active": False,
             "terminals": [{"terminal": "t3", "pane": "p3",
                            "cwd": str(project.root), "app": None,
                            "status": None}]},
        ],
    }], "calls": []}))

    assert project.module.init() == 0

    config = json.loads((project.root / ".torcha/agents.json").read_text())
    assert [tab["name"] for tab in config["tabs"]] == ["Orchestrator", "Builder", "Idle"]
    # Nothing was created: the named live tabs were reused.
    assert project.commands().count("tab.new") == 0


def test_init_reuses_a_live_orchestrator_named_lead(project):
    """Role names in the config must not duplicate a live tab called "Lead"."""
    (project.root / ".torcha/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": str(project.root), "active": True,
        "tabs": [{"id": "tb1", "name": "Lead", "active": True,
                  "terminals": [{"terminal": "t1", "pane": "p1",
                                 "cwd": str(project.root), "app": "pi",
                                 "status": "idle"}]}],
    }], "calls": []}))

    assert project.module.init() == 0

    config = json.loads((project.root / ".torcha/agents.json").read_text())
    assert config["tabs"][0]["name"] == "Orchestrator"
    assert project.commands().count("tab.new") == 0
    assert project.commands().count("space.new") == 0


# --- the terminal pid -------------------------------------------------------


def test_created_tabs_record_their_session_id_and_adopted_ones_do_not(project):
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))

    assert project.module.init() == 0

    tabs = project.registry()["herdr"]["tabs"]
    assert tabs["orchestrator"]["session_id"] is None      # adoptada, no creada
    worker = tabs["worker_1"]["session_id"]
    uuid.UUID(worker)                                      # es un uuid
    argv = json.loads(project.options_for("tab.new")[0]["argv"])
    # el mismo que se lanzó
    assert argv[argv.index("--session-id") + 1] == worker


def test_init_records_the_pid_of_each_terminal(project):
    assert project.module.init() == 0

    pids = [project.registry()["herdr"]["tabs"][tab["key"]]["pid"] for tab in TABS]
    assert all(isinstance(pid, int) for pid in pids)
    assert len(set(pids)) == len(pids)


def test_terminal_pid_is_none_for_an_unknown_terminal(project):
    assert project.module.herdr.terminal_pid("t99") is None


def test_terminal_pid_is_none_without_herdr_core(project, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(project.module.herdr.subprocess, "run", missing)
    assert project.module.herdr.terminal_pid("t01") is None


def test_a_tab_without_an_agent_records_no_pid(project):
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": str(project.root), "active": True,
        "tabs": [{"id": "tb1", "name": "Orquestador", "active": True,
                  "terminals": [{"terminal": "t1", "pane": "p1",
                                 "cwd": str(project.root), "app": None,
                                 "status": None, "pid": 4242}]}],
    }], "calls": []}))

    assert project.module.init() == 0

    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["app"] is None
    assert entry["pid"] is None


# --- status -----------------------------------------------------------------


def write_registry(project, space="sp01", tabs=None, status="ready"):
    payload = {"version": "0.3.0", "status": status, "error": None,
               "herdr": {"space_id": space, "tabs": tabs or {}}}
    (project.root / ".torcha" / "registry.json").write_text(json.dumps(payload))
    return payload


def live_tab(tab_id_value, name, terminal, app="pi", pid=None):
    return {"id": tab_id_value, "name": name, "active": False,
            "terminals": [{"terminal": terminal, "pane": "p", "cwd": None,
                           "app": app, "status": "idle" if app else None,
                           "pid": pid}]}


def status_space(space_id_value, tabs):
    return {"id": space_id_value, "name": "proj", "folder": "/x",
            "active": True, "tabs": tabs}


def seed_live(project, tabs, space="sp01"):
    project.state.write_text(json.dumps({
        "spaces": [status_space(space, tabs)], "calls": []}))


def test_status_reports_an_alive_role(project, capsys):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])

    assert project.module.status(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"][0]["state"] == "alive"
    assert payload["summary"] == {"total": 1, "alive": 1, "diverged": False}


def test_status_reports_a_down_role_without_failing(project, capsys):
    write_registry(project, tabs={"worker_1": {
        "name": "Worker 1", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": None, "pid": None}})
    seed_live(project, [live_tab("tb1", "Worker 1", "t1", app=None)])

    assert project.module.status(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"][0]["state"] == "down"
    assert payload["summary"]["alive"] == 0


def test_status_reports_a_tab_that_no_longer_exists(project, capsys):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500}})
    seed_live(project, [live_tab("tb2", "Other", "t2", pid=500)])

    assert project.module.status(as_json=True) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"][0]["state"] == "missing"
    assert "the tab" in payload["roles"][0]["detail"]
    assert payload["summary"]["diverged"] is True


def test_status_reports_a_terminal_that_no_longer_exists(project, capsys):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t9", pid=500)])

    assert project.module.status(as_json=True) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"][0]["state"] == "missing"
    assert "the terminal" in payload["roles"][0]["detail"]


def test_status_reports_a_replaced_session(project, capsys):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=777)])

    assert project.module.status(as_json=True) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"][0]["state"] == "moved"
    assert "500" in payload["roles"][0]["detail"]


def test_status_notes_a_renamed_tab_without_failing(project, capsys):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500}})
    seed_live(project, [live_tab("tb1", "Orchestrator", "t1", pid=500)])

    assert project.module.status(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["roles"][0]["state"] == "alive"
    assert "renamed" in payload["roles"][0]["detail"]


def test_status_needs_a_registry(project):
    (project.root / ".torcha" / "registry.json").unlink(missing_ok=True)
    seed_live(project, [])

    with pytest.raises(project.module.TorchaError, match="registry"):
        project.module.status()


# --- status: the detail that decides a handoff -------------------------------


def commit_empty(project, message="next"):
    """A commit on the project, so a handoff's head falls behind HEAD."""
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", message],
                   cwd=project.root, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=project.root,
                          text=True, capture_output=True, check=True).stdout.strip()


def abandoned_commit(project):
    """A commit of this repository that is not on its branch.

    `commit-tree` writes an object and touches neither HEAD nor the index, so the
    test gets the shape a rebase leaves behind without rewriting anything.
    """
    tree = subprocess.run(["git", "mktree"], cwd=project.root, input="",
                          text=True, capture_output=True, check=True).stdout.strip()
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "commit-tree", tree, "-m", "abandoned"],
                          cwd=project.root, text=True, capture_output=True,
                          check=True).stdout.strip()


def iso_ago(**delta):
    return (datetime.now().astimezone() - timedelta(**delta)).isoformat(timespec="seconds")


def write_status_handoff(project, role, head, *, created_at=None, handoff_id=None):
    """A handoff document shaped like the ones the agents write."""
    directory = project.root / ".torcha" / "handoffs" / role
    directory.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1,
            "handoff_id": handoff_id or str(uuid.uuid4()),
            "project": project.root.name, "agent_id": role, "role": role,
            "created_at": created_at or iso_ago(minutes=5),
            "source_pi_session_id": "01a1f453-0174-7369",
            "status": "prepared",
            "git": {"branch": "master", "head": head,
                    "status_summary": "clean tree"}}
    path = directory / f"{data['handoff_id']}.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def pi_agent(tmp_path, monkeypatch):
    """A throwaway Pi agent directory: its session store and its model catalogue."""
    agent_dir = tmp_path / "pi-agent"
    (agent_dir / "sessions").mkdir(parents=True)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
    # The store of the machine running the suite is not a fixture: a role's
    # session id must only ever resolve against the throwaway store.
    monkeypatch.delenv("PI_SESSION_FILE", raising=False)
    return agent_dir


# A presence block that belongs to some other session: what an intercom tool
# result carries inside a transcript it did not write.
FOREIGN_ID = "01a21214-4e63-7118-9a50-74009be0c4b9"


def presence_block(**fields):
    """The figures Pi's own status bar shows, as it writes them beside a message.

    A block written beside a message belongs to the session that wrote it, so the
    default id is the session under test. A test that deliberately wants a block
    from somewhere else passes `id=FOREIGN_ID`.
    """
    block = {"id": SESSION,
             "name": "subagent-chat-01a21214", "cwd": "/project",
             "model": "deepseek-v4.1-flash", "pid": 14118,
             "status": "idle", "trustedLocal": True}
    block.update(fields)
    return block


def presence_line(block, shape="details"):
    """One transcript line carrying a presence block, in either shape Pi writes.

    `details` is the shape an intercom message has on this machine (the figures
    sit at `details.from`); `from` is the shape of a line that states them next
    to its own `message`. The code must not care which.
    """
    if shape == "details":
        return {"type": "custom_message", "customType": "intercom_message",
                "display": "notice",
                "details": {"from": block, "message": {"id": "m1"}},
                "content": "a message"}
    return {"type": "message", "from": block,
            "message": {"role": "user", "content": [
                {"type": "text", "text": "and now?"}]}}


def write_transcript(agent_dir, session_id, *, model="test-model", total=176283,
                     project_dir="proj", presence=None, presence_shape="details"):
    """One Pi transcript: one JSON object per line, as Pi writes them."""
    store = Path(agent_dir) / "sessions" / project_dir
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"2026-11-25T10-00-00-000Z_{session_id}.jsonl"
    records = [
        {"type": "message", "message": {"role": "user", "content": [
            {"type": "text", "text": "go"}]}},
        {"type": "message", "message": {
            "role": "assistant", "model": model,
            "usage": {"input": 10, "output": 20, "cacheRead": 0,
                      "reasoning": 0, "totalTokens": total}}},
        # La última línea no lleva `usage`: se toma el último mensaje que sí.
        {"type": "message", "message": {"role": "user", "content": [
            {"type": "text", "text": "and now?"}]}},
    ]
    blocks = [presence] if isinstance(presence, dict) else list(presence or [])
    records.extend(presence_line(block, presence_shape) for block in blocks)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


def one_role(project, *, session_id=None, pid=500):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": pid, "session_id": session_id}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=pid)])


def status_roles(capsys):
    return json.loads(capsys.readouterr().out)["roles"]


def test_status_reports_the_age_and_the_head_of_the_newest_handoff(project, capsys):
    one_role(project)
    head = commit_empty(project, "the head the agent recorded")
    write_status_handoff(project, "orchestrator", head,
                         created_at=iso_ago(days=3),
                         handoff_id="11111111-1111-4111-8111-111111111111")
    newest = write_status_handoff(project, "orchestrator", head,
                                  created_at=iso_ago(hours=2),
                                  handoff_id="22222222-2222-4222-8222-222222222222")

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert head[:7] in out
    assert "2h ago" in out                      # la antigüedad del más nuevo
    assert "3d ago" not in out                  # el anterior no se cuela

    assert project.module.status(as_json=True) == 0
    handoff = status_roles(capsys)[0]["handoff"]
    assert handoff["present"] is True
    assert handoff["handoff_id"] == "22222222-2222-4222-8222-222222222222"
    assert handoff["path"] == str(newest)
    assert handoff["head"] == head
    assert 7200 <= handoff["age_seconds"] < 7400


def test_status_says_a_role_has_no_handoff_on_its_own_line(project, capsys):
    """Un rol sin handoff no se omite: lo dice, y no hace fallar el comando."""
    write_registry(project, tabs={
        "orchestrator": {"name": "Orquestador", "tab_id": "tb1",
                         "terminal_id": "t1", "pane_id": "p1", "app": "pi",
                         "pid": 500},
        "worker_1": {"name": "Worker 1", "tab_id": "tb2", "terminal_id": "t2",
                     "pane_id": "p2", "app": "pi", "pid": 501}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500),
                        live_tab("tb2", "Worker 1", "t2", pid=501)])

    assert project.module.status() == 0
    out = capsys.readouterr().out
    said = [line for line in out.splitlines() if "no handoff:" in line]
    assert len(said) == 2                       # una por rol, ninguna omitida
    assert sum("nothing to compare: there is no handoff" in line
               for line in out.splitlines()) == 2

    assert project.module.status(as_json=True) == 0
    roles = status_roles(capsys)
    assert [role["handoff"]["present"] for role in roles] == [False, False]
    assert all(role["drift"]["commits"] is None for role in roles)
    assert all("no handoff" in role["drift"]["detail"] for role in roles)


def test_status_measures_how_far_the_repository_moved(project, capsys):
    # El estado de torcha no ensucia el árbol: es lo que un proyecto real
    # hace, y este repo hace, para que `status` hable del trabajo, no de su store.
    (project.root / ".git" / "info" / "exclude").write_text(".torcha/\n")

    one_role(project)
    head = commit_empty(project, "the handoff point")
    write_status_handoff(project, "orchestrator", head)
    commit_empty(project, "one")
    commit_empty(project, "two")

    assert project.module.status(as_json=True) == 0
    drift = status_roles(capsys)[0]["drift"]
    assert drift["commits"] == 2
    assert drift["ancestor"] is True
    assert drift["dirty"] is False
    assert drift["dirty_files"] == 0

    (project.root / "notes.txt").write_text("work in progress\n")

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "2 commit(s)" in out
    assert "1 uncommitted file(s)" in out

    assert project.module.status(as_json=True) == 0
    drift = status_roles(capsys)[0]["drift"]
    assert drift["commits"] == 2
    assert drift["dirty"] is True
    assert drift["dirty_files"] == 1


def test_status_says_a_rewritten_branch_instead_of_inventing_a_count(project, capsys):
    one_role(project)
    write_status_handoff(project, "orchestrator", abandoned_commit(project))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "not an ancestor" in out
    assert "rebased or rewritten" in out

    assert project.module.status(as_json=True) == 0
    drift = status_roles(capsys)[0]["drift"]
    assert drift["ancestor"] is False
    assert drift["commits"] is None             # no se inventa una cuenta


def test_status_reports_the_tokens_of_the_last_turn(project, pi_agent, capsys):
    session = "01a1f453-0174-7369-9a3a-111111111111"
    one_role(project, session_id=session)
    path = write_transcript(pi_agent, session)

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "176,283" in out
    assert "test-model" in out
    assert "no percentage" in out               # no hay ventana legible

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["total_tokens"] == 176283
    assert usage["model"] == "test-model"
    assert usage["transcript"] == str(path)
    assert usage["context_window"] is None
    assert usage["percent"] is None


def test_status_shows_the_percentage_only_when_the_window_is_known(
        project, pi_agent, capsys):
    session = "01a1f453-0174-7369-9a3a-222222222222"
    one_role(project, session_id=session)
    write_transcript(pi_agent, session)
    (pi_agent / "models.json").write_text(json.dumps({"providers": {"local": {
        "models": [{"id": "test-model", "contextWindow": 200000}]}}}))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "88%" in out
    assert "200,000" in out

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["context_window"] == 200000
    assert usage["percent"] == 88


def test_status_prefers_the_percentage_the_transcript_states(
        project, pi_agent, capsys):
    """Pi ya calculó el porcentaje: se usa el suyo, no el que sale de dividir."""
    session = SESSION
    one_role(project, session_id=session)
    write_transcript(
        pi_agent, session, model="deepseek-v4.1-flash", total=176283,
        presence=[presence_block(contextPct=23, contextTokens=230365,
                                 contextWindow=1000000),
                  presence_block(contextPct=47, contextTokens=473271,
                                 contextWindow=1000000)])

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "176,283 tokens" in out
    assert "model deepseek-v4.1-flash" in out
    assert "about 47% of a 1,000,000-token window" in out
    assert "18%" not in out                    # no se recalcula lo que Pi dijo
    assert "23%" not in out                    # la última presencia manda
    assert "no percentage" not in out

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["total_tokens"] == 176283
    assert usage["model"] == "deepseek-v4.1-flash"
    assert usage["percent"] == 47
    assert usage["context_window"] == 1000000


@pytest.mark.parametrize("shape", ["details", "from"])
def test_status_reads_the_presence_record_wherever_the_line_puts_it(
        project, pi_agent, capsys, shape):
    session = SESSION
    one_role(project, session_id=session)
    write_transcript(pi_agent, session,
                     presence=presence_block(contextPct=6, contextTokens=61390,
                                             contextWindow=1000000),
                     presence_shape=shape)

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["percent"] == 6
    assert usage["context_window"] == 1000000


def test_status_ignores_a_presence_block_of_another_session(
        project, pi_agent, capsys):
    """Un transcript guarda bloques de otras sesiones (los mete intercom): el
    ajeno no presta ni su porcentaje ni su ventana a este rol."""
    one_role(project, session_id=SESSION)
    write_transcript(
        pi_agent, SESSION, model="deepseek-v4.1-flash", total=473271,
        presence=presence_block(id=FOREIGN_ID, contextPct=6,
                                contextTokens=61390, contextWindow=200000))
    (pi_agent / "models-store.json").write_text(json.dumps({
        "opencode-go": {"models": [
            {"id": "deepseek-v4.1-flash", "contextWindow": 1000000}]}}))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "about 47% of a 1,000,000-token window" in out
    assert "6%" not in out                     # el porcentaje del bloque ajeno
    assert "200,000" not in out                 # ni la ventana del bloque ajeno

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["total_tokens"] == 473271
    assert usage["context_window"] == 1000000
    assert usage["percent"] == 47


def test_status_trusts_the_transcript_window_over_the_catalogue(
        project, pi_agent, capsys):
    """La ventana que Pi declara gana a la del catálogo, que puede ser vieja."""
    session = SESSION
    one_role(project, session_id=session)
    write_transcript(pi_agent, session, model="deepseek-v4.1-flash",
                     presence=presence_block(contextPct=6, contextTokens=61390,
                                             contextWindow=1000000))
    (pi_agent / "models-store.json").write_text(json.dumps({
        "opencode-go": {"models": [
            {"id": "deepseek-v4.1-flash", "contextWindow": 200000}]}}))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "about 6% of a 1,000,000-token window" in out
    assert "200,000" not in out


def test_status_falls_back_to_the_model_store_outside_the_providers_block(
        project, pi_agent, capsys):
    """models-store.json guarda cada proveedor en la raíz, no bajo `providers`."""
    session = "01a1f453-0174-7369-9a3a-666666666666"
    one_role(project, session_id=session)
    write_transcript(pi_agent, session, model="deepseek-v4.1-flash", total=473271)
    (pi_agent / "models-store.json").write_text(json.dumps({
        "groq": {"models": [{"id": "other-model", "contextWindow": 32000}]},
        "opencode-go": {"lastModified": "2026-11-20T00:00:00Z", "models": [
            {"id": "another-model", "contextWindow": 65536},
            {"id": "deepseek-v4.1-flash", "contextWindow": 1000000}]}}))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "about 47% of a 1,000,000-token window" in out
    assert "32,000" not in out

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["context_window"] == 1000000
    assert usage["percent"] == 47


def test_status_prefers_the_store_over_the_hand_written_model_file(
        project, pi_agent, capsys):
    """El catálogo que Pi resolvió va antes que un models.json escrito a mano."""
    session = "01a1f453-0174-7369-9a3a-777777777777"
    one_role(project, session_id=session)
    write_transcript(pi_agent, session)
    (pi_agent / "models-store.json").write_text(json.dumps({"local": {
        "models": [{"id": "test-model", "contextWindow": 400000}]}}))
    (pi_agent / "models.json").write_text(json.dumps({"providers": {"local": {
        "models": [{"id": "test-model", "contextWindow": 200000}]}}}))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "about 44% of a 400,000-token window" in out
    assert "200,000" not in out


@pytest.mark.parametrize("window", [0, -1, "1000000", True, 2.5])
def test_a_catalogue_window_that_is_not_a_positive_integer_is_ignored(
        project, pi_agent, capsys, window):
    """Una ventana mal escrita no es un número que imprimir: se degrada."""
    session = "01a1f453-0174-7369-9a3a-888888888888"
    one_role(project, session_id=session)
    write_transcript(pi_agent, session)
    (pi_agent / "models-store.json").write_text(json.dumps({"local": {
        "models": [{"id": "test-model", "contextWindow": window}]}}))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "no context window known: no percentage" in out

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["context_window"] is None
    assert usage["percent"] is None


def test_status_states_a_percentage_the_transcript_gives_without_a_window(
        project, pi_agent, capsys):
    """El porcentaje que Pi dijo se muestra aunque no diga el tamaño."""
    session = SESSION
    one_role(project, session_id=session)
    write_transcript(pi_agent, session,
                     presence=presence_block(contextPct=6, contextTokens=61390))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "about 6% of its context window" in out
    assert "the window size is unknown" in out
    assert "no percentage" not in out

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["percent"] == 6
    assert usage["context_window"] is None


def test_the_tokens_degrade_per_role_not_per_command(project, pi_agent, capsys):
    """Un rol sin transcripción no se lleva por delante los números de otro."""
    known = SESSION
    absent = "01a1f453-0174-7369-9a3a-bbbbbbbbbbbb"
    write_registry(project, tabs={
        "orchestrator": {"name": "Orquestador", "tab_id": "tb1",
                         "terminal_id": "t1", "pane_id": "p1", "app": "pi",
                         "pid": 500, "session_id": known},
        "worker_1": {"name": "Worker 1", "tab_id": "tb2",
                     "terminal_id": "t2", "pane_id": "p2", "app": "pi",
                     "pid": 501, "session_id": absent}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500),
                        live_tab("tb2", "Worker 1", "t2", pid=501)])
    write_transcript(pi_agent, known, model="deepseek-v4.1-flash", total=473271,
                     presence=presence_block(contextPct=47, contextTokens=473271,
                                             contextWindow=1000000))

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "about 47% of a 1,000,000-token window" in out
    assert f"no transcript for session {absent.split('-')[0][:8]}" in out

    assert project.module.status(as_json=True) == 0
    roles = status_roles(capsys)
    assert roles[0]["usage"]["percent"] == 47
    assert "no transcript" in roles[1]["usage"]["detail"]
    assert roles[1]["usage"]["percent"] is None


def test_status_says_which_source_is_missing_for_the_tokens(project, pi_agent, capsys):
    """Sin session id, sin transcripción y sin store: se dice, no se falla."""
    known = "11111111-2222-4333-8444-555555555555"
    write_registry(project, tabs={
        "orchestrator": {"name": "Orquestador", "tab_id": "tb1",
                         "terminal_id": "t1", "pane_id": "p1", "app": "pi",
                         "pid": 500, "session_id": known},
        "worker_1": {"name": "Worker 1", "tab_id": "tb2", "terminal_id": "t2",
                     "pane_id": "p2", "app": "pi", "pid": 501,
                     "session_id": None}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500),
                        live_tab("tb2", "Worker 1", "t2", pid=501)])

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "no transcript" in out
    assert "no session id" in out

    assert project.module.status(as_json=True) == 0
    roles = status_roles(capsys)
    assert roles[0]["usage"]["total_tokens"] is None
    assert "no transcript" in roles[0]["usage"]["detail"]
    assert "no session id" in roles[1]["usage"]["detail"]


def test_a_missing_session_store_does_not_fail_the_command(
        project, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "nowhere"))
    monkeypatch.delenv("PI_SESSION_FILE", raising=False)
    one_role(project, session_id="11111111-2222-4333-8444-666666666666")

    assert project.module.status(as_json=True) == 0
    usage = status_roles(capsys)[0]["usage"]
    assert usage["total_tokens"] is None
    assert "no transcript" in usage["detail"]


def test_an_unreadable_handoff_does_not_fail_the_command(project, capsys):
    one_role(project)
    directory = project.root / ".torcha" / "handoffs" / "orchestrator"
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text("{not json")

    assert project.module.status() == 0
    out = capsys.readouterr().out
    assert "could not be read" in out

    assert project.module.status(as_json=True) == 0
    handoff = status_roles(capsys)[0]["handoff"]
    assert handoff["present"] is True
    assert handoff["head"] is None


def test_status_keeps_its_contract_with_the_new_detail(project, capsys):
    """Los estados, la divergencia y el código de salida no cambian."""
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500}})
    seed_live(project, [live_tab("tb2", "Other", "t2", pid=500)])

    assert project.module.status(as_json=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"registry", "roles", "summary"}
    assert payload["summary"] == {"total": 1, "alive": 0, "diverged": True}
    assert payload["roles"][0]["state"] == "missing"
    assert {"role", "name", "state", "detail"} <= set(payload["roles"][0])

    assert project.module.status() == 1
    out = capsys.readouterr().out
    assert "  orchestrator  missing" in out
    assert "0 of 1 role(s) alive" in out


# --- the handoff document ---------------------------------------------------


def valid_handoff(**overrides):
    data = {
        "schema_version": 1,
        "handoff_id": "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
        "project": "proj",
        "agent_id": "orchestrator",
        "role": "Coordinates the team.",
        "created_at": "2026-11-23T15:00:00+01:00",
        "source_pi_session_id": "01a1f453-0174-7369",
        "status": "prepared",
        "objective": "Finish the handoff format.",
        "current_state": "Module written, tests pending.",
        "completed": ["wrote handoff.py"],
        "in_progress": ["tests"],
        "next_actions": ["run the suite"],
        "files_touched": [{"path": "src/torcha/handoff.py",
                           "reason": "new module"}],
        "decisions": ["the handoff is JSON, not YAML"],
        "blockers": [],
        "validation": {"commands_run": ["pytest"], "results": ["77 passed"]},
        "git": {"branch": "main", "head": "a" * 40, "status_summary": "clean"},
        "engram_refs": ["torcha/handoff/orchestrator"],
    }
    data.update(overrides)
    return data


def test_a_complete_handoff_is_valid(project):
    assert project.module.handoff.validate_handoff(valid_handoff()) == []


def test_a_missing_field_is_reported(project):
    data = valid_handoff()
    del data["objective"]
    problems = project.module.handoff.validate_handoff(data)
    assert any("objective" in problem for problem in problems)


def test_an_unknown_schema_version_is_rejected(project):
    problems = project.module.handoff.validate_handoff(valid_handoff(schema_version=2))
    assert any("schema_version" in problem for problem in problems)


def test_an_unknown_status_is_rejected(project):
    problems = project.module.handoff.validate_handoff(valid_handoff(status="done"))
    assert any("status" in problem for problem in problems)


def test_git_head_must_be_a_sha(project):
    data = valid_handoff(git={"branch": "main", "head": "not-a-sha",
                              "status_summary": "clean"})
    problems = project.module.handoff.validate_handoff(data)
    assert any("git.head" in problem for problem in problems)


def test_a_non_uuid_handoff_id_is_rejected(project):
    problems = project.module.handoff.validate_handoff(valid_handoff(handoff_id="x"))
    assert any("handoff_id" in problem for problem in problems)


def test_a_bad_created_at_is_rejected(project):
    problems = project.module.handoff.validate_handoff(
        valid_handoff(created_at="ayer"))
    assert any("created_at" in problem for problem in problems)


def test_files_touched_needs_a_reason(project):
    problems = project.module.handoff.validate_handoff(
        valid_handoff(files_touched=[{"path": "a.py"}]))
    assert any("reason" in problem for problem in problems)


def test_a_credential_is_refused(project):
    token = "ghp_" + "a" * 30
    problems = project.module.handoff.validate_handoff(
        valid_handoff(current_state=f"deployed with {token}"))
    assert any("credential" in problem for problem in problems)


def test_a_project_mismatch_is_reported(project):
    problems = project.module.handoff.validate_handoff(valid_handoff(),
                                                       project_name="other")
    assert any("project" in problem for problem in problems)


def test_the_project_field_is_only_checked_inside_the_project(project, tmp_path):
    inside = project.root / ".torcha" / "handoffs" / "orchestrator"
    inside.mkdir(parents=True)
    wrong = inside / "h.json"
    wrong.write_text(json.dumps(valid_handoff(project="other")))

    assert project.module.handoff_command.validate(str(wrong)) == 1

    outside = tmp_path / "h.json"
    outside.write_text(json.dumps(valid_handoff(project="other")))
    assert project.module.handoff_command.validate(str(outside)) == 0


def test_the_command_validates_a_file(project, tmp_path):
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(valid_handoff()))
    assert project.module.handoff_command.validate(str(path)) == 0

    path.write_text(json.dumps(valid_handoff(status="done")))
    assert project.module.handoff_command.validate(str(path)) == 1


def test_check_head_says_when_it_cannot_verify(project, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(project.module.handoff_command, "repo_head", lambda: None)
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(valid_handoff()))

    assert project.module.handoff_command.validate(str(path), check_head=True) == 0
    assert "could not read the current commit" in capsys.readouterr().err


def test_check_head_reports_a_moved_repository(project, tmp_path, monkeypatch):
    monkeypatch.setattr(project.module.handoff_command, "repo_head",
                        lambda: "b" * 40)
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(valid_handoff()))

    assert project.module.handoff_command.validate(str(path)) == 0
    assert project.module.handoff_command.validate(str(path), check_head=True) == 1


# --- not replacing the session that invokes you ------------------------------


def test_runs_inside_detects_the_invoking_session(project, monkeypatch):
    herdr = project.module.herdr
    monkeypatch.setattr(herdr, "terminal_pid", lambda terminal: 500)
    monkeypatch.setattr(herdr, "_parent_pid",
                        lambda pid: 500 if pid == os.getpid() else 0)
    assert herdr.runs_inside("t1") is True


def test_runs_inside_is_false_for_a_foreign_session(project, monkeypatch):
    herdr = project.module.herdr
    monkeypatch.setattr(herdr, "terminal_pid", lambda terminal: 500)
    monkeypatch.setattr(herdr, "_parent_pid", lambda pid: 1)
    assert herdr.runs_inside("t1") is False


def test_runs_inside_is_false_without_a_foreground_pid(project, monkeypatch):
    herdr = project.module.herdr
    monkeypatch.setattr(herdr, "terminal_pid", lambda terminal: None)
    assert herdr.runs_inside("t1") is False


# --- start: resume, do not rebuild -----------------------------------------

SESSION = "11111111-1111-4111-8111-111111111111"


def start_registry(project, session_id=SESSION, **extra):
    entry = {"name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
             "pane_id": "p1", "app": None, "pid": None, "session_id": session_id}
    entry.update(extra)
    write_registry(project, tabs={"orchestrator": entry})


def seed_bootstrap_file(project, key="orchestrator", mode=None):
    """The prompt `pi` reads, rendered exactly as `init` writes it.

    `start` refuses to launch on a file that does not hold the configured
    mode's text, so every test that expects a launch has to have this file.
    """
    config = json.loads((project.root / ".torcha/agents.json").read_text())
    mode = mode or config["pi"]["bootstrap"]
    item = next(tab for tab in config["tabs"] if tab["key"] == key)
    path = project.module.paths.BOOTSTRAP_DIR / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(project.module.bootstrap_text(item, mode))
    return path


def created_tab(project, name):
    """La tab que el fake acaba de crear, tal como la reporta `ls`."""
    for space in project.read_state()["spaces"]:
        for tab in space["tabs"]:
            if tab["name"] == name:
                return tab
    return None


def test_start_resumes_the_registry_session(project):
    start_registry(project)
    seed_bootstrap_file(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(timeout=0.5, interval=0.01) == 0

    assert "hc_sent" not in project.read_state()          # no se teclea nada
    assert [opts["id"] for opts in project.options_for("tab.close")] == ["tb1"]
    created = project.options_for("tab.new")
    assert created and created[0]["name"] == "Orquestador"
    assert created[0]["space"] == "sp01"
    assert created[0]["folder"] == str(project.root)
    assert created[0]["focus"] == "false"
    assert "--skill" in created[0]["argv"]      # la skill del equipo, siempre
    assert "--session-id" in created[0]["argv"]
    assert SESSION in created[0]["argv"]
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["session_id"] == SESSION
    assert entry["pid"] == created_tab(project, "Orquestador")["terminals"][0]["pid"]


def test_start_fresh_uses_a_new_session_id(project):
    start_registry(project)
    seed_bootstrap_file(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(fresh=True, timeout=0.5, interval=0.01) == 0

    new_id = project.registry()["herdr"]["tabs"]["orchestrator"]["session_id"]
    assert new_id != SESSION
    uuid.UUID(new_id)


def test_start_skips_a_tab_that_already_runs_the_agent(project):
    start_registry(project)
    seed_bootstrap_file(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app="pi", pid=500)])

    assert project.module.start(timeout=0.5, interval=0.01) == 0
    assert "hc_sent" not in project.read_state()


def test_start_refuses_to_type_into_something_that_is_not_a_shell(project):
    start_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None,
                                 pid=77) | {}])
    state = project.read_state()
    state["spaces"][0]["tabs"][0]["terminals"][0]["fg_argv"] = ["vim"]
    project.state.write_text(json.dumps(state))

    assert project.module.start(timeout=0.5, interval=0.01) == 1
    assert "hc_sent" not in project.read_state()
    assert project.options_for("tab.close") == []      # no se cierra a ciegas


def a_space_without_the_role(project):
    """The space still matches by cwd, but the orchestrator's tab is gone."""
    return {"id": "sp01", "name": "proj", "folder": "/wrong", "active": True,
            "tabs": [{"id": "tb-other", "name": "Revisor", "active": True,
                      "terminals": [{"terminal": "t09", "pane": "p09",
                                     "cwd": str(project.root), "app": "pi",
                                     "status": "idle", "pid": 111}]}]}


def test_start_reports_a_closed_tab_and_offers_recreate(project, capsys):
    start_registry(project)
    project.state.write_text(json.dumps(
        {"spaces": [a_space_without_the_role(project)], "calls": []}))

    assert project.module.start(timeout=0.2, interval=0.01) == 1
    assert "--recreate" in capsys.readouterr().err


def test_start_recreate_resumes_the_old_session(project, capsys):
    """Un cierre por error debe devolver la conversación, no empezar otra."""
    start_registry(project)
    seed_bootstrap_file(project)
    project.state.write_text(json.dumps(
        {"spaces": [a_space_without_the_role(project)], "calls": []}))

    assert project.module.start(timeout=0.2, interval=0.01, recreate=True) == 0

    created = project.options_for("tab.new")
    assert created and created[0]["name"] == "Orquestador"
    assert SESSION in created[0]["argv"]
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["session_id"] == SESSION
    assert entry["terminal_id"] != "t1"          # el terminal es nuevo
    new_pid = created_tab(project, "Orquestador")["terminals"][0]["pid"]
    assert entry["pid"] == new_pid               # el pid de la tab creada
    assert entry["pid"] != 9000                  # ni el del arranque tecleado
    assert "resumed" in capsys.readouterr().out


def test_start_recreate_fresh_starts_a_new_session(project):
    start_registry(project)
    seed_bootstrap_file(project)
    project.state.write_text(json.dumps(
        {"spaces": [a_space_without_the_role(project)], "calls": []}))

    assert project.module.start(timeout=0.2, interval=0.01, recreate=True,
                                fresh=True) == 0
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["session_id"] != SESSION


def test_start_recreate_fresh_reports_a_new_session(project, capsys):
    start_registry(project)
    seed_bootstrap_file(project)
    project.state.write_text(json.dumps(
        {"spaces": [a_space_without_the_role(project)], "calls": []}))

    assert project.module.start(timeout=0.2, interval=0.01, recreate=True,
                                fresh=True) == 0
    out = capsys.readouterr().out
    assert "new session" in out
    assert "resumed" not in out


def test_start_recreate_takes_the_ids_from_ls_not_from_the_echo(project):
    """El id que devuelve `tab.new` no es la verdad; manda `herdr-app ls`."""
    start_registry(project)
    seed_bootstrap_file(project)
    project.state.write_text(json.dumps(
        {"spaces": [a_space_without_the_role(project)], "calls": [],
         "tab_new_echo": {"tab": "tb-other", "terminal": "t09"}}))

    assert project.module.start(timeout=0.2, interval=0.01, recreate=True) == 0

    fresh_tab = created_tab(project, "Orquestador")
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["tab_id"] == fresh_tab["id"]
    assert entry["terminal_id"] == fresh_tab["terminals"][0]["terminal"]
    assert entry["tab_id"] != "tb-other"
    assert entry["terminal_id"] != "t09"


def test_start_skips_a_role_with_the_bootstrap_disabled(project):
    (project.root / ".torcha" / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi", "bootstrap": "none"},
                    "tabs": TABS}))
    start_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(timeout=0.5, interval=0.01) == 0

    assert "hc_sent" not in project.read_state()
    assert project.options_for("tab.close") == []
    assert project.options_for("tab.new") == []


def test_start_refuses_a_stale_bootstrap_file_and_launches_nothing(project, capsys):
    """S16: the file wins. Editing agents.json does not rewrite the prompt."""
    start_registry(project)
    # El prompt en disco se escribió para `recover`, pero la config dice `greet`.
    path = seed_bootstrap_file(project, mode="recover")
    before = path.read_text()
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(timeout=0.5, interval=0.01) == 1

    error = capsys.readouterr().err
    assert ".torcha/bootstrap/orchestrator.md" in error   # nombra el fichero
    assert "recover" in error                                 # el modo que tiene
    assert "greet" in error                                   # el que se configuró
    assert "torcha init" in error                          # cómo reconciliarlo
    assert project.options_for("tab.close") == []             # no se cierra nada
    assert project.options_for("tab.new") == []               # ni se lanza nada
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["tab_id"] == "tb1" and entry["terminal_id"] == "t1"
    assert entry["session_id"] == SESSION
    assert path.read_text() == before                         # no se sobrescribe


def test_start_recreate_refuses_a_missing_bootstrap_file(project, capsys):
    """S16: a role with no prompt on disk cannot be launched either."""
    start_registry(project)
    project.state.write_text(json.dumps(
        {"spaces": [a_space_without_the_role(project)], "calls": []}))

    assert project.module.start(timeout=0.2, interval=0.01, recreate=True) == 1

    error = capsys.readouterr().err
    assert ".torcha/bootstrap/orchestrator.md" in error
    assert "torcha init" in error
    assert project.options_for("tab.new") == []
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["tab_id"] == "tb1" and entry["terminal_id"] == "t1"


def test_start_refuses_a_role_that_is_no_longer_declared(project, capsys):
    """S16: outside `agents.json` there is no rendered prompt to verify."""
    write_registry(project, tabs={"ghost": {
        "name": "Ghost", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": None, "pid": None, "session_id": SESSION}})
    seed_bootstrap_file(project, "orchestrator")
    seed_live(project, [live_tab("tb1", "Ghost", "t1", app=None)])

    assert project.module.start(timeout=0.5, interval=0.01) == 1

    error = capsys.readouterr().err
    assert "no longer in agents.json" in error
    assert "torcha init" in error
    assert project.options_for("tab.close") == []
    assert project.options_for("tab.new") == []


def test_start_does_not_compare_bootstrap_files_when_the_mode_is_none(project, capsys):
    """S16: with `none` pi is never launched, so no file is read."""
    (project.root / ".torcha" / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi", "bootstrap": "none"},
                    "tabs": TABS}))
    start_registry(project)
    # Un fichero que quedó de un modo anterior no puede impedir nada: no se lee.
    seed_bootstrap_file(project, "orchestrator", mode="recover")
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(timeout=0.5, interval=0.01) == 0

    error = capsys.readouterr().err
    assert "bootstrap is disabled in agents.json" in error
    assert "does not exist" not in error
    assert project.options_for("tab.close") == []
    assert project.options_for("tab.new") == []


def test_start_only_touches_the_named_role(project):
    seed_bootstrap_file(project, "worker_1")
    write_registry(project, tabs={
        "orchestrator": {"name": "Orquestador", "tab_id": "tb1",
                         "terminal_id": "t1", "pane_id": "p1", "app": None,
                         "pid": None, "session_id": SESSION},
        "worker_1": {"name": "Worker 1", "tab_id": "tb2", "terminal_id": "t2",
                     "pane_id": "p2", "app": None, "pid": None,
                     "session_id": SESSION},
    })
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None),
                        live_tab("tb2", "Worker 1", "t2", app=None)])

    assert project.module.start(role="worker_1", timeout=0.5, interval=0.01) == 0

    assert "hc_sent" not in project.read_state()
    assert [opts["id"] for opts in project.options_for("tab.close")] == ["tb2"]
    assert [opts["name"] for opts in project.options_for("tab.new")] == ["Worker 1"]


# --- rename ----------------------------------------------------------------


def test_rename_uses_the_registry_tab_id(project):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500, "session_id": None}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])

    assert project.module.rename("orchestrator", "Orchestrator") == 0

    assert project.registry()["herdr"]["tabs"]["orchestrator"]["name"] == "Orchestrator"
    assert project.read_state()["spaces"][0]["tabs"][0]["name"] == "Orchestrator"


def test_rename_refuses_an_unknown_role(project):
    write_registry(project, tabs={})
    seed_live(project, [])
    assert project.module.rename("nobody", "Whatever") == 1


def test_rename_refuses_a_tab_that_no_longer_exists(project):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb-gone", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500, "session_id": None}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])

    assert project.module.rename("orchestrator", "Orchestrator") == 1


# --- guided init: the interview runs as a child -----------------------------


def test_the_interview_prompt_carries_the_skeleton_keys(project):
    skeleton = [{"key": "orchestrator", "name": "Orquestador"},
                {"key": "revisor", "name": "Revisor"}]
    payload = {"space": "proj", "tabs": [
        {"tab_id": "tb1", "terminal_id": "t1", "name": "Revisor",
         "app": "pi", "status": "done"},
        {"tab_id": "tb2", "terminal_id": "t2", "name": "Orquestador",
         "app": "pi", "status": "idle"},
    ]}
    text = project.module.init_module._interview_prompt(skeleton, payload)
    assert "`orchestrator`" in text and "`revisor`" in text
    assert "`tb2`" in text and "`t2`" in text
    assert "Do not touch keys, names or order" in text
    # El procedimiento ya no vive aquí: vive en la skill.
    assert "intercom list-cwd" not in text


def test_the_interview_prompt_covers_only_the_pending_roles(project, monkeypatch):
    """career-ops: one empty role among five written ones must be the whole list."""
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Coordinates the team.", "instructions": "- a"},
                 {"key": "coach", "name": "Coach",
                  "role": "", "instructions": ""}]}))
    folder = str(project.root)
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": folder, "active": True,
        "tabs": [role_tab(1, "Orquestador", folder),
                 role_tab(2, "Coach", folder)]}], "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    text = (project.root / ".torcha/interview.md").read_text()
    # El sujeto de la entrevista es la única role pendiente, y se dice cuál es.
    assert "The interview covers only these roles, which are still empty: `coach`." \
        in text
    assert "already written by their agents" in text
    assert "touch or rewrite them" in text
    # Y no se afirma que todas estén vacías, porque no lo están.
    assert "Every `role` and `instructions` is empty" not in text


def test_a_role_is_pending_while_either_field_is_empty(project):
    """S13: `initial_tabs` and `discover` leave `role` set and `instructions` empty."""
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Not declared in the repository; describe it.",
                  "instructions": ""},
                 {"key": "coach", "name": "Coach",
                  "role": "Coaches the team.", "instructions": "- a"},
                 {"key": "auditor", "name": "Auditor",
                  "role": "Audits the work."}]}))

    pending = project.module.init_module.unfilled_roles()

    # El texto del placeholder no decide nada: decide que falte un campo.
    assert pending == ["orchestrator", "auditor"]
    # Y `init` la trata como pendiente: no aplica una configuración a medias.
    assert project.module.init(plain=True) == 1


def test_the_interview_names_the_field_a_pending_role_still_needs(project):
    """A role with `role` written is asked for its instructions, not for itself."""
    skeleton = [
        {"key": "orchestrator", "name": "Orquestador",
         "role": "Coordinates the team.", "instructions": "- a"},
        {"key": "coach", "name": "Coach",
         "role": "Coaches the team.", "instructions": ""},
    ]
    payload = {"space": "proj", "tabs": []}

    text = project.module.init_module._interview_prompt(skeleton, payload)

    assert "The interview covers only these roles, which are still empty: `coach`." \
        in text
    # Se dice qué campo falta, y no se pide describir desde cero una role escrita.
    assert "- `coach`: `instructions` is empty; `role` is filled and must not " \
        "be rewritten." in text
    assert "`coach`: `role` and `instructions` are both empty" not in text
    # La role pendiente no se anuncia como escrita; la escrita sigue protegida.
    assert "Every `role` and `instructions` is empty" not in text
    assert "already written by their agents" in text


def test_a_written_team_needs_no_interview_and_a_seed_keeps_its_wording(
        project, monkeypatch):
    """S13 leaves both ends alone: nothing pending, and a first-time seed."""
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Coordinates the team.", "instructions": "- a"},
                 {"key": "coach", "name": "Coach",
                  "role": "Coaches the team.", "instructions": "- b"}]}))
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)
    called = {}
    monkeypatch.setattr(project.module.init_module, "start_interview",
                        lambda candidates, seen=None, say=None:
                        called.setdefault("ran", True))

    assert project.module.init_module.unfilled_roles() == []
    assert project.module.init() == 0
    assert "ran" not in called

    seed = [{"key": "orchestrator", "name": "Orquestador",
             "role": "", "instructions": ""},
            {"key": "revisor", "name": "Revisor",
             "role": "", "instructions": ""}]
    text = project.module.init_module._interview_prompt(
        seed, {"space": "proj", "tabs": []})

    assert "Every `role` and `instructions` is empty. Fill them from what each " \
        "agent" in text
    assert "What is still empty, per role:" not in text


def test_a_first_time_seed_keeps_the_original_interview_wording(project):
    skeleton = [{"key": "orchestrator", "name": "Orquestador", "role": ""},
                {"key": "revisor", "name": "Revisor", "role": ""}]
    payload = {"space": "proj", "tabs": []}

    text = project.module.init_module._interview_prompt(skeleton, payload)

    assert "Every `role` and `instructions` is empty. Fill them from what each \
agent" in text
    assert "already written by their agents" not in text


def test_the_setup_skill_asks_only_the_pending_roles(project):
    text = " ".join(
        project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8").split())

    assert "Ask only the roles the prompt marks as pending" in text
    assert "never ask it again and never rewrite it" in text
    # "Ask every agent in the list" solo es cierto para un primer sembrado.
    assert "Ask every agent in the list" not in text


def test_the_setup_skill_fills_only_the_empty_field(project):
    text = " ".join(
        project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8").split())

    # La skill dice lo mismo por campo: qué falta, y qué no se toca.
    assert "it says which of the two fields is empty" in text
    assert "ask that agent only what it must not touch" in text
    assert "leave its `role` as it is" in text
    assert "Never ask an agent to describe a responsibility that is already " \
        "written" in text


def test_the_setup_skill_carries_the_rules(project):
    text = project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8")
    assert "intercom list-cwd" in text
    assert "intercom ask" in text
    assert "[a-z][a-z0-9_]*" in text
    assert "Never invent a scope" in text
    assert "first entry is `key: \"orchestrator\"`" in text


def test_run_interview_loads_the_packaged_skill(project, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command

        class Result:
            returncode = 0
        return Result()

    monkeypatch.setattr(project.module.init_module.subprocess, "run", fake_run)
    project.module.init_module._run_interview(Path("/tmp/x.md"), "pi")

    assert "--skill" in captured["command"]
    assert any(str(part).endswith("setup/SKILL.md")
               for part in captured["command"])


def test_start_interview_writes_the_skeleton_before_launching(project, monkeypatch):
    (project.root / ".torcha/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))
    # `start_interview` comprueba que el ejecutable existe: sin este stub el
    # test depende de que `pi` esté instalado en la máquina que lo ejecuta.
    monkeypatch.setattr(shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    report = project.module.init_module.start_interview([])

    # La entrevista sí tomó esta tab, pero no rellenó ninguna role.
    assert report.ran is True
    assert report.pending == ("orchestrator",)
    config = json.loads((project.root / ".torcha/agents.json").read_text())
    assert config["tabs"][0]["key"] == "orchestrator"
    assert config["tabs"][0]["name"] == "Orquestador"
    assert config["tabs"][0]["role"] == ""


def test_an_unfinished_interview_blocks_init(project):
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "", "instructions": ""}]}))

    assert project.module.init(plain=True) == 1


def test_init_opens_the_interview_when_live_tabs_exist(project, monkeypatch):
    (project.root / ".torcha/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    called = {}

    def fake_interview(candidates, seen=None, say=None):
        called["ran"] = True
        (project.root / ".torcha/agents.json").write_text(json.dumps({
            "pi": {"executable": "pi", "bootstrap": "greet"},
            "tabs": [{"key": "orchestrator", "name": "Orquestador",
                      "role": "Coordinates from the interview."}]}))
        return project.module.init_module.Interview(ran=True)

    monkeypatch.setattr(project.module.init_module, "start_interview", fake_interview)

    assert project.module.init() == 0
    assert called.get("ran") is True
    config = json.loads((project.root / ".torcha/agents.json").read_text())
    assert config["tabs"][0]["role"] == "Coordinates from the interview."


def test_init_skips_the_interview_with_plain(project, monkeypatch):
    (project.root / ".torcha/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    called = {}
    monkeypatch.setattr(project.module.init_module, "start_interview",
                        lambda candidates, seen=None, say=None:
                        called.setdefault("ran", True))

    assert project.module.init(plain=True) == 0
    assert "ran" not in called
    assert (project.root / ".torcha/agents.json").exists()


def test_init_skips_the_interview_without_a_tty(project, monkeypatch):
    (project.root / ".torcha/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: False)
    called = {}
    monkeypatch.setattr(project.module.init_module, "start_interview",
                        lambda candidates, seen=None, say=None:
                        called.setdefault("ran", True))

    assert project.module.init() == 0
    assert "ran" not in called


def test_a_failed_interview_refuses_to_apply(project, monkeypatch):
    (project.root / ".torcha/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    def fake_interview(candidates, seen=None, say=None):
        (project.root / ".torcha/agents.json").write_text(json.dumps({
            "pi": {"executable": "pi", "bootstrap": "greet"},
            "tabs": [{"key": "orchestrator", "name": "Orquestador",
                      "role": "", "instructions": ""}]}))
        return project.module.init_module.Interview(
            ran=True, pending=("orchestrator",))

    monkeypatch.setattr(project.module.init_module, "start_interview", fake_interview)

    assert project.module.init() == 1
    assert project.registry if False else True


# --- templates --------------------------------------------------------------


def test_the_software_team_template_is_available(project):
    found = {item["name"]: item for item in project.module.templates.available()}
    assert "software-team" in found
    assert found["software-team"]["tabs"] == 4


def test_the_template_keeps_the_loader_invariants(project):
    data = project.module.templates.load("software-team")
    keys = [tab["key"] for tab in data["tabs"]]
    assert keys[0] == "orchestrator"
    assert len(set(keys)) == len(keys)
    for tab in data["tabs"]:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", tab["key"])
        assert tab["name"].strip()
        assert tab["role"].strip()
        assert tab.get("instructions")


def test_an_unknown_template_is_reported(project):
    with pytest.raises(project.module.TorchaError, match="There is no template"):
        project.module.templates.load("nope")


def test_the_templates_command_lists_it(project, capsys):
    assert project.module.templates_command(as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["templates"][0]["name"] == "software-team"


# --- instructions and launch safety ----------------------------------------


def test_instructions_accepts_a_list_of_bullets(project):
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Coordinates.", "instructions": ["- one", "- two"]}]}))

    config = project.module.load_config()
    assert config["tabs"][0]["instructions"] == "- one\n- two"


def test_instructions_rejects_a_shape_it_cannot_use(project):
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Coordinates.", "instructions": 42}]}))

    with pytest.raises(project.module.TorchaError, match="instructions"):
        project.module.load_config()


def test_the_skill_asks_one_question_at_a_time(project):
    text = project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8")
    assert "One question at a time" in text
    assert "Already waiting for a reply" in text


def test_init_warns_when_launched_inside_a_team_tab(project, monkeypatch, capsys):
    (project.root / ".torcha/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_own_tab",
                        lambda: {"id": "tb-sp01", "name": "Orquestador"})
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    assert "with the same label" in capsys.readouterr().err


def test_a_loose_tab_in_the_space_is_not_a_team_tab(project, monkeypatch, capsys):
    """La tab desde la que se lanza init no es un rol: no avisa y se renombra."""
    (project.root / ".torcha/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_own_tab",
                        lambda: {"id": "tb-loose", "name": "6"})
    # `start_interview` comprueba que el ejecutable existe: sin este stub el
    # test depende de que `pi` esté instalado en la máquina que lo ejecuta.
    monkeypatch.setattr(shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    assert "with the same label" not in capsys.readouterr().err
    renames = project.options_for("tab.rename")
    assert renames and renames[0]["id"] == "tb-loose"
    assert renames[0]["name"] == "Torcha"


# --- session ids collected by the interview ---------------------------------


def test_the_interview_session_ids_reach_an_adopted_tab(project):
    """A tab init creates gets its own id; one it adopts gets the interviewed one."""
    sid = "11111111-1111-4111-8111-111111111111"
    proposals = project.root / ".torcha" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "sessions.json").write_text(json.dumps({"orchestrator": sid}))
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))

    assert project.module.init(plain=True) == 0

    tabs = project.registry()["herdr"]["tabs"]
    assert tabs["orchestrator"]["session_id"] == sid        # adoptada
    assert tabs["worker_1"]["session_id"] != sid            # creada por init


def test_a_created_tab_keeps_its_own_session_id(project):
    sid = "22222222-2222-4222-8222-222222222222"
    proposals = project.root / ".torcha" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "sessions.json").write_text(json.dumps({"worker_1": sid}))
    project.state.write_text(json.dumps({"spaces": [], "calls": []}))

    assert project.module.init(plain=True) == 0
    assert project.registry()["herdr"]["tabs"]["worker_1"]["session_id"] != sid


def test_ids_written_during_the_interview_are_read_afterwards(project, monkeypatch):
    """The proposals file does not exist until the interview writes it."""
    sid = "33333333-3333-4333-8333-333333333333"
    (project.root / ".torcha/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    def fake_interview(candidates, seen=None, say=None):
        (project.root / ".torcha/agents.json").write_text(json.dumps({
            "pi": {"executable": "pi", "bootstrap": "greet"},
            "tabs": [{"key": "orchestrator", "name": "Orquestador",
                      "role": "Coordinates.", "instructions": ""}]}))
        proposals = project.root / ".torcha" / "proposals"
        proposals.mkdir(parents=True, exist_ok=True)
        (proposals / "sessions.json").write_text(json.dumps({"orchestrator": sid}))
        return project.module.init_module.Interview(ran=True)

    monkeypatch.setattr(project.module.init_module, "start_interview", fake_interview)
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))

    assert project.module.init() == 0
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["session_id"] == sid


def test_an_invalid_session_id_is_ignored_not_used(project):
    proposals = project.root / ".torcha" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "sessions.json").write_text(json.dumps({"orchestrator": "no-soy-un-uuid"}))
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))

    assert project.module.init(plain=True) == 0
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["session_id"] is None


def test_the_skill_asks_for_the_session_id(project):
    text = project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8")
    assert "PI_SESSION_ID" in text
    assert "proposals/sessions.json" in text
    assert "an invented id would make `torcha start` resume" in text


# --- handoff run ------------------------------------------------------------


def handoff_registry(project, session_id="11111111-1111-4111-8111-111111111111"):
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500, "session_id": session_id}})


def fill_on_send(project, monkeypatch, fill=True):
    """Simulate the agent: it fills the handoff file, but it does not launch Pi.

    The handoff order is the only text the command injects: the swap replaces the
    tab with `--argv` and types nothing, so any other send goes to the real
    send_text.
    """
    original = project.module.handoff_command.send_text

    def fake_send(terminal, text):
        match = re.search(r"(/\S+\.json)", text)
        if not match:
            return original(terminal, text)
        if fill:
            path = Path(match.group(1))
            data = json.loads(path.read_text())
            data["objective"] = "Relevar el trabajo en curso."
            data["current_state"] = "Medido y comprobado."
            path.write_text(json.dumps(data))
        return True

    monkeypatch.setattr(project.module.handoff_command, "send_text", fake_send)


def test_the_relevo_message_states_the_shape_of_structured_fields(project):
    """El agente no puede adivinar files_touched ni engram_refs: van vacíos."""
    text = project.module.handoff_command.RELEVO
    assert '"path"' in text and '"reason"' in text
    assert "engram_refs" in text and "STRINGS" in text
    assert "files_touched" in text and "OBJECTS" in text


def test_the_relevo_message_pins_the_git_block(project):
    """`git` lo mide torcha: reescribirlo fue cómo un handoff declaró un sha falso."""
    text = project.module.handoff_command.RELEVO
    assert "`git` is measured by torcha and must not be edited" in text


def test_handoff_run_writes_and_validates_a_handoff(project, monkeypatch):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 0

    files = list((project.root / ".torcha" / "handoffs" / "orchestrator").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["agent_id"] == "orchestrator"
    assert data["objective"] == "Relevar el trabajo en curso."
    assert len(data["git"]["head"]) == 40


HEAD = "a" * 40
MOVED = "b" * 40


def pinned_repository(project, monkeypatch, head=HEAD):
    """Fija lo que el repositorio mide, sin tocar git desde el test."""
    monkeypatch.setattr(project.module.handoff_command, "repo_state",
                        lambda: {"branch": "main", "head": HEAD,
                                 "status_summary": "clean tree"})
    monkeypatch.setattr(project.module.handoff_command, "repo_head", lambda: head)


def test_a_handoff_whose_head_moved_is_refused(project, monkeypatch, capsys):
    """El sha aceptado tiene que ser el del repositorio al validar, o el relevo nace rancia."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)
    pinned_repository(project, monkeypatch, head=MOVED)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01, swap=True) == 1

    err = capsys.readouterr().err
    assert f"the handoff declares {HEAD} and the repository is at {MOVED}" in err
    assert "tab.close" not in project.commands()          # no se releva nada
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["pid"] == 500
    files = list((project.root / ".torcha" / "handoffs" / "orchestrator").glob("*.json"))
    data = json.loads(files[0].read_text())
    assert data["status"] == "prepared"                    # el handoff no se consume
    assert data["git"]["head"] == HEAD


def test_a_handoff_with_the_head_the_repository_reports_is_accepted(project, monkeypatch):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)
    pinned_repository(project, monkeypatch)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01, swap=True) == 0
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["pid"] == 1002


def test_an_unconfirmed_head_is_reported_not_invented(project, monkeypatch, capsys):
    """Sin commit legible no se puede afirmar un desajuste: se dice y se acepta."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)
    pinned_repository(project, monkeypatch, head=None)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 0

    err = capsys.readouterr().err
    assert "could not read the current commit" in err
    assert "declares" not in err


def test_handoff_run_fails_when_the_agent_writes_nothing(project, monkeypatch):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch, fill=False)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 1


def test_handoff_run_refuses_its_own_terminal(project, monkeypatch):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)
    monkeypatch.setattr(project.module.handoff_command, "runs_inside",
                        lambda terminal: True)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 1


def test_handoff_run_swaps_only_when_asked(project, monkeypatch):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 0
    assert project.commands().count("space.new") == 0
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["pid"] == 500

    # --swap vuelve a pedir aunque ya hubiera un handoff válido.
    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01, swap=True) == 0
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["pid"] == 1002     # el pid de la tab que crea el fake, no el viejo
    assert entry["session_id"] != "11111111-1111-4111-8111-111111111111"
    # y el handoff consumido queda marcado: no se reutiliza en el próximo run.
    # Se busca el que quedó consumido en vez de leer el primero del glob: con dos
    # documentos el orden del sistema de ficheros no significa nada.
    files = list((project.root / ".torcha" / "handoffs" / "orchestrator").glob("*.json"))
    statuses = [json.loads(path.read_text())["status"] for path in files]
    assert statuses.count("consumed") == 1
    # El relevo no teclea nada en un shell: cierra la tab y abre otra con --argv.
    assert [opts["id"] for opts in project.options_for("tab.close")] == ["tb1"]
    created = project.options_for("tab.new")
    assert len(created) == 1
    assert created[0]["name"] == "Orquestador"
    assert entry["tab_id"] != "tb1"
    new_argv = json.loads(created[0]["argv"])
    assert new_argv[0] == "pi" and "--session-id" in new_argv
    assert entry["session_id"] in new_argv


def test_a_swap_launches_the_successor_in_recover_mode(project, monkeypatch):
    """El relevo tiene que heredar el handoff: con `greet` la sesión nueva no lo lee."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)
    configured = json.loads((project.root / ".torcha/agents.json").read_text())
    assert configured["pi"]["bootstrap"] == "greet"

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01, swap=True) == 0

    text = project.bootstrap("orchestrator")
    assert "Recovery protocol" in text
    assert "handoffs/orchestrator" in text
    new_argv = json.loads(project.options_for("tab.new")[0]["argv"])
    assert "@.torcha/bootstrap/orchestrator.md" in new_argv


def test_swap_never_closes_a_working_agent(project, monkeypatch, capsys):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    state = project.read_state()
    state["spaces"][0]["tabs"][0]["terminals"][0]["status"] = "working"
    project.state.write_text(json.dumps(state))
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01, swap=True) == 1
    assert "the agent is still working" in capsys.readouterr().err
    assert "hc_keys" not in project.read_state()


def test_a_role_with_a_valid_handoff_is_skipped(project, monkeypatch, capsys):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 0
    capsys.readouterr()

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 0
    assert "skipped" in capsys.readouterr().out


def test_a_busy_agent_is_reported_as_busy_not_as_wrong(project, monkeypatch, capsys):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    state = project.read_state()
    state["spaces"][0]["tabs"][0]["terminals"][0]["status"] = "working"
    project.state.write_text(json.dumps(state))
    fill_on_send(project, monkeypatch, fill=False)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 1
    err = capsys.readouterr().err
    assert "is working" in err
    assert "did not get to write it" in err
    assert "objective" not in err          # no se le acusa de escribirlo mal


def test_handoff_run_needs_a_target(project):
    handoff_registry(project)
    assert project.module.handoff_command.run() == 1


def test_handoff_run_all_stops_at_the_first_failure(project, monkeypatch, capsys):
    write_registry(project, tabs={
        "orchestrator": {"name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
                         "pane_id": "p1", "app": "pi", "pid": 500, "session_id": None},
        "worker_1": {"name": "Worker 1", "tab_id": "tb2", "terminal_id": "t2",
                     "pane_id": "p2", "app": None, "pid": None, "session_id": None},
    })
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500),
                        live_tab("tb2", "Worker 1", "t2", app=None)])
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(all_roles=True, timeout=0.2,
                                              interval=0.01) == 1
    err = capsys.readouterr().err
    assert "Stopping here" in err


# --- handoff run --use-existing --swap ---------------------------------------


def reusable_handoff(project, role="orchestrator", head=HEAD, *, minutes=120,
                     status="prepared", agent_id=None, project_name=None,
                     handoff_id=None, mtime=None):
    """Un handoff que ya valida sobre el disco: lo que `--use-existing` reutiliza."""
    directory = project.root / ".torcha" / "handoffs" / role
    directory.mkdir(parents=True, exist_ok=True)
    data = valid_handoff(
        handoff_id=handoff_id or str(uuid.uuid4()),
        project=project_name or project.root.name,
        agent_id=agent_id or role,
        status=status,
        created_at=iso_ago(minutes=minutes),
        git={"branch": "main", "head": head, "status_summary": "clean tree"})
    path = directory / f"{data['handoff_id']}.json"
    path.write_text(json.dumps(data))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def record_sends(project, monkeypatch):
    """El agente no escribe nada: solo se anota todo lo que se le manda."""
    sent = []
    monkeypatch.setattr(project.module.handoff_command, "send_text",
                        lambda terminal, text: sent.append(text) or True)
    return sent


def test_use_existing_swaps_with_the_document_on_disk_without_asking(
        project, monkeypatch, capsys):
    """Reutilizar ahorra el turno: ni RELEVO ni documento reescrito."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    pinned_repository(project, monkeypatch)
    document = reusable_handoff(project, minutes=120)
    before = document.read_text()
    sent = record_sends(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", use_existing=True, timeout=0.2, interval=0.01,
        swap=True) == 0

    out = capsys.readouterr().out
    assert sent == []                                   # no se pide otro handoff
    assert "reusing the handoff written 2h ago" in out  # y se dice su edad
    # El contenido no se reescribe: el agente no vuelve a escribirlo. Pero el
    # documento queda gastado, o un segundo --use-existing relevaría con él otra
    # vez. Se comprueba el cuerpo intacto y solo el estado cambiado.
    after = json.loads(document.read_text())
    written = json.loads(before)
    assert after["status"] == "consumed"
    written["status"] = "consumed"
    assert after == written                            # nada más cambió
    assert len(list(document.parent.glob("*.json"))) == 1
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["pid"] == 1002
    assert entry["session_id"] != "11111111-1111-4111-8111-111111111111"
    assert [opts["id"] for opts in project.options_for("tab.close")] == ["tb1"]
    new_argv = json.loads(project.options_for("tab.new")[0]["argv"])
    assert "@.torcha/bootstrap/orchestrator.md" in new_argv
    # La sesión nueva lee el documento que se le dio, no otro.
    text = project.bootstrap("orchestrator")
    assert "Recovery protocol" in text
    assert ".torcha/handoffs/orchestrator/" in text


def test_reuse_still_refuses_a_handoff_the_repository_moved_past(
        project, monkeypatch, capsys):
    """El chequeo de HEAD no se salta: reutilizar no puede ser un atajo."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    pinned_repository(project, monkeypatch, head=MOVED)
    document = reusable_handoff(project, head=HEAD)
    before = document.read_text()
    sent = record_sends(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", use_existing=True, timeout=0.2, interval=0.01,
        swap=True) == 1

    err = capsys.readouterr().err
    assert f"the handoff declares {HEAD} and the repository is at {MOVED}" in err
    assert "ask for a new handoff" in err.lower()
    assert sent == []
    assert document.read_text() == before
    assert "tab.close" not in project.commands()
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["pid"] == 500


def test_use_existing_without_a_swap_is_refused(project, monkeypatch, capsys):
    """Sin --swap no hay sesión que relevar: se dice y no se hace nada."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    reusable_handoff(project)
    sent = record_sends(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", use_existing=True, timeout=0.2, interval=0.01) == 1

    err = capsys.readouterr().err
    assert "--swap" in err
    assert "there is no session to replace" in err
    assert "Nothing was sent or written" in err
    assert sent == []
    assert project.commands() == []
    assert project.registry()["herdr"]["tabs"]["orchestrator"]["pid"] == 500
    files = list((project.root / ".torcha" / "handoffs" / "orchestrator").glob("*.json"))
    assert len(files) == 1                              # no se escribió otro documento


def test_use_existing_falls_back_to_asking_and_says_so(project, monkeypatch, capsys):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    pinned_repository(project, monkeypatch)
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", use_existing=True, timeout=0.2, interval=0.01,
        swap=True) == 0

    err = capsys.readouterr().err
    assert "falling back to asking the agent" in err
    files = list((project.root / ".torcha" / "handoffs" / "orchestrator").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["status"] == "consumed"
    assert project.options_for("tab.new")


@pytest.mark.parametrize("changes", [
    {"status": "consumed"},
    {"status": "superseded"},
    {"agent_id": "worker_1"},
    {"project_name": "another-project"},
])
def test_a_document_that_no_longer_qualifies_is_not_reused(
        project, monkeypatch, capsys, changes):
    """Se vuelve a validar antes de usarlo: prepared, agent_id y project cuentan."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    pinned_repository(project, monkeypatch)
    ineligible = reusable_handoff(project, **changes)
    before = ineligible.read_text()
    sent = record_sends(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", use_existing=True, timeout=0.0, interval=0.01,
        swap=True) == 1

    err = capsys.readouterr().err
    assert "falling back to asking the agent" in err
    assert sent and ".torcha/handoffs/orchestrator" in sent[0]   # RELEVO salió
    assert ineligible.read_text() == before             # el no elegible no se toca
    assert "tab.close" not in project.commands()


def test_reuse_skips_an_ineligible_newer_document_for_a_valid_older_one(
        project, monkeypatch, capsys):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    pinned_repository(project, monkeypatch)
    now = time.time()
    older = reusable_handoff(
        project, minutes=300, mtime=now - 3600,
        handoff_id="22222222-2222-4222-8222-222222222222")
    newer = reusable_handoff(
        project, minutes=5, status="consumed", mtime=now,
        handoff_id="33333333-3333-4333-8333-333333333333")
    newer_before = newer.read_text()
    sent = record_sends(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", use_existing=True, timeout=0.2, interval=0.01,
        swap=True) == 0

    assert sent == []
    assert "reusing the handoff written 5h ago" in capsys.readouterr().out
    assert newer.read_text() == newer_before
    assert older.exists()


def test_force_and_use_existing_together_are_refused(project, monkeypatch, capsys):
    """Se contradicen: se dice en vez de elegir uno por su cuenta."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    reusable_handoff(project)
    sent = record_sends(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", use_existing=True, force=True, swap=True,
        timeout=0.2, interval=0.01) == 1

    err = capsys.readouterr().err
    assert "--force" in err and "--use-existing" in err
    assert sent == []
    assert "tab.close" not in project.commands()


def test_force_still_asks_again_when_a_valid_handoff_exists(
        project, monkeypatch, capsys):
    """Lo que `--force` ya hacía sigue igual, con el flag nuevo en la mano."""
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    pinned_repository(project, monkeypatch)
    reusable_handoff(project)
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(
        role="orchestrator", force=True, timeout=0.2, interval=0.01) == 0

    assert "handoff written and validated" in capsys.readouterr().out
    files = list((project.root / ".torcha" / "handoffs" / "orchestrator").glob("*.json"))
    assert len(files) == 2


def test_handoff_run_help_states_the_requirement_of_use_existing(project):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC_DIR), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    helped = subprocess.run([sys.executable, "-m", "torcha", "handoff",
                             "run", "--help"],
                            cwd=project.root, env=env,
                            capture_output=True, text=True)
    text = " ".join(helped.stdout.split())   # el ancho de línea no importa
    assert helped.returncode == 0
    assert "--use-existing" in text
    assert "Requires --swap" in text
    assert "git.head" in text


# --- naming the setup tab ---------------------------------------------------


def test_the_setup_tab_is_renamed_when_it_is_not_a_team_tab(project):
    seed_live(project, [live_tab("tb-team", "Orquestador", "t01", pid=500)])

    project.module.init_module._mark_setup_tab(
        {"id": "tb-setup", "name": "1"}, {"tb-team"})

    renames = project.options_for("tab.rename")
    assert renames and renames[0]["id"] == "tb-setup"
    assert renames[0]["name"] == "Torcha"


def test_a_team_tab_is_never_renamed(project):
    seed_live(project, [live_tab("tb-team", "Orquestador", "t01", pid=500)])

    project.module.init_module._mark_setup_tab(
        {"id": "tb-team", "name": "Orquestador"}, {"tb-team"})

    assert project.options_for("tab.rename") == []


def test_an_unidentifiable_terminal_is_left_alone(project):
    seed_live(project, [])
    project.module.init_module._mark_setup_tab(None, set())
    assert project.options_for("tab.rename") == []


def test_the_old_setup_tab_name_is_still_the_setup_tab(project):
    """Un tab `Agentorch` que dejó una entrevista anterior sigue sin ser un rol."""
    live = project.module.live

    def tab(name):
        return live.LiveTab(name=name, app="pi", status=None, active=False,
                            renamed=True, candidate=None)

    assert live.is_setup_tab(tab("Torcha"))
    assert live.is_setup_tab(tab("Agentorch"))
    assert live.role_tabs([tab("Agentorch")]) == []
    assert [item.name for item in live.role_tabs([tab("Agentorch"), tab("Worker 1")])] \
        == ["Worker 1"]


# --- language rules in the setup skill -------------------------------------


def test_the_setup_skill_separates_artifact_and_conversation_language(project):
    text = project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8")
    assert "Artifacts are English" in text
    assert "the human's language" in text
    # La comprobación pedida: el idioma de los agentes decide el de la charla.
    assert "What the agents answered in" in text
    assert "before your first message to the human" in text


def test_the_skill_sample_question_is_not_in_spanish(project):
    text = project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8")
    assert "Soy el asistente de configuración" not in text
    assert "translated into the language of the conversation" in text


# --- doctor ----------------------------------------------------------------


def test_doctor_passes_with_everything_in_place(project, monkeypatch, capsys):
    monkeypatch.setattr(project.module.doctor_module, "which",
                        lambda name: "/usr/bin/" + name)
    assert project.module.doctor() == 0
    out = capsys.readouterr().out
    assert "0 failure(s)" in out
    assert "1 warning(s)" in out          # no hay registry todavía


def test_doctor_fails_without_herdr_app(project, monkeypatch, capsys):
    monkeypatch.setattr(project.module.doctor_module, "which",
                        lambda name: None if name == "herdr-app" else "/usr/bin/" + name)
    assert project.module.doctor(as_json=True) == 1

    payload = json.loads(capsys.readouterr().out)
    assert "herdr-app" in payload["summary"]["failures"]


def test_doctor_fails_when_the_core_does_not_answer(project, monkeypatch, capsys):
    monkeypatch.setattr(project.module.doctor_module, "which",
                        lambda name: "/usr/bin/" + name)
    project.state.write_text(json.dumps({"spaces": [], "calls": [], "hc_down": True}))

    assert project.module.doctor(as_json=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert "herdr-core" in payload["summary"]["failures"]


def test_doctor_fails_with_a_broken_config(project, monkeypatch, capsys):
    monkeypatch.setattr(project.module.doctor_module, "which",
                        lambda name: "/usr/bin/" + name)
    (project.root / ".torcha" / "agents.json").write_text('{"tabs": []}')

    assert project.module.doctor(as_json=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert "config" in payload["summary"]["failures"]


def test_doctor_warns_when_the_registry_is_partial(project, monkeypatch, capsys):
    monkeypatch.setattr(project.module.doctor_module, "which",
                        lambda name: "/usr/bin/" + name)
    write_registry(project, status="partial")

    assert project.module.doctor(as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "registry" in payload["summary"]["warnings"]


def test_doctor_warns_when_a_bootstrap_file_holds_another_mode(project, monkeypatch, capsys):
    """S16: the same disagreement, as a report that does not fail a healthy project."""
    monkeypatch.setattr(project.module.doctor_module, "which",
                        lambda name: "/usr/bin/" + name)
    seed_bootstrap_file(project, mode="recover")   # la config dice `greet`

    assert project.module.doctor(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert "bootstrap" not in payload["summary"]["failures"]
    assert "bootstrap" in payload["summary"]["warnings"]
    check = next(item for item in payload["checks"] if item["name"] == "bootstrap")
    assert "orchestrator" in check["detail"]
    assert ".torcha/bootstrap/orchestrator.md" in check["detail"]


def test_doctor_is_quiet_about_bootstrap_files_that_match(project, monkeypatch, capsys):
    """S16: a file holding exactly the configured mode is not a finding."""
    monkeypatch.setattr(project.module.doctor_module, "which",
                        lambda name: "/usr/bin/" + name)
    for tab in TABS:
        seed_bootstrap_file(project, tab["key"])

    assert project.module.doctor(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    check = next(item for item in payload["checks"] if item["name"] == "bootstrap")
    assert check["state"] == "ok"


# --- which space belongs to the project -------------------------------------


def seeded_space(space_id, name, folder, cwd, terminal="t01", app="pi"):
    return {
        "id": space_id, "name": name, "folder": folder, "active": True,
        "tabs": [{"id": "tb-" + space_id, "name": "Orquestador", "active": True,
                  "terminals": [{"terminal": terminal, "pane": "p-" + terminal,
                                 "cwd": cwd, "app": app, "status": "idle",
                                 "pid": 500}]}],
    }


def test_init_matches_by_terminal_cwd_not_by_the_folder_field(project):
    """The real case: a space claims this folder but its terminal is elsewhere."""
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "other", str(project.root), "/somewhere/else", "t01"),
        seeded_space("sp02", "proj", "/wrong/folder", str(project.root), "t02"),
    ], "calls": []}))

    assert project.module.init() == 0
    assert project.commands().count("space.new") == 0
    assert project.registry()["herdr"]["space_id"] == "sp02"


def test_init_ignores_a_space_whose_folder_matches_but_terminals_do_not(project):
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "other", str(project.root), "/somewhere/else", "t01"),
    ], "calls": []}))

    assert project.module.init() == 0
    assert project.commands().count("space.new") == 1


def test_init_accepts_a_terminal_inside_the_project(project):
    sub = project.root / "pkg"
    sub.mkdir()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(sub), "t01"),
    ], "calls": []}))

    assert project.module.init() == 0
    assert project.commands().count("space.new") == 0
    assert project.registry()["herdr"]["space_id"] == "sp01"


def test_an_exact_match_wins_over_a_subfolder_match(project):
    sub = project.root / "pkg"
    sub.mkdir()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "sub", "/wrong", str(sub), "t01"),
        seeded_space("sp02", "exact", "/wrong", str(project.root), "t02"),
    ], "calls": []}))

    assert project.module.init() == 0
    assert project.registry()["herdr"]["space_id"] == "sp02"


def test_init_fails_when_herdr_core_is_missing(project, monkeypatch):
    """No herdr-core means no reliable folder, so it refuses instead of guessing."""
    monkeypatch.setattr(project.module.herdr, "which",
                        lambda name: None if name == "hc" else "/usr/bin/" + name)
    with pytest.raises(project.module.TorchaError, match="herdr-core"):
        project.module.herdr.terminal_folders()


def test_init_reports_a_missing_herdr_core(project, monkeypatch):
    monkeypatch.setattr(project.module.herdr, "which",
                        lambda name: None if name == "hc" else "/usr/bin/" + name)
    project.state.write_text(json.dumps({"spaces": [], "calls": []}))

    assert project.module.init() == 1
    assert project.commands().count("space.new") == 0


def test_init_starts_the_core_and_retries_when_it_does_not_answer(project):
    project.state.write_text(json.dumps({
        "spaces": [seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": [], "hc_down": True,
    }))

    assert project.module.init() == 0

    calls = project.read_state().get("hc_calls", [])
    assert ["server", "start"] in calls
    assert project.registry()["herdr"]["space_id"] == "sp01"


def test_init_reports_when_the_core_cannot_be_started(project):
    project.state.write_text(json.dumps({
        "spaces": [], "calls": [], "hc_down": True, "hc_start_fails": True,
    }))

    assert project.module.init() == 1
    assert project.commands().count("space.new") == 0


def test_a_space_without_live_terminals_does_not_match(project):
    """A space whose terminals are gone cannot be placed, so it is not adopted."""
    space = seeded_space("sp01", "proj", str(project.root), None, "t01", app=None)
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))

    assert project.module.init() == 0
    assert project.commands().count("space.new") == 1


def test_a_failed_init_keeps_the_previous_registry(project):
    registry_file = project.root / ".torcha" / "registry.json"
    registry_file.write_text(json.dumps({"herdr": {"space_id": "sp-old"}}))
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "a", str(project.root), str(project.root), "t01"),
        seeded_space("sp02", "b", str(project.root), str(project.root), "t02"),
    ], "calls": []}))

    assert project.module.init() == 1
    assert json.loads(registry_file.read_text())["herdr"]["space_id"] == "sp-old"


# --- live workspace: renamed tabs that already run an agent -----------------


def live_space(folder):
    return {
        "id": "sp01", "name": "proj", "folder": folder, "active": True,
        "tabs": [
            {"id": "tb1", "name": "Senior Orchestrator", "active": True,
             "terminals": [{"terminal": "t1", "pane": "p1", "cwd": folder,
                            "app": "pi", "status": "idle"}]},
            {"id": "tb2", "name": "Scout", "active": False,
             "terminals": [{"terminal": "t2", "pane": "p2", "cwd": folder,
                            "app": "pi", "status": "working"}]},
            {"id": "tb3", "name": "3", "active": False,
             "terminals": [{"terminal": "t3", "pane": "p3", "cwd": folder,
                            "app": None, "status": None}]},
        ],
    }


def declared_pair(project):
    discovery = project.module.discovery
    return [
        discovery.Candidate("job_senior", "job-senior",
                            "Job-search orchestrator. Owns triage.", "pi", "project", "p"),
        discovery.Candidate("job_scout", "job-scout",
                            "Indexes lead sources (job fairs).", "pi", "project", "p"),
    ]


def test_is_renamed_treats_numeric_names_as_untouched(project):
    is_renamed = project.module.live.is_renamed
    assert is_renamed("1") is False
    assert is_renamed("12") is False
    assert is_renamed("") is False
    assert is_renamed(None) is False
    assert is_renamed("Scout") is True
    assert is_renamed("Worker 1") is True


def test_match_tab_needs_every_word_of_the_tab_name(project):
    match_tab = project.module.live.match_tab
    candidates = declared_pair(project)
    assert match_tab("Scout", candidates).key == "job_scout"
    assert match_tab("Senior Orchestrator", candidates).key == "job_senior"
    assert match_tab("Revisor", candidates) is None


def test_inspect_space_classifies_renamed_tabs_with_agents(project):
    candidates = declared_pair(project)
    tabs = project.module.live.inspect_space(live_space(str(project.root)), candidates)

    assert [tab.renamed for tab in tabs] == [True, True, False]
    assert [tab.has_agent for tab in tabs] == [True, True, False]
    assert tabs[0].candidate.key == "job_senior"
    assert tabs[1].candidate.key == "job_scout"
    assert tabs[2].candidate is None
    assert tabs[1].status == "working"


def test_inspect_space_does_not_match_an_untouched_numeric_tab(project):
    """A tab named "1" would otherwise match a role called "worker-1"."""
    discovery = project.module.discovery
    candidates = [discovery.Candidate("worker_1", "worker-1", "Implements changes.",
                                      "pi", "project", "p")]
    space = {"id": "sp01", "folder": "/x", "tabs": [
        {"id": "tb1", "name": "1", "active": True,
         "terminals": [{"terminal": "t1", "pane": "p1", "app": "pi",
                        "status": "idle"}]},
    ]}

    tabs = project.module.live.inspect_space(space, candidates)
    assert tabs[0].renamed is False
    assert tabs[0].candidate is None


def test_discover_live_reports_tabs_and_their_roles(project, capsys):
    project.state.write_text(json.dumps(
        {"spaces": [live_space(str(project.root))], "calls": []}))
    write_agent(project.root / ".pi/agents/senior.md", "job-senior",
                "Job-search orchestrator.")
    write_agent(project.root / ".pi/agents/scout.md", "job-scout",
                "Indexes lead sources.")

    assert project.module.discover(live=True) == 0

    captured = capsys.readouterr()
    assert "Senior Orchestrator" in captured.err
    assert "renamed" in captured.err
    assert "agent=pi" in captured.err
    assert "job_senior" in captured.err
    # The proposal comes from the live tabs, not from the files: the human's
    # names win, and the keys come from the matched roles.
    proposed = json.loads(captured.out)["tabs"]
    assert [tab["name"] for tab in proposed] == ["Orchestrator", "Scout"]
    assert proposed[0]["key"] == "orchestrator"


def test_proposal_from_live_is_empty_without_renamed_tabs(project):
    space = {"id": "sp01", "folder": "/x", "tabs": [
        {"id": "tb1", "name": "1", "active": True,
         "terminals": [{"terminal": "t1", "pane": "p1", "app": "pi",
                        "status": "idle"}]},
    ]}
    tabs = project.module.live.inspect_space(space, [])
    assert project.module.live.proposal_from_live(tabs) == []


def test_proposal_from_live_marks_roles_nobody_declared(project):
    space = {"id": "sp01", "folder": "/x", "tabs": [
        {"id": "tb1", "name": "Orchestrator", "active": True,
         "terminals": [{"terminal": "t1", "pane": "p1", "app": "pi",
                        "status": "idle"}]},
        {"id": "tb2", "name": "Revisor", "active": False,
         "terminals": [{"terminal": "t2", "pane": "p2", "app": None,
                        "status": None}]},
    ]}
    live = project.module.live
    proposal = live.proposal_from_live(live.inspect_space(space, []))
    assert [tab["key"] for tab in proposal] == ["orchestrator", "revisor"]
    assert proposal[1]["role"] == live.UNDECLARED_ROLE


def test_discover_live_without_a_space_for_the_project(project, capsys):
    write_agent(project.root / ".pi/agents/scout.md", "job-scout", "Indexes sources.")

    assert project.module.discover(live=True) == 0
    assert "There is no Herdr space for this project" in capsys.readouterr().err


def test_discover_live_points_at_a_space_whose_name_matches_another_folder(project, capsys):
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": "/somewhere/else", "active": True,
        "tabs": [],
    }], "calls": []}))
    write_agent(project.root / ".pi/agents/scout.md", "job-scout", "Indexes sources.")

    assert project.module.discover(live=True) == 0

    err = capsys.readouterr().err
    assert "there is a space named 'proj'" in err
    assert "/somewhere/else" in err


# --- the team limit and the tabs that are not roles -------------------------

# The shape measured in career-ops: six named roles, the setup tab a previous
# interview renamed, and Herdr's own "7" for a fresh tab.
CAREER_OPS_ROLES = ["Senior Orchestrator", "Scout", "Communicator",
                    "Auditor", "Builder", "Coach"]


def role_tab(number: int, name: str, folder: str, app="pi") -> dict:
    return {"id": "tb-%02d" % number, "name": name, "active": number == 1,
            "terminals": [{"terminal": "t-%02d" % number,
                           "pane": "p-%02d" % number, "cwd": folder,
                           "app": app, "status": "idle" if app else None}]}


def career_ops_space(folder: str, roles=None) -> dict:
    names = list(roles or CAREER_OPS_ROLES)
    tabs = [role_tab(number, name, folder)
            for number, name in enumerate(names, 1)]
    tabs.append(role_tab(len(names) + 1, "Torcha", folder))
    tabs.append({"id": "tb-new", "name": str(len(names) + 2), "active": False,
                 "terminals": [{"terminal": "t-new", "pane": "p-new",
                                "cwd": folder, "app": None, "status": None}]})
    return {"id": "sp01", "name": "proj", "folder": folder, "active": True,
            "tabs": tabs}


def test_the_skeleton_lists_every_named_role_and_never_the_setup_tab(project, monkeypatch):
    """career-ops: six named roles with an agent, the setup tab and an unused "7"."""
    (project.root / ".torcha/agents.json").unlink()
    project.state.write_text(json.dumps(
        {"spaces": [career_ops_space(str(project.root))], "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    tabs = json.loads((project.root / ".torcha/agents.json").read_text())["tabs"]
    assert [tab["name"] for tab in tabs] == CAREER_OPS_ROLES
    assert tabs[0]["key"] == "orchestrator"
    assert tabs[-1]["key"] == "coach"


def test_the_proposal_lists_every_named_role_and_never_the_setup_tab(project, capsys):
    project.state.write_text(json.dumps(
        {"spaces": [career_ops_space(str(project.root))], "calls": []}))

    assert project.module.discover(live=True) == 0

    proposed = json.loads(capsys.readouterr().out)["tabs"]
    assert [tab["name"] for tab in proposed] == \
        ["Orchestrator"] + CAREER_OPS_ROLES[1:]
    assert "Torcha" not in [tab["name"] for tab in proposed]


def test_the_tab_running_the_interview_is_never_a_role(project, monkeypatch):
    (project.root / ".torcha/agents.json").unlink()
    folder = str(project.root)
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": folder, "active": True,
        "tabs": [role_tab(1, "Senior Orchestrator", folder),
                 role_tab(2, "Scout", folder),
                 role_tab(3, "Scratch", folder)]}], "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_own_tab",
                        lambda: {"id": "tb-03", "name": "Scratch"})
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    tabs = json.loads((project.root / ".torcha/agents.json").read_text())["tabs"]
    assert [tab["name"] for tab in tabs] == ["Senior Orchestrator", "Scout"]


def test_the_skeleton_only_takes_named_tabs_with_a_live_agent(project):
    folder = str(project.root)
    space = {"id": "sp01", "name": "proj", "folder": folder, "active": True,
             "tabs": [role_tab(1, "Senior Orchestrator", folder),
                      role_tab(2, "Scout", folder),
                      role_tab(3, "Paused", folder, app=None)]}
    live = project.module.live

    skeleton = live.skeleton_from_live(live.inspect_space(space, []))

    assert [tab["name"] for tab in skeleton] == ["Senior Orchestrator", "Scout"]


def test_the_default_limit_is_ten_and_the_tabs_it_cuts_are_named(project, capsys):
    roles = CAREER_OPS_ROLES + ["Reviewer", "Tester", "Archivist",
                                "Deployer", "Recruiter", "Analyst"]
    live = project.module.live

    skeleton = live.skeleton_from_live(
        live.inspect_space(career_ops_space(str(project.root), roles), []))

    err = capsys.readouterr().err
    assert [tab["name"] for tab in skeleton] == roles[:10]
    assert "Recruiter" in err and "Analyst" in err
    # Las que se quedan dentro no se nombran: solo se avisa de las recortadas.
    assert "Coach" not in err


def test_the_configured_max_tabs_is_used_and_only_the_cut_tabs_are_named(project, capsys):
    project.state.write_text(json.dumps(
        {"spaces": [career_ops_space(str(project.root))], "calls": []}))
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "max_tabs": 3, "tabs": TABS}))

    assert project.module.discover(live=True) == 0

    captured = capsys.readouterr()
    assert [tab["name"] for tab in json.loads(captured.out)["tabs"]] == \
        ["Orchestrator", "Scout", "Communicator"]
    cut = next(line for line in captured.err.splitlines() if "leaves out" in line)
    assert "Auditor" in cut and "Coach" in cut
    # La tab de setup queda excluida, no recortada: no se nombra.
    assert "Torcha" not in cut


def test_the_skeleton_keeps_the_live_names_with_the_orchestrator_first(project):
    folder = str(project.root)
    space = {"id": "sp01", "name": "proj", "folder": folder, "active": True,
             "tabs": [role_tab(1, "Scout", folder),
                      role_tab(2, "Senior Orchestrator", folder),
                      role_tab(9, "9", folder)]}
    live = project.module.live

    skeleton = live.skeleton_from_live(live.inspect_space(space, []))

    assert [tab["name"] for tab in skeleton] == ["Senior Orchestrator", "Scout"]
    assert [tab["key"] for tab in skeleton] == ["orchestrator", "scout"]
    assert [tab["role"] for tab in skeleton] == ["", ""]


# --- a named tab whose agent died is not lost in silence --------------------

def career_ops_space_with_a_dead_agent(folder: str) -> dict:
    """The measured career-ops shape: Coach is named but has no program."""
    space = career_ops_space(folder)
    for tab in space["tabs"]:
        if tab["name"] == "Coach":
            tab["terminals"][0]["app"] = None
            tab["terminals"][0]["status"] = None
    return space


def test_a_named_tab_without_an_agent_is_reported_once_with_a_way_forward(
        project, capsys):
    project.state.write_text(json.dumps({
        "spaces": [career_ops_space_with_a_dead_agent(str(project.root))],
        "calls": []}))

    assert project.module.discover(live=True) == 0

    captured = capsys.readouterr()
    # role_tabs has several callers in one command (the proposal, the election
    # of the orchestrator); the note belongs to the command, so it prints once.
    reported = [line for line in captured.err.splitlines()
                if "no agent running" in line]
    assert len(reported) == 1
    assert "Coach" in reported[0]
    assert "torcha start <role> --recreate" in reported[0]
    assert "by hand" in reported[0]


def test_only_the_named_tab_without_an_agent_is_reported(
        project, monkeypatch, capsys):
    """The setup marker, an unnamed tab and the caller's own tab stay silent."""
    (project.root / ".torcha/agents.json").unlink()
    folder = str(project.root)
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": folder, "active": True,
        "tabs": [role_tab(1, "Senior Orchestrator", folder),
                 role_tab(2, "Coach", folder, app=None),
                 role_tab(3, "Torcha", folder),
                 role_tab(4, "7", folder, app=None),
                 role_tab(5, "Scratch", folder)]}], "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_own_tab",
                        lambda: {"id": "tb-05", "name": "Scratch"})
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    reported = [line for line in capsys.readouterr().err.splitlines()
                if "no agent running" in line]
    assert len(reported) == 1
    assert "Coach" in reported[0]
    for silent in ("Torcha", "7", "Scratch"):
        assert silent not in reported[0]


def test_init_reports_a_named_tab_without_an_agent_on_both_paths(
        project, monkeypatch, capsys):
    folder = str(project.root)
    project.state.write_text(json.dumps({
        "spaces": [career_ops_space_with_a_dead_agent(folder)], "calls": []}))
    config = project.root / ".torcha/agents.json"

    # The fallback, which proposes from the live tabs without an interview.
    config.unlink()
    tabs, origin = project.module.init_module.initial_tabs([])
    assert origin == "named live tabs"
    fallback = capsys.readouterr().err
    assert "no agent running" in fallback and "Coach" in fallback

    # The interview path, which builds the skeleton.
    config.unlink(missing_ok=True)
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)
    project.module.init_module.start_interview([])
    interview = capsys.readouterr().err
    assert "no agent running" in interview and "Coach" in interview


def agent_less_space(folder: str) -> dict:
    """The career-ops shape with every named tab back on a bare shell."""
    space = career_ops_space(folder)
    for tab in space["tabs"]:
        tab["terminals"][0]["app"] = None
        tab["terminals"][0]["status"] = None
    return space


def test_one_init_prints_the_agent_less_note_once(project, monkeypatch, capsys):
    """Every named tab is agent-less: the interview reports and returns an empty
    skeleton, and the fallback then inspects the same space. Both paths are one
    command, so the human reads the note once."""
    (project.root / ".torcha/agents.json").unlink()
    project.state.write_text(json.dumps({
        "spaces": [agent_less_space(str(project.root))], "calls": []}))
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty",
                        lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty",
                        lambda: True)
    monkeypatch.setattr(project.module.init_module, "_own_tab", lambda: None)
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    assert project.module.init() == 0

    reported = [line for line in capsys.readouterr().err.splitlines()
                if "no agent running" in line]
    assert len(reported) == 1
    assert "Coach" in reported[0]


def test_the_tab_running_the_command_is_never_reported_or_proposed(
        project, capsys):
    """A named shell tab that runs the command is the setup terminal, not a role.

    `start_interview` already excludes it; the report and the proposal have to
    agree, or `discover --live` warns about the pane the human is typing in and
    the fallback proposes it as a role.
    """
    folder = str(project.root)
    own = role_tab(2, "Scratch", folder, app=None)
    # The pane this process runs in: herdr-core reports it with our own pid, so
    # `own_terminal` finds it without any test-only seam.
    own["terminals"][0]["pid"] = os.getpid()
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": folder, "active": True,
        "tabs": [role_tab(1, "Senior Orchestrator", folder), own]}],
        "calls": []}))

    # `discover --live`: neither a warning nor a proposal for the own tab.
    assert project.module.discover(live=True) == 0
    captured = capsys.readouterr()
    assert "no agent running" not in captured.err
    assert [tab["name"] for tab in json.loads(captured.out)["tabs"]] == \
        ["Orchestrator"]

    # The fallback in `init`: the own tab is not a role there either.
    (project.root / ".torcha/agents.json").unlink()
    tabs, origin = project.module.init_module.initial_tabs([])
    assert origin == "named live tabs"
    assert [tab["name"] for tab in tabs] == ["Orchestrator"]
    assert "no agent running" not in capsys.readouterr().err


# --- the tabs the configuration does not declare (S20) ----------------------

def team_space(folder: str) -> dict:
    """One space where the team declared in TABS is already live."""
    return {"id": "sp01", "name": "proj", "folder": folder, "active": True,
            "tabs": [role_tab(index, tab["name"], folder)
                     for index, tab in enumerate(TABS, start=1)]}


def add_live_tab(space: dict, name: str, app="pi", pid=None) -> dict:
    """One more tab in the space, with its own tab, terminal and pane ids."""
    tab = role_tab(len(space["tabs"]) + 1, name, space["folder"], app=app)
    if pid is not None:
        tab["terminals"][0]["pid"] = pid
    space["tabs"].append(tab)
    return tab


def test_init_names_the_live_tabs_outside_the_team_and_the_role_it_would_add(
        project, capsys):
    """S20: the command that reconciles the team says what the team leaves out."""
    space = team_space(str(project.root))
    add_live_tab(space, "Coach")
    add_live_tab(space, "Auditor")
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))

    assert project.module.init() == 0

    out = capsys.readouterr().out
    reported = [line for line in out.splitlines() if "outside the team" in line]
    assert len(reported) == 1                    # one line, not one line per tab
    line = reported[0]
    for name, key in (("Coach", "coach"), ("Auditor", "auditor")):
        assert f"{name} would add role '{key}'" in line
        assert f"name '{name}'" in line
    # After the run's summary, and never about a tab the team declares.
    assert out.index(line) > out.index("Tabs verified:")
    for declared in ("Orquestador", "Worker 1", "Worker 4"):
        assert declared not in line


def test_the_report_of_tabs_outside_the_team_writes_nothing(project, capsys):
    """A report, not an adoption: the configuration is the human's to edit."""
    space = team_space(str(project.root))
    add_live_tab(space, "Coach")
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))
    config = project.root / ".torcha/agents.json"
    before = config.read_bytes()

    assert project.module.init() == 0

    assert "outside the team" in capsys.readouterr().out    # it did report
    assert config.read_bytes() == before                    # byte for byte
    assert project.commands().count("tab.new") == 0         # no tab for Coach
    entries = project.registry()["herdr"]["tabs"]
    assert set(entries) == {tab["key"] for tab in TABS}     # no role recorded
    selected = [options["id"] for options in project.options_for("tab.select")]
    assert selected == [entries["orchestrator"]["tab_id"]]  # focus unmoved


def test_the_report_never_names_a_tab_without_an_agent(project, capsys):
    """A named tab with no agent is `report_tabs_without_agent`'s subject."""
    space = team_space(str(project.root))
    add_live_tab(space, "Coach")
    add_live_tab(space, "Idle", app=None)
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))

    assert project.module.init() == 0

    captured = capsys.readouterr()
    line = next(line for line in captured.out.splitlines()
                if "outside the team" in line)
    assert line.count("would add role") == 1
    assert "Coach would add role 'coach'" in line
    assert "Idle" not in captured.out


def test_the_two_reports_partition_the_live_tabs(project, capsys):
    """One predicate, two subjects: with an agent (outside the team) or without."""
    folder = str(project.root)
    space = team_space(folder)
    caller = add_live_tab(space, "Scratch")
    caller["terminals"][0]["pid"] = os.getpid()
    add_live_tab(space, "Coach")
    add_live_tab(space, "Idle", app=None)
    add_live_tab(space, "Torcha")
    add_live_tab(space, "7")
    own_id = caller["id"]
    tabs = project.module.live.inspect_space(space, [])

    outside = {item["tab"].name for item in
               project.module.live.outside_team(tabs, TABS, set(), own_id)}
    idle = {tab.name for tab in project.module.live.report_tabs_without_agent(
        tabs, own_id)}

    assert outside == {"Coach"}
    assert idle == {"Idle"}
    assert outside.isdisjoint(idle)


def test_the_report_skips_the_setup_tab_the_numeric_tab_and_the_caller(
        project, capsys):
    """The tabs excluded on purpose stay out of it, as everywhere else."""
    space = team_space(str(project.root))
    add_live_tab(space, "Torcha")            # the setup marker
    add_live_tab(space, "7")                    # Herdr's own default name
    caller = add_live_tab(space, "Scratch")      # this command's own tab
    caller["terminals"][0]["pid"] = os.getpid()
    add_live_tab(space, "Coach")
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))

    assert project.module.init() == 0

    line = next(line for line in capsys.readouterr().out.splitlines()
                if "outside the team" in line)
    assert line.count("would add role") == 1
    assert "Coach would add role 'coach'" in line
    for silent in ("Torcha", "Scratch", "7 would add"):
        assert silent not in line


def test_init_json_carries_the_tabs_outside_the_team(project, capsys):
    space = team_space(str(project.root))
    add_live_tab(space, "Coach")
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))

    assert project.module.init(as_json=True) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)           # stdout holds the object alone
    assert payload["space_id"] == "sp01"
    assert payload["outside_team"] == [{
        "name": "Coach", "tab_id": "tb-06", "terminal_id": "t-06",
        "app": "pi",
        "suggested_role": {"key": "coach", "name": "Coach"}}]
    # The human line is not printed as well: the object carries the list.
    assert "outside the team" not in captured.out
    # This run's narration moves to stderr, so stdout stays machine-readable.
    assert "Initialisation and reconciliation complete." in captured.err


def test_init_json_keeps_stdout_for_the_object_during_an_interview(
        project, monkeypatch, capsys):
    """The interview's narration moves to stderr too: stdout stays parseable."""
    (project.root / ".torcha/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)
    project.state.write_text(json.dumps({"spaces": [], "calls": []}))

    def fake_interview(candidates, seen=None, say=None):
        (project.root / ".torcha/agents.json").write_text(json.dumps({
            "pi": {"executable": "pi", "bootstrap": "greet"}, "tabs": TABS}))
        return project.module.init_module.Interview(ran=True)

    monkeypatch.setattr(project.module.init_module, "start_interview", fake_interview)

    assert project.module.init(as_json=True) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["outside_team"] == []
    assert "Initialisation and reconciliation complete." in captured.err


def test_init_accepts_the_json_flag_from_the_command_line(project):
    space = team_space(str(project.root))
    add_live_tab(space, "Coach")
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC_DIR), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)

    result = subprocess.run(
        [sys.executable, "-m", "torcha", "init", "--json", "--plain",
         "--project", str(project.root)],
        cwd=project.root, env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [item["suggested_role"]["key"] for item in payload["outside_team"]] \
        == ["coach"]


def test_a_workspace_inside_the_team_says_nothing_extra(project, capsys):
    space = team_space(str(project.root))
    project.state.write_text(json.dumps({"spaces": [space], "calls": []}))

    assert project.module.init() == 0
    assert "outside the team" not in capsys.readouterr().out


# --- the main session -------------------------------------------------------


def make_tab(module, name, app=None, candidate=None):
    return module.live.LiveTab(name=name, app=app, status=None, active=False,
                               renamed=module.live.is_renamed(name),
                               candidate=candidate)


def test_designate_orchestrator_by_its_name(project):
    module = project.module
    tabs = [make_tab(module, "Orquestador"), make_tab(module, "Worker 1")]
    assert module.live.designate_orchestrator(tabs).name == "Orquestador"


def test_designate_orchestrator_falls_back_to_the_only_live_agent(project):
    module = project.module
    tabs = [make_tab(module, "Alice", app="pi"), make_tab(module, "Bob")]
    assert module.live.designate_orchestrator(tabs).name == "Alice"


def test_designate_orchestrator_refuses_to_guess_between_two_agents(project):
    module = project.module
    tabs = [make_tab(module, "Alice", app="pi"), make_tab(module, "Bob", app="pi")]
    assert module.live.designate_orchestrator(tabs) is None


def test_designate_orchestrator_prefers_a_stated_name_over_the_only_agent(project):
    module = project.module
    tabs = [make_tab(module, "Orchestrator"), make_tab(module, "Worker", app="pi")]
    assert module.live.designate_orchestrator(tabs).name == "Orchestrator"


def test_default_team_and_orchestrator_are_named_in_english(project):
    assert project.module.config.DEFAULT_TABS[0]["name"] == "Orchestrator"
    assert project.module.discovery.DEFAULT_ORCHESTRATOR["name"] == "Orchestrator"


def test_two_tabs_with_the_same_name_do_not_steal_the_registry(project):
    """Con dos tabs homónimas, el relevo adopta la que creó, no la ajena."""
    start_registry(project)
    seed_bootstrap_file(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None),
                        live_tab("tb99", "Orquestador", "t99", app=None)])

    project.module.start(fresh=True, timeout=0.5, interval=0.01)

    live = [tab["id"] for tab in project.read_state()["spaces"][0]["tabs"]
            if tab["name"] == "Orquestador"]
    created = [identifier for identifier in live if identifier not in {"tb1", "tb99"}]
    assert created, "el fake debería haber creado una tab nueva"
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["tab_id"] == created[0]
    assert entry["tab_id"] != "tb99"


def test_a_failed_create_is_reported_and_the_registry_does_not_lie(project, monkeypatch):
    """Si `tab.new` falla después de cerrar, el registro no apunta a la tab cerrada."""
    start_registry(project)
    seed_bootstrap_file(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])
    module = sys.modules[project.module.start.__module__]
    real = module.run_app

    def explode(args):
        if args[:2] == ["do", "tab.new"]:
            raise module.TorchaError("boom")
        return real(args)

    monkeypatch.setattr(module, "run_app", explode)

    assert project.module.start(timeout=0.5, interval=0.01) == 1
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["tab_id"] is None
    assert entry["terminal_id"] is None


# --- ls: the declared team against reality ----------------------------------


def ls_registry_tabs():
    """Four of the five declared roles adopted, each in a different state."""
    return {
        "orchestrator": {"name": "Orquestador", "tab_id": "tb1",
                         "terminal_id": "t1", "pane_id": "p1", "app": "pi",
                         "pid": 500, "session_id": "01a1f453-0174-7369"},
        "worker_1": {"name": "Worker 1", "tab_id": "tb2", "terminal_id": "t2",
                     "pane_id": "p2", "app": None, "pid": None,
                     "session_id": None},
        "worker_2": {"name": "Worker 2", "tab_id": "tb-missing",
                     "terminal_id": "t9", "pane_id": "p9", "app": "pi",
                     "pid": 600, "session_id": "02b2b2b2-2222-4222"},
        "worker_3": {"name": "Worker 3", "tab_id": "tb3", "terminal_id": "t3",
                     "pane_id": "p3", "app": "pi", "pid": 500,
                     "session_id": "03c3c3c3-3333-4333"},
    }


def ls_live_tabs():
    return [live_tab("tb1", "Orquestador", "t1", pid=500),
            live_tab("tb2", "Worker 1", "t2", app=None),
            live_tab("tb3", "Worker 3", "t3", pid=777)]


def ls_rows(stdout):
    """The role lines, without the `[torcha] ` prefix and keeping the padding."""
    return [line[len("[torcha] "):] for line in stdout.splitlines()
            if line.startswith("[torcha]   ")]


def test_ls_prints_one_line_per_declared_role_in_declaration_order(project, capsys):
    write_registry(project, tabs=ls_registry_tabs())
    seed_live(project, ls_live_tabs())

    assert project.module.ls() == 0

    out = capsys.readouterr().out
    assert "[torcha] Space sp01 · proj" in out
    assert ls_rows(out) == [
        "  orchestrator  Orquestador  t1        alive        01a1f453  pid 500",
        "  worker_1      Worker 1     t2        down         —         no agent (shell)",
        "  worker_2      Worker 2     t9        missing      02b2b2b2  the tab no longer exists",
        "  worker_3      Worker 3     t3        moved        03c3c3c3  the pid changed: 500 → 777",
        "  worker_4      Worker 4     —         not adopted  —         no tab in the registry",
    ]
    assert "[torcha] No live tab is outside the team." in out
    assert "[torcha] 5 declared · 4 adopted · 1 alive" in out


def test_ls_names_the_live_tabs_that_are_not_in_the_team(project, capsys):
    """The setup marker, a bare number and the caller's tab are never named."""
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500,
        "session_id": "01a1f453-0174-7369"}})
    folder = str(project.root)
    own = {"id": "tb-own", "name": "Scratch", "active": False,
           "terminals": [{"terminal": "t-own", "pane": "p-own", "cwd": folder,
                          "app": None, "status": None, "pid": os.getpid()}]}
    seed_live(project, [
        live_tab("tb1", "Orquestador", "t1", pid=500),
        live_tab("tb2", "Coach", "t2"),
        live_tab("tb3", "Reviewer", "t3", app=None),
        live_tab("tb4", "Torcha", "t4"),
        live_tab("tb5", "7", "t5", app=None),
        own,
    ])

    assert project.module.ls() == 0

    out = capsys.readouterr().out
    assert "[torcha] Tabs not in the team (2): Coach, Reviewer" in out
    assert "Torcha" not in out
    assert "Scratch" not in out
    assert ", 7" not in out


def test_ls_json_carries_the_same_data(project, capsys):
    write_registry(project, tabs=ls_registry_tabs())
    seed_live(project, ls_live_tabs())

    assert project.module.ls(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [role["key"] for role in payload["roles"]] == [
        "orchestrator", "worker_1", "worker_2", "worker_3", "worker_4"]
    assert payload["roles"][0] == {
        "key": "orchestrator", "name": "Orquestador", "terminal": "t1",
        "state": "alive", "session": "01a1f453",
        "session_id": "01a1f453-0174-7369", "detail": "pid 500"}
    assert payload["roles"][-1]["state"] == "not adopted"
    assert payload["roles"][-1]["terminal"] is None
    assert payload["roles"][-1]["session"] is None
    assert payload["space"] == {"id": "sp01", "name": "proj"}
    assert payload["undeclared"] == []
    assert payload["errors"] == []
    assert payload["summary"] == {"declared": 5, "adopted": 4, "alive": 1}


def test_ls_is_read_only(project, capsys):
    """No tab is created, closed, moved or focused, and the registry is untouched."""
    write_registry(project, tabs=ls_registry_tabs())
    seed_live(project, ls_live_tabs() + [live_tab("tb9", "Coach", "t9")])
    registry_file = project.root / ".torcha" / "registry.json"
    before = registry_file.read_text()

    assert project.module.ls() == 0
    capsys.readouterr()

    assert project.commands() == []
    assert registry_file.read_text() == before
    assert project.read_state()["calls"] == [["ls"]]
    assert "hc_sent" not in project.read_state()


def test_ls_says_what_it_can_when_the_registry_is_unreadable(project, capsys):
    (project.root / ".torcha" / "registry.json").unlink(missing_ok=True)
    seed_live(project, ls_live_tabs())

    assert project.module.ls() == 1

    captured = capsys.readouterr()
    rows = ls_rows(captured.out)
    assert len(rows) == 5
    for row, key in zip(rows, ["orchestrator", "worker_1", "worker_2",
                               "worker_3", "worker_4"]):
        assert row.startswith(f"  {key}")
        assert "unknown" in row
        assert "the registry could not be read" in row
    assert "[torcha] 5 declared · ? adopted · ? alive" in captured.out
    assert "The registry does not exist" in captured.err


def test_ls_says_what_it_can_when_the_live_workspace_is_unreadable(project, capsys):
    tabs = ls_registry_tabs()
    tabs["worker_4"] = {"name": "Worker 4", "tab_id": "tb4", "terminal_id": "t4",
                        "pane_id": "p4", "app": "pi", "pid": 700,
                        "session_id": None}
    write_registry(project, tabs=tabs)
    project.state.write_text(json.dumps(
        {"spaces": [], "calls": [], "ls_fails": True}))

    assert project.module.ls() == 1

    captured = capsys.readouterr()
    rows = ls_rows(captured.out)
    assert len(rows) == 5
    assert all("unknown" in row for row in rows)
    assert all("the live workspace could not be read" in row for row in rows)
    assert "[torcha] 5 declared · 5 adopted · ? alive" in captured.out
    assert "herdr-app returned code 1" in captured.err


def test_ls_is_registered_with_the_shared_project_option(project):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC_DIR), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    helped = subprocess.run([sys.executable, "-m", "torcha", "ls", "--help"],
                            cwd=project.root, env=env,
                            capture_output=True, text=True)
    text = " ".join(helped.stdout.split())   # el ancho de línea no importa
    assert helped.returncode == 0
    assert "--json" in text
    assert "--project" in text
    listed = subprocess.run([sys.executable, "-m", "torcha", "--help"],
                            cwd=project.root, env=env,
                            capture_output=True, text=True)
    assert listed.returncode == 0
    assert ("List the declared team against the live workspace."
            in " ".join(listed.stdout.split()))

    write_registry(project, tabs=ls_registry_tabs())
    seed_live(project, ls_live_tabs())
    result = subprocess.run(
        [sys.executable, "-m", "torcha", "ls", "--json",
         "--project", str(project.root)],
        cwd=project.root, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert json.loads(result.stdout)["summary"] == {
        "declared": 5, "adopted": 4, "alive": 1}


def test_status_keeps_reading_only_the_registry(project, capsys):
    """ls adds the declared team; status keeps comparing the registry alone."""
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])

    assert project.module.status(as_json=True) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [role["role"] for role in payload["roles"]] == ["orchestrator"]
    assert payload["summary"] == {"total": 1, "alive": 1, "diverged": False}


def test_ls_reports_a_space_the_registry_remembers_but_herdr_lost(project, capsys):
    """The space is missing, so the roles are: it says which space and exits 0.

    Ruling on that divergence is `status`'s job; `ls` only has to avoid claiming
    the project never had a space.
    """
    write_registry(project, space="sp-gone", tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
        "pane_id": "p1", "app": "pi", "pid": 500,
        "session_id": "01a1f453-0174-7369"}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)],
              space="sp-other")

    assert project.module.ls() == 0

    out = capsys.readouterr().out
    assert "[torcha] Space sp-gone is no longer in Herdr." in out
    assert "the space no longer exists" in out
    assert "[torcha] 5 declared · 1 adopted · 0 alive" in out


# --- recover: catch up without replacing the session -------------------------


def recover_registry(project):
    """Two roles: one running, one whose terminal no longer holds an agent."""
    write_registry(project, tabs={
        "orchestrator": {"name": "Orquestador", "tab_id": "tb1", "terminal_id": "t1",
                         "pane_id": "p1", "app": "pi", "pid": 500,
                         "session_id": "11111111-1111-4111-8111-111111111111"},
        "worker_1": {"name": "Worker 1", "tab_id": "tb2", "terminal_id": "t2",
                     "pane_id": "p2", "app": None, "pid": None, "session_id": None},
    })


def registry_bytes(project):
    return (project.root / ".torcha" / "registry.json").read_bytes()


def sent(project):
    """What the fake herdr-core accepted as text for a terminal."""
    return project.read_state().get("hc_sent", [])


def catch_up_text(project, **overrides):
    """The catch-up as the command renders it, with every field it names."""
    fields = {"project": "proj", "key": "orchestrator", "name": "Orquestador"}
    fields.update(overrides)
    return project.module.recover_module.CATCH_UP.format(**fields)


def test_recover_sends_a_catch_up_to_the_running_agent(project):
    """The effect, not the shape: one message, nothing touched, no tab moved."""
    recover_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    before = registry_bytes(project)

    assert project.module.recover("orchestrator") == 0

    # Llega texto al agente vivo, y ese texto es el del catch-up de su rol.
    assert [address for address, _ in sent(project)] == ["t1"]
    text = sent(project)[0][1]
    assert ".torcha/handoffs/orchestrator/" in text
    assert "git rev-parse HEAD" in text

    # Nada más se toca: ni tab, ni sesión, ni registro, ni handoff.
    assert project.commands() == []
    assert registry_bytes(project) == before
    assert not (project.root / ".torcha" / "handoffs").exists()


def test_recover_refuses_a_role_that_is_not_in_the_registry(project, capsys):
    recover_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    before = registry_bytes(project)

    assert project.module.recover("ghost") == 1

    assert "There is no role 'ghost' in the registry" in capsys.readouterr().err
    assert sent(project) == []
    assert registry_bytes(project) == before


def test_recover_refuses_a_role_with_no_running_agent(project, capsys):
    """No agent in that terminal: nothing is typed and `start` is the way forward."""
    recover_registry(project)
    seed_live(project, [live_tab("tb2", "Worker 1", "t2", app=None)])

    assert project.module.recover("worker_1") == 1

    err = capsys.readouterr().err
    assert "no agent is running" in err
    assert "torcha start worker_1" in err
    assert sent(project) == []
    assert project.commands() == []


def test_recover_refuses_the_terminal_running_the_command(project, monkeypatch,
                                                         capsys):
    recover_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    monkeypatch.setattr(project.module.recover_module, "runs_inside",
                        lambda terminal: True)

    assert project.module.recover("orchestrator") == 1

    assert ("that terminal is the one running this command"
            in capsys.readouterr().err)
    assert sent(project) == []


def test_the_catch_up_message_is_its_own_text(project):
    """Neither the launch bootstrap (confirm who you are) nor the relevo (write a handoff)."""
    text = catch_up_text(project)

    # Lo que un agente ya en marcha necesita leer.
    assert ".torcha/handoffs/orchestrator/" in text
    assert "git rev-parse HEAD" in text
    assert "the tree is the source of truth" in text
    assert "mem_search" in text
    assert "what is done" in text and "what is pending" in text
    assert "contradicts" in text
    assert "do not restart" in text

    # Ni el arranque, ni el relevo.
    assert text != project.module.bootstrap_text(TABS[0], "recover")
    assert text != project.module.handoff_command.RELEVO.format(path="/x.json")
    assert "READY" not in text
    assert "Confirm your identity" not in text
    assert "wait for instructions" not in text
    assert "Fill in the handoff" not in text


def test_recover_refuses_a_terminal_that_now_lives_in_another_tab(project, capsys):
    """A terminal running the right executable is not enough: the id can carry
    another role's tab, and this role's handoff path would go to a stranger.
    """
    recover_registry(project)
    seed_live(project, [live_tab("tb9", "Worker 1", "t1", pid=500)])
    before = registry_bytes(project)

    assert project.module.recover("orchestrator") == 1

    err = capsys.readouterr().err
    assert "tb1" in err and "tb9" in err
    assert "now lives in tab" in err
    assert "torcha start orchestrator" in err
    assert sent(project) == []
    assert registry_bytes(project) == before


def test_recover_warns_about_a_renamed_tab_and_still_sends(project, capsys):
    """Renombrar la tab no cambia quién está dentro: se avisa y se envía."""
    recover_registry(project)
    seed_live(project, [live_tab("tb1", "Another name", "t1", pid=500)])

    assert project.module.recover("orchestrator") == 0

    err = capsys.readouterr().err
    assert "Another name" in err and "Orquestador" in err
    assert "torcha start orchestrator" in err
    assert [address for address, _ in sent(project)] == ["t1"]


def test_recover_refuses_an_entry_with_no_terminal(project, capsys):
    """No terminal id: nothing to prove, so nothing is sent and `start` is the way."""
    write_registry(project, tabs={"orchestrator": {
        "name": "Orquestador", "tab_id": "tb1", "terminal_id": None,
        "pane_id": None, "app": None, "pid": None, "session_id": None}})
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    before = registry_bytes(project)

    assert project.module.recover("orchestrator") == 1

    err = capsys.readouterr().err
    assert "the registry has no terminal" in err
    assert "torcha start orchestrator" in err
    assert sent(project) == []
    assert registry_bytes(project) == before


def test_recover_fails_when_herdr_core_refuses_the_send(project, capsys):
    """A refusal is a failure, never a silent success."""
    recover_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    state = project.read_state()
    state["hc_send_fails"] = True
    project.state.write_text(json.dumps(state))

    assert project.module.recover("orchestrator") == 1

    captured = capsys.readouterr()
    assert "did not accept the send" in captured.err
    assert "t1" in captured.err
    assert "sent to its running session" not in captured.out
    assert sent(project) == []


def test_recover_reports_a_mid_turn_agent_as_queued(project, capsys):
    """The message is sent, but the human is not told the agent has answered."""
    recover_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    state = project.read_state()
    state["spaces"][0]["tabs"][0]["terminals"][0]["status"] = "working"
    project.state.write_text(json.dumps(state))

    assert project.module.recover("orchestrator") == 0

    captured = capsys.readouterr()
    assert "the agent is working" in captured.err
    assert "queues behind its current turn" in captured.err
    assert "not been answered" in captured.err
    # El mensaje viaja igual: el agente lo lee al terminar su turno.
    assert len(sent(project)) == 1
    assert ".torcha/handoffs/orchestrator/" in sent(project)[0][1]


def test_the_catch_up_says_what_to_do_without_a_handoff_or_engram(project):
    """No instruction the agent cannot satisfy: both empty cases say so and continue."""
    text = catch_up_text(project)

    assert text.count("say so and continue") == 2
    assert "If there is none" in text        # no handoff for this role
    assert "If there is nothing" in text     # nothing in Engram for this role


def test_the_catch_up_names_the_project_and_the_role(project):
    text = catch_up_text(project)

    assert "`proj`" in text
    assert "Orquestador" in text and "`orchestrator`" in text
    # "The most recent file" is ambiguous: newest by modification time.
    assert "by modification time" in text
    # No pide releer el proyecto entero y a la vez leer el árbol.
    assert "read the working tree" not in text
    assert "do not re-read" in text
    # Ni vocabulario de escritura de handoff (`keys`, `sha`).
    assert "sha" not in text
    assert "keys" not in text
    assert "Do not write a handoff" in text


def test_recover_is_registered_with_its_help_line(project):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC_DIR), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    helped = subprocess.run([sys.executable, "-m", "torcha", "recover", "--help"],
                            cwd=project.root, env=env,
                            capture_output=True, text=True)
    text = " ".join(helped.stdout.split())   # el ancho de línea no importa
    assert helped.returncode == 0
    assert "role" in text
    assert "--project" in text

    listed = subprocess.run([sys.executable, "-m", "torcha", "--help"],
                            cwd=project.root, env=env,
                            capture_output=True, text=True)
    assert listed.returncode == 0
    assert ("Ask a running agent to catch up without replacing its session."
            in " ".join(listed.stdout.split()))


# --- migrating the runtime data directory -----------------------------------


def run_cli(project, *args):
    """The real entry point, with `--project` applied before the subcommand."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC_DIR), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "torcha", "--project", str(project.root), *args],
        cwd=project.root, env=env, capture_output=True, text=True)


def snapshot_tree(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def make_old_layout(project):
    """The data of an adopted project, under the old directory name."""
    data = project.root / ".torcha"
    write_registry(project)
    (data / "bootstrap").mkdir(exist_ok=True)
    (data / "bootstrap" / "orchestrator.md").write_text("Bootstrap text.\n")
    (data / "handoffs").mkdir(exist_ok=True)
    (data / "handoffs" / "2026-11-25.md").write_text("# Handoff\n")
    legacy = project.root / ".agentorch"
    data.rename(legacy)
    return legacy


def test_migrate_copies_and_verifies_the_old_data_directory(project):
    legacy = make_old_layout(project)
    original = snapshot_tree(legacy)

    result = run_cli(project, "migrate")

    assert result.returncode == 0, result.stderr
    current = project.root / ".torcha"
    assert snapshot_tree(legacy) == original        # copy, never move
    assert snapshot_tree(current) == original
    assert f"Copied {len(original)} file(s)" in result.stdout
    for name in original:
        assert name in result.stdout
    assert "Verified the copy" in result.stdout
    assert "agents.json" in result.stdout and "registry.json" in result.stdout


def test_migrate_says_there_is_nothing_to_do_when_the_data_is_already_there(
        project):
    current = project.root / ".torcha"
    before = snapshot_tree(current)

    result = run_cli(project, "migrate")

    assert result.returncode == 0, result.stderr
    assert "Nothing to migrate" in result.stdout
    assert snapshot_tree(current) == before
    assert not (project.root / ".agentorch").exists()


def test_migrate_refuses_to_guess_when_both_directories_exist(project):
    current = project.root / ".torcha"
    legacy = project.root / ".agentorch"
    legacy.mkdir()
    (legacy / "agents.json").write_text((current / "agents.json").read_text())
    before_legacy = snapshot_tree(legacy)
    before_current = snapshot_tree(current)

    result = run_cli(project, "migrate")

    assert result.returncode == 1
    assert "refusing to guess" in result.stderr
    assert str(legacy) in result.stderr and str(current) in result.stderr
    assert snapshot_tree(legacy) == before_legacy
    assert snapshot_tree(current) == before_current


@pytest.mark.parametrize("args", [
    ("init", "--plain"), ("discover",), ("status",), ("ls",), ("doctor",),
    ("start",), ("recover", "orchestrator"),
    ("rename", "orchestrator", "New name"), ("templates",),
    ("handoff", "validate", "handoff.md"), ("handoff", "run"),
])
def test_every_other_command_refuses_an_unmigrated_project(project, args):
    legacy = make_old_layout(project)

    result = run_cli(project, *args)

    assert result.returncode == 1, result.stdout
    assert "torcha migrate" in result.stderr
    assert str(legacy) in result.stderr
    assert not (project.root / ".torcha").exists()   # never migrates on its own


def test_init_still_works_in_a_project_with_neither_directory(project):
    (project.root / ".torcha").rename(project.root / "saved-config")

    result = run_cli(project, "init", "--plain")

    assert result.returncode == 0, result.stderr
    assert (project.root / ".torcha" / "agents.json").exists()
    assert not (project.root / ".agentorch").exists()


def test_the_readme_tells_an_old_project_to_run_migrate():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8")
    assert "torcha migrate" in readme


# --- the command line reference --------------------------------------------

CLI_DOC = Path(__file__).resolve().parent.parent / "docs" / "cli.md"
# A command section is `## `torcha start``; the shared sections have no
# backticks and are not compared with the parsers.
COMMAND_HEADING = re.compile(r"^## `(torcha(?: [^`]*)?)`\s*$")


def parsers_from_the_cli():
    """Every parser `torcha.cli` defines: the root, then each subcommand.

    The parsers come from the module itself, not from the `--help` text it
    renders, so the test states the contract and not one formatting of it.
    `main()` is the only place the tree is built, so its single `parse_args()`
    call is intercepted before anything is resolved or executed.
    """
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    import argparse
    import torcha.cli as cli

    captured = {}

    class Intercepted(Exception):
        pass

    def intercept(self, args=None, namespace=None):
        captured.setdefault("root", self)
        raise Intercepted

    original = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = intercept
    try:
        with pytest.raises(Intercepted):
            cli.main()
    finally:
        argparse.ArgumentParser.parse_args = original

    found = []

    def walk(parser, path):
        found.append((path, parser))
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    walk(child, f"{path} {name}")

    walk(captured["root"], "torcha")
    return found


def interface_of(parser):
    """The options and positionals one parser defines, `-h`/`--help` aside."""
    import argparse
    names = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        names.append(max(action.option_strings, key=len)
                     if action.option_strings else action.dest)
    return names


def documented_sections():
    """The command sections of docs/cli.md, in document order."""
    sections = []
    body = None
    for line in CLI_DOC.read_text(encoding="utf-8").splitlines():
        heading = COMMAND_HEADING.match(line)
        if heading:
            body = []
            sections.append((heading.group(1), body))
        elif line.startswith("## "):
            body = None
        elif body is not None:
            body.append(line)
    return [(path, "\n".join(lines)) for path, lines in sections]


def documented_names(body):
    """The names in the `### Arguments and options` table of one section."""
    names, inside = [], False
    for line in body.splitlines():
        if line.startswith("### "):
            inside = line.strip().lower() == "### arguments and options"
            continue
        if not inside or not line.startswith("|"):
            continue
        cell = line.split("|")[1].strip()
        found = re.fullmatch(r"`([^`]+)`", cell)
        if found:
            names.append(found.group(1).strip())
    return names


def documented_usage(body):
    """The `usage:` line of one section, with its wrapping neutralised."""
    line = next((line for line in body.splitlines()
                 if line.strip().startswith("usage: ")), None)
    return " ".join(line.split()) if line else None


def test_every_option_and_subcommand_is_in_the_documented_contract():
    parsed = parsers_from_the_cli()
    documented = documented_sections()
    bodies = dict(documented)
    order = [path for path, _ in documented]
    expected = [path for path, _ in parsed]

    problems = []
    for path, parser in parsed:
        body = bodies.get(path)
        if body is None:
            problems.append(f"{path}: the parser defines it and docs/cli.md "
                            "has no section for it")
            continue
        names = interface_of(parser)
        written = documented_names(body)
        for name in names:
            if name not in written:
                problems.append(f"{path}: {name!r} is an option of the parser "
                                "and docs/cli.md does not document it")
        for name in written:
            if name not in names:
                problems.append(f"{path}: docs/cli.md documents {name!r} and "
                                "the parser does not define it")
        usage = documented_usage(body)
        real = " ".join(parser.format_usage().split())
        if usage != real:
            problems.append(f"{path}: docs/cli.md states the usage as "
                            f"{usage!r} and the parser prints {real!r}")
    for path in order:
        if path not in expected:
            problems.append(f"docs/cli.md documents {path!r}, which the "
                            "parsers do not define")
    if order != expected:
        problems.append("docs/cli.md documents the commands in this order: "
                        f"{order}; the top-level help lists them as {expected}")

    assert not problems, "\n".join(problems)


def test_init_reports_a_named_tab_without_an_agent_even_with_the_config_written(
        project, capsys):
    """Con la config completa no hay entrevista: era la ruta que callaba."""
    (project.root / ".torcha").mkdir(parents=True, exist_ok=True)
    (project.root / ".torcha/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Coordinates.", "instructions": "Do not push."}],
    }))
    # El space tiene que emparejar por carpeta, o `init` crea uno nuevo y nunca
    # llega al camino de reconciliación que este test describe.
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": str(project.root), "active": True,
        "tabs": [
            {"id": "tb1", "name": "Orquestador", "active": True,
             "terminals": [{"terminal": "t1", "pane": "p1",
                            "cwd": str(project.root), "app": "pi",
                            "status": "idle", "pid": 500}]},
            {"id": "tb2", "name": "Extra", "active": False,
             "terminals": [{"terminal": "t2", "pane": "p2",
                            "cwd": str(project.root), "app": None,
                            "status": None, "pid": None}]},
        ]}], "calls": []}))

    assert project.module.init(plain=True) == 0

    reported = [line for line in capsys.readouterr().err.splitlines()
                if "no agent running" in line]
    assert len(reported) == 1
    assert "Extra" in reported[0]


# --- el paquete -------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_the_wheel_carries_the_files_a_launch_depends_on(tmp_path):
    """Cada arranque pasa `--skill <paquete>/skills/...`: si no viaja, no arranca.

    El modo editable lee el árbol de fuentes y esconde el fallo; esto construye
    el paquete de verdad y mira dentro.
    """
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed: a wheel cannot be built here")

    result = subprocess.run([uv, "build", "--wheel", "--out-dir", str(tmp_path), "."],
                            cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    wheel = next(tmp_path.glob("*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())
    for expected in ("torcha/skills/torcha/SKILL.md",
                     "torcha/skills/setup/SKILL.md",
                     "torcha/templates/software-team.json"):
        assert expected in names, f"{expected} is missing from the wheel"


def test_two_handoffs_written_at_the_same_instant_have_a_stable_winner(
        project):
    """El "más reciente" no puede depender del orden del sistema de ficheros.

    Dos documentos con la misma marca de tiempo eligen siempre el mismo, aquí y
    en cualquier versión de Python: el nombre desempata.
    """
    directory = project.root / ".torcha" / "handoffs" / "orchestrator"
    directory.mkdir(parents=True)
    for name in ("zzz.json", "aaa.json"):
        path = directory / name
        path.write_text(json.dumps({"status": "prepared", "objective": name}))
        os.utime(path, ns=(1_700_000_000_000_000_000,) * 2)

    chosen = project.module.handoff.newest_handoff("orchestrator")

    assert chosen is not None and chosen.name == "zzz.json"
