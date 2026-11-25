"""Tests for src/agentorch.py.

The suite never talks to a real Herdr window. A fake `herdr-app` is placed on
PATH and keeps its state in a JSON file, so every assertion is about what the
tool asked Herdr to do and what it wrote to the registry.

Run with: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC_DIR = Path(os.environ.get(
    "AGENTORCH_SRC",
    str(Path(__file__).resolve().parent.parent / "src"),
))

TABS = [
    {"key": "orchestrator", "name": "Orquestador", "role": "Coordina."},
    {"key": "worker_1", "name": "Worker 1", "role": "Investiga."},
    {"key": "worker_2", "name": "Worker 2", "role": "Implementa."},
    {"key": "worker_3", "name": "Worker 3", "role": "Revisa."},
    {"key": "worker_4", "name": "Worker 4", "role": "Prueba."},
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
    for name in [n for n in list(sys.modules) if n == "agentorch" or n.startswith("agentorch.")]:
        del sys.modules[name]

    import agentorch.bootstrap
    import agentorch.commands.discover
    import agentorch.commands.doctor
    import agentorch.commands.handoff
    import agentorch.commands.init
    import agentorch.commands.rename
    import agentorch.commands.start
    import agentorch.commands.status
    import agentorch.commands.templates
    import agentorch.templates
    import agentorch.config
    import agentorch.discovery
    import agentorch.errors
    import agentorch.git
    import agentorch.herdr
    import agentorch.live
    import agentorch.project

    return SimpleNamespace(
        init=agentorch.commands.init.init,
        AgentorchError=agentorch.errors.AgentorchError,
        load_config=agentorch.config.load_config,
        parse_bootstrap=agentorch.config.parse_bootstrap,
        bootstrap_text=agentorch.bootstrap.bootstrap_text,
        extract_tab_ids=agentorch.herdr.extract_tab_ids,
        tab_app=agentorch.herdr.tab_app,
        get_spaces=agentorch.herdr.get_spaces,
        time=agentorch.herdr.time,
        sys=agentorch.git.sys,
        paths=agentorch.project,
        discovery=agentorch.discovery,
        live=agentorch.live,
        discover=agentorch.commands.discover.discover,
        config=agentorch.config,
        herdr=agentorch.herdr,
        init_module=agentorch.commands.init,
        status=agentorch.commands.status.status,
        handoff=agentorch.handoff,
        handoff_command=agentorch.commands.handoff,
        start=agentorch.commands.start.start,
        rename=agentorch.commands.rename.rename,
        templates=agentorch.templates,
        templates_command=agentorch.commands.templates.templates,
        doctor=agentorch.commands.doctor.doctor,
        doctor_module=agentorch.commands.doctor,
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
        return json.loads((self.root / ".agentorch" / "registry.json").read_text())

    def bootstrap(self, key):
        return (self.root / ".agentorch" / "bootstrap" / f"{key}.md").read_text()


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
    agentorch_dir = root / ".agentorch"
    monkeypatch.setattr(module.paths, "PROJECT_DIR", root)
    monkeypatch.setattr(module.paths, "PROJECT_NAME", root.name)
    monkeypatch.setattr(module.paths, "AGENTORCH_DIR", agentorch_dir)
    monkeypatch.setattr(module.paths, "CONFIG_FILE", agentorch_dir / "agents.json")
    monkeypatch.setattr(module.paths, "REGISTRY_FILE", agentorch_dir / "registry.json")
    monkeypatch.setattr(module.paths, "BOOTSTRAP_DIR", agentorch_dir / "bootstrap")

    agentorch_dir.mkdir(parents=True, exist_ok=True)
    (agentorch_dir / "agents.json").write_text(
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
    with pytest.raises(project.module.AgentorchError, match="pi.bootstrap"):
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
    assert ".agentorch/handoffs/orchestrator/" in text
    assert "git rev-parse HEAD" in text
    assert "mem_search" in text
    assert "READY" in text
    # El handoff y su validación contra el repo van antes que Engram.
    assert text.index("handoffs/orchestrator") < text.index("mem_search")
    assert text.index("git rev-parse HEAD") < text.index("mem_search")


def test_config_rejects_pi_executable_with_arguments(project):
    (project.root / ".agentorch" / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi --model x"}, "tabs": TABS}))
    with pytest.raises(project.module.AgentorchError, match="pi.executable"):
        project.module.load_config()


@pytest.mark.parametrize("value", [0, -1, "ten", 2.5, True])
def test_an_invalid_max_tabs_is_refused(project, value):
    """El tope del equipo se lee del proyecto, y se valida: no se ignora."""
    (project.root / ".agentorch" / "agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "max_tabs": value, "tabs": TABS}))

    with pytest.raises(project.module.AgentorchError, match="max_tabs"):
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
        assert argv[1] == "--session-id"
        uuid.UUID(argv[2])
        reference = argv[3]
        assert reference.startswith("@.agentorch/bootstrap/")
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
    """Closing the interview's Pi must not jump away from agentorch's logs."""
    (project.root / ".agentorch/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    def fake_interview(candidates):
        (project.root / ".agentorch/agents.json").write_text(json.dumps({
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
                        lambda candidates: called.setdefault("ran", True))

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
    (project.root / ".agentorch" / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi", "bootstrap": "none"}, "tabs": TABS}))

    assert project.module.init() == 0
    for options in project.options_for("space.new") + project.options_for("tab.new"):
        assert "argv" not in options


# --- the git precondition --------------------------------------------------


def test_init_refuses_to_run_outside_a_repository_without_a_terminal(
        project, tmp_path, monkeypatch):
    # Outside any repository: `tmp_path` is not inside the fixture's repo.
    plain = tmp_path / "outside"
    plain.mkdir()
    monkeypatch.setattr(project.module.paths, "PROJECT_DIR", plain)
    monkeypatch.setattr(project.module.paths, "AGENTORCH_DIR", plain / ".agentorch")
    monkeypatch.setattr(project.module.paths, "CONFIG_FILE", plain / ".agentorch" / "agents.json")
    monkeypatch.setattr(project.module.paths, "REGISTRY_FILE", plain / ".agentorch" / "registry.json")
    monkeypatch.setattr(project.module.paths, "BOOTSTRAP_DIR", plain / ".agentorch" / "bootstrap")
    monkeypatch.setattr(project.module.sys.stdin, "isatty", lambda: False)

    with pytest.raises(project.module.AgentorchError,
                       match="is not a git repository"):
        project.module.init()

    # Nothing was created and Herdr was never called.
    assert not (plain / ".agentorch").exists()
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
    (project.root / ".agentorch/agents.json").unlink()
    write_agent(project.root / ".pi/agents/lead.md", "lead", "Orchestrates the team.")
    write_agent(project.root / ".pi/agents/builder.md", "builder", "Implements changes.")

    assert project.module.init() == 0

    config = json.loads((project.root / ".agentorch/agents.json").read_text())
    assert [tab["key"] for tab in config["tabs"]] == ["orchestrator", "builder"]
    assert config["tabs"][0]["name"] == "Orchestrator"


def test_init_seeds_the_config_from_named_tabs_with_sessions_first(project):
    """The team in use beats the catalogue: named live tabs win, active first."""
    (project.root / ".agentorch/agents.json").unlink()
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

    config = json.loads((project.root / ".agentorch/agents.json").read_text())
    assert [tab["name"] for tab in config["tabs"]] == ["Orchestrator", "Builder", "Idle"]
    # Nothing was created: the named live tabs were reused.
    assert project.commands().count("tab.new") == 0


def test_init_reuses_a_live_orchestrator_named_lead(project):
    """Role names in the config must not duplicate a live tab called "Lead"."""
    (project.root / ".agentorch/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": str(project.root), "active": True,
        "tabs": [{"id": "tb1", "name": "Lead", "active": True,
                  "terminals": [{"terminal": "t1", "pane": "p1",
                                 "cwd": str(project.root), "app": "pi",
                                 "status": "idle"}]}],
    }], "calls": []}))

    assert project.module.init() == 0

    config = json.loads((project.root / ".agentorch/agents.json").read_text())
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
    assert argv[2] == worker                               # el mismo que se lanzó


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
    (project.root / ".agentorch" / "registry.json").write_text(json.dumps(payload))
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
    (project.root / ".agentorch" / "registry.json").unlink(missing_ok=True)
    seed_live(project, [])

    with pytest.raises(project.module.AgentorchError, match="registry"):
        project.module.status()


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
        "files_touched": [{"path": "src/agentorch/handoff.py",
                           "reason": "new module"}],
        "decisions": ["the handoff is JSON, not YAML"],
        "blockers": [],
        "validation": {"commands_run": ["pytest"], "results": ["77 passed"]},
        "git": {"branch": "main", "head": "a" * 40, "status_summary": "clean"},
        "engram_refs": ["agentorch/handoff/orchestrator"],
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
    inside = project.root / ".agentorch" / "handoffs" / "orchestrator"
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


def created_tab(project, name):
    """La tab que el fake acaba de crear, tal como la reporta `ls`."""
    for space in project.read_state()["spaces"]:
        for tab in space["tabs"]:
            if tab["name"] == name:
                return tab
    return None


def test_start_resumes_the_registry_session(project):
    start_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(timeout=0.5, interval=0.01) == 0

    assert "hc_sent" not in project.read_state()          # no se teclea nada
    assert [opts["id"] for opts in project.options_for("tab.close")] == ["tb1"]
    created = project.options_for("tab.new")
    assert created and created[0]["name"] == "Orquestador"
    assert created[0]["space"] == "sp01"
    assert created[0]["folder"] == str(project.root)
    assert created[0]["focus"] == "false"
    assert "--session-id" in created[0]["argv"]
    assert SESSION in created[0]["argv"]
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["session_id"] == SESSION
    assert entry["pid"] == created_tab(project, "Orquestador")["terminals"][0]["pid"]


def test_start_fresh_uses_a_new_session_id(project):
    start_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(fresh=True, timeout=0.5, interval=0.01) == 0

    new_id = project.registry()["herdr"]["tabs"]["orchestrator"]["session_id"]
    assert new_id != SESSION
    uuid.UUID(new_id)


def test_start_skips_a_tab_that_already_runs_the_agent(project):
    start_registry(project)
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
    project.state.write_text(json.dumps(
        {"spaces": [a_space_without_the_role(project)], "calls": []}))

    assert project.module.start(timeout=0.2, interval=0.01, recreate=True,
                                fresh=True) == 0
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["session_id"] != SESSION


def test_start_recreate_fresh_reports_a_new_session(project, capsys):
    start_registry(project)
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
    (project.root / ".agentorch" / "agents.json").write_text(
        json.dumps({"pi": {"executable": "pi", "bootstrap": "none"},
                    "tabs": TABS}))
    start_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])

    assert project.module.start(timeout=0.5, interval=0.01) == 0

    assert "hc_sent" not in project.read_state()
    assert project.options_for("tab.close") == []
    assert project.options_for("tab.new") == []


def test_start_only_touches_the_named_role(project):
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
    (project.root / ".agentorch/agents.json").write_text(json.dumps({
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

    text = (project.root / ".agentorch/interview.md").read_text()
    # El sujeto de la entrevista es la única role pendiente, y se dice cuál es.
    assert "The interview covers only these roles, which are still empty: `coach`." \
        in text
    assert "already written by their agents" in text
    assert "touch or rewrite them" in text
    # Y no se afirma que todas estén vacías, porque no lo están.
    assert "Every `role` and `instructions` is empty" not in text


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
    (project.root / ".agentorch/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    report = project.module.init_module.start_interview([])

    # La entrevista sí tomó esta tab, pero no rellenó ninguna role.
    assert report.ran is True
    assert report.pending == ("orchestrator",)
    config = json.loads((project.root / ".agentorch/agents.json").read_text())
    assert config["tabs"][0]["key"] == "orchestrator"
    assert config["tabs"][0]["name"] == "Orquestador"
    assert config["tabs"][0]["role"] == ""


def test_an_unfinished_interview_blocks_init(project):
    (project.root / ".agentorch/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "", "instructions": ""}]}))

    assert project.module.init(plain=True) == 1


def test_init_opens_the_interview_when_live_tabs_exist(project, monkeypatch):
    (project.root / ".agentorch/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    called = {}

    def fake_interview(candidates):
        called["ran"] = True
        (project.root / ".agentorch/agents.json").write_text(json.dumps({
            "pi": {"executable": "pi", "bootstrap": "greet"},
            "tabs": [{"key": "orchestrator", "name": "Orquestador",
                      "role": "Coordinates from the interview."}]}))
        return project.module.init_module.Interview(ran=True)

    monkeypatch.setattr(project.module.init_module, "start_interview", fake_interview)

    assert project.module.init() == 0
    assert called.get("ran") is True
    config = json.loads((project.root / ".agentorch/agents.json").read_text())
    assert config["tabs"][0]["role"] == "Coordinates from the interview."


def test_init_skips_the_interview_with_plain(project, monkeypatch):
    (project.root / ".agentorch/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    called = {}
    monkeypatch.setattr(project.module.init_module, "start_interview",
                        lambda candidates: called.setdefault("ran", True))

    assert project.module.init(plain=True) == 0
    assert "ran" not in called
    assert (project.root / ".agentorch/agents.json").exists()


def test_init_skips_the_interview_without_a_tty(project, monkeypatch):
    (project.root / ".agentorch/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: False)
    called = {}
    monkeypatch.setattr(project.module.init_module, "start_interview",
                        lambda candidates: called.setdefault("ran", True))

    assert project.module.init() == 0
    assert "ran" not in called


def test_a_failed_interview_refuses_to_apply(project, monkeypatch):
    (project.root / ".agentorch/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    def fake_interview(candidates):
        (project.root / ".agentorch/agents.json").write_text(json.dumps({
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
    with pytest.raises(project.module.AgentorchError, match="There is no template"):
        project.module.templates.load("nope")


def test_the_templates_command_lists_it(project, capsys):
    assert project.module.templates_command(as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["templates"][0]["name"] == "software-team"


# --- instructions and launch safety ----------------------------------------


def test_instructions_accepts_a_list_of_bullets(project):
    (project.root / ".agentorch/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Coordinates.", "instructions": ["- one", "- two"]}]}))

    config = project.module.load_config()
    assert config["tabs"][0]["instructions"] == "- one\n- two"


def test_instructions_rejects_a_shape_it_cannot_use(project):
    (project.root / ".agentorch/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "tabs": [{"key": "orchestrator", "name": "Orquestador",
                  "role": "Coordinates.", "instructions": 42}]}))

    with pytest.raises(project.module.AgentorchError, match="instructions"):
        project.module.load_config()


def test_the_skill_asks_one_question_at_a_time(project):
    text = project.module.init_module.SETUP_SKILL.read_text(encoding="utf-8")
    assert "One question at a time" in text
    assert "Already waiting for a reply" in text


def test_init_warns_when_launched_inside_a_team_tab(project, monkeypatch, capsys):
    (project.root / ".agentorch/agents.json").unlink()
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
    (project.root / ".agentorch/agents.json").unlink()
    project.state.write_text(json.dumps({"spaces": [
        seeded_space("sp01", "proj", "/wrong", str(project.root), "t01")],
        "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_own_tab",
                        lambda: {"id": "tb-loose", "name": "6"})
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    assert "with the same label" not in capsys.readouterr().err
    renames = project.options_for("tab.rename")
    assert renames and renames[0]["id"] == "tb-loose"
    assert renames[0]["name"] == "Agentorch"


# --- session ids collected by the interview ---------------------------------


def test_the_interview_session_ids_reach_an_adopted_tab(project):
    """A tab init creates gets its own id; one it adopts gets the interviewed one."""
    sid = "11111111-1111-4111-8111-111111111111"
    proposals = project.root / ".agentorch" / "proposals"
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
    proposals = project.root / ".agentorch" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "sessions.json").write_text(json.dumps({"worker_1": sid}))
    project.state.write_text(json.dumps({"spaces": [], "calls": []}))

    assert project.module.init(plain=True) == 0
    assert project.registry()["herdr"]["tabs"]["worker_1"]["session_id"] != sid


def test_ids_written_during_the_interview_are_read_afterwards(project, monkeypatch):
    """The proposals file does not exist until the interview writes it."""
    sid = "33333333-3333-4333-8333-333333333333"
    (project.root / ".agentorch/agents.json").unlink()
    monkeypatch.setattr(project.module.init_module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(project.module.init_module.sys.stdout, "isatty", lambda: True)

    def fake_interview(candidates):
        (project.root / ".agentorch/agents.json").write_text(json.dumps({
            "pi": {"executable": "pi", "bootstrap": "greet"},
            "tabs": [{"key": "orchestrator", "name": "Orquestador",
                      "role": "Coordinates.", "instructions": ""}]}))
        proposals = project.root / ".agentorch" / "proposals"
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
    proposals = project.root / ".agentorch" / "proposals"
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
    assert "an invented id would make `agentorch start` resume" in text


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
    """`git` lo mide agentorch: reescribirlo fue cómo un handoff declaró un sha falso."""
    text = project.module.handoff_command.RELEVO
    assert "`git` is measured by agentorch and must not be edited" in text


def test_handoff_run_writes_and_validates_a_handoff(project, monkeypatch):
    handoff_registry(project)
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", pid=500)])
    fill_on_send(project, monkeypatch)

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01) == 0

    files = list((project.root / ".agentorch" / "handoffs" / "orchestrator").glob("*.json"))
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
    files = list((project.root / ".agentorch" / "handoffs" / "orchestrator").glob("*.json"))
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
    # y el handoff consumido queda marcado: no se reutiliza en el próximo run
    files = list((project.root / ".agentorch" / "handoffs" / "orchestrator").glob("*.json"))
    assert json.loads(files[0].read_text())["status"] == "consumed"
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
    configured = json.loads((project.root / ".agentorch/agents.json").read_text())
    assert configured["pi"]["bootstrap"] == "greet"

    assert project.module.handoff_command.run(role="orchestrator", timeout=0.2,
                                              interval=0.01, swap=True) == 0

    text = project.bootstrap("orchestrator")
    assert "Recovery protocol" in text
    assert "handoffs/orchestrator" in text
    new_argv = json.loads(project.options_for("tab.new")[0]["argv"])
    assert "@.agentorch/bootstrap/orchestrator.md" in new_argv


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


# --- naming the setup tab ---------------------------------------------------


def test_the_setup_tab_is_renamed_when_it_is_not_a_team_tab(project):
    seed_live(project, [live_tab("tb-team", "Orquestador", "t01", pid=500)])

    project.module.init_module._mark_setup_tab(
        {"id": "tb-setup", "name": "1"}, {"tb-team"})

    renames = project.options_for("tab.rename")
    assert renames and renames[0]["id"] == "tb-setup"
    assert renames[0]["name"] == "Agentorch"


def test_a_team_tab_is_never_renamed(project):
    seed_live(project, [live_tab("tb-team", "Orquestador", "t01", pid=500)])

    project.module.init_module._mark_setup_tab(
        {"id": "tb-team", "name": "Orquestador"}, {"tb-team"})

    assert project.options_for("tab.rename") == []


def test_an_unidentifiable_terminal_is_left_alone(project):
    seed_live(project, [])
    project.module.init_module._mark_setup_tab(None, set())
    assert project.options_for("tab.rename") == []


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
    (project.root / ".agentorch" / "agents.json").write_text('{"tabs": []}')

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
    with pytest.raises(project.module.AgentorchError, match="herdr-core"):
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
    registry_file = project.root / ".agentorch" / "registry.json"
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
    tabs.append(role_tab(len(names) + 1, "Agentorch", folder))
    tabs.append({"id": "tb-new", "name": str(len(names) + 2), "active": False,
                 "terminals": [{"terminal": "t-new", "pane": "p-new",
                                "cwd": folder, "app": None, "status": None}]})
    return {"id": "sp01", "name": "proj", "folder": folder, "active": True,
            "tabs": tabs}


def test_the_skeleton_lists_every_named_role_and_never_the_setup_tab(project, monkeypatch):
    """career-ops: six named roles with an agent, the setup tab and an unused "7"."""
    (project.root / ".agentorch/agents.json").unlink()
    project.state.write_text(json.dumps(
        {"spaces": [career_ops_space(str(project.root))], "calls": []}))
    monkeypatch.setattr(project.module.init_module, "_run_interview",
                        lambda path, exe: 0)

    project.module.init_module.start_interview([])

    tabs = json.loads((project.root / ".agentorch/agents.json").read_text())["tabs"]
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
    assert "Agentorch" not in [tab["name"] for tab in proposed]


def test_the_tab_running_the_interview_is_never_a_role(project, monkeypatch):
    (project.root / ".agentorch/agents.json").unlink()
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

    tabs = json.loads((project.root / ".agentorch/agents.json").read_text())["tabs"]
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
    (project.root / ".agentorch/agents.json").write_text(json.dumps({
        "pi": {"executable": "pi", "bootstrap": "greet"},
        "max_tabs": 3, "tabs": TABS}))

    assert project.module.discover(live=True) == 0

    captured = capsys.readouterr()
    assert [tab["name"] for tab in json.loads(captured.out)["tabs"]] == \
        ["Orchestrator", "Scout", "Communicator"]
    cut = next(line for line in captured.err.splitlines() if "leaves out" in line)
    assert "Auditor" in cut and "Coach" in cut
    # La tab de setup queda excluida, no recortada: no se nombra.
    assert "Agentorch" not in cut


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
    assert "agentorch start <role> --recreate" in reported[0]
    assert "by hand" in reported[0]


def test_only_the_named_tab_without_an_agent_is_reported(
        project, monkeypatch, capsys):
    """The setup marker, an unnamed tab and the caller's own tab stay silent."""
    (project.root / ".agentorch/agents.json").unlink()
    folder = str(project.root)
    project.state.write_text(json.dumps({"spaces": [{
        "id": "sp01", "name": "proj", "folder": folder, "active": True,
        "tabs": [role_tab(1, "Senior Orchestrator", folder),
                 role_tab(2, "Coach", folder, app=None),
                 role_tab(3, "Agentorch", folder),
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
    for silent in ("Agentorch", "7", "Scratch"):
        assert silent not in reported[0]


def test_init_reports_a_named_tab_without_an_agent_on_both_paths(
        project, monkeypatch, capsys):
    folder = str(project.root)
    project.state.write_text(json.dumps({
        "spaces": [career_ops_space_with_a_dead_agent(folder)], "calls": []}))
    config = project.root / ".agentorch/agents.json"

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
    seed_live(project, [live_tab("tb1", "Orquestador", "t1", app=None)])
    module = sys.modules[project.module.start.__module__]
    real = module.run_app

    def explode(args):
        if args[:2] == ["do", "tab.new"]:
            raise module.AgentorchError("boom")
        return real(args)

    monkeypatch.setattr(module, "run_app", explode)

    assert project.module.start(timeout=0.5, interval=0.01) == 1
    entry = project.registry()["herdr"]["tabs"]["orchestrator"]
    assert entry["tab_id"] is None
    assert entry["terminal_id"] is None
