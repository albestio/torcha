"""Regression tests for agentorch v0.3.0 (S1-S6). No Herdr is touched: run_app is faked."""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE_SRC = REPO / ".agentorch" / "agentorch.py"
CONFIG_SRC = REPO / ".agentorch" / "agents.json"


def load_project(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".agentorch").mkdir(parents=True)
    shutil.copy(MODULE_SRC, proj / ".agentorch" / "agentorch.py")
    shutil.copy(CONFIG_SRC, proj / ".agentorch" / "agents.json")
    spec = importlib.util.spec_from_file_location(
        "agentorch_under_test", proj / ".agentorch" / "agentorch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, proj


class FakeHerdr:
    """Minimal herdr-app: `ls` returns spaces[].tabs[].terminals[].pane/app."""

    def __init__(self):
        self.spaces = []
        self.calls = []
        self.focus = None
        self.counter = 0
        self.report_apps = True
        self.hide_space = False

    def _tab(self, name, folder, argv):
        self.counter += 1
        argv = json.loads(argv) if argv else None
        existed = None
        if argv and argv[1].startswith("@"):
            existed = (Path(folder) / argv[1][1:]).exists()
        return {"id": f"tb{self.counter}", "name": name, "argv": argv,
                "bootstrap_existed": existed,
                "terminals": [{"id": f"t{self.counter}", "pane": f"p{self.counter}",
                               "cwd": folder, "app": None}]}

    def __call__(self, args, allow_error=False):
        self.calls.append(list(args))
        if args == ["ls"]:
            if self.hide_space:
                return json.dumps({"spaces": []})
            if self.report_apps:
                for space in self.spaces:
                    for tab in space["tabs"]:
                        if tab.get("argv"):
                            for term in tab["terminals"]:
                                term["app"] = tab["argv"][0]
            return json.dumps({"spaces": self.spaces})
        rest = args[2:]
        opts = {}
        i = 0
        while i < len(rest):
            if rest[i].startswith("--"):
                opts[rest[i][2:]] = rest[i + 1]
                i += 2
            else:
                i += 1
        sub = args[1]
        if sub == "space.new":
            self.spaces = [{"id": "sp", "folder": opts["folder"],
                            "tabs": [self._tab(opts["tab"], opts["folder"], opts.get("argv"))]}]
            return json.dumps({"space": "sp"})
        space = self.spaces[0]
        if sub == "tab.new":
            space["tabs"].append(self._tab(opts["name"], opts["folder"], opts.get("argv")))
            return json.dumps({"tab": space["tabs"][-1]["id"]})
        if sub == "tab.move":
            tab = next(t for t in space["tabs"] if t["id"] == opts["id"])
            space["tabs"].remove(tab)
            space["tabs"].insert(int(opts["index"]) - 1, tab)
            return json.dumps({"ok": True})
        if sub in ("space.select", "tab.select"):
            self.focus = opts["id"]
            return json.dumps({"ok": True})
        return json.dumps({"ok": True})

    def created(self):
        return [c for c in self.calls
                if c[:2] in (["do", "space.new"], ["do", "tab.new"])]

    def tab(self, name):
        return next(t for t in self.spaces[0]["tabs"] if t["name"] == name)


def registry(proj):
    return json.loads((proj / ".agentorch" / "registry.json").read_text())


@pytest.fixture()
def project(tmp_path, monkeypatch):
    mod, proj = load_project(tmp_path)
    fake = FakeHerdr()
    monkeypatch.setattr(mod, "run_app", fake)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    return mod, proj, fake


def test_s1_focus_first_tab_new_space(project):
    mod, proj, fake = project
    assert mod.init() == 0
    orchestrator = registry(proj)["herdr"]["tabs"]["orchestrator"]["tab_id"]
    assert fake.focus == orchestrator
    selects = [c for c in fake.calls if c[:2] == ["do", "tab.select"]]
    assert len(selects) == 1 and selects[0][3] == orchestrator
    new_tabs = [c for c in fake.calls if c[:2] == ["do", "tab.new"]]
    assert new_tabs and all(c[c.index("--focus") + 1] == "false" for c in new_tabs)


def test_s1_focus_first_tab_existing_space(project):
    mod, proj, fake = project
    assert mod.init() == 0
    before = len(fake.created())
    assert mod.init() == 0
    orchestrator = registry(proj)["herdr"]["tabs"]["orchestrator"]["tab_id"]
    assert len(fake.created()) == before
    assert fake.focus == orchestrator


def test_s2_created_tabs_start_pi_with_bootstrap_file(project):
    mod, proj, fake = project
    assert mod.init() == 0
    config = json.loads((proj / ".agentorch" / "agents.json").read_text())
    created = fake.created()
    assert len(created) == len(config["tabs"])
    for call, item in zip(created, config["tabs"]):
        argv = json.loads(call[call.index("--argv") + 1])
        assert argv == ["pi", f"@.agentorch/bootstrap/{item['key']}.md"]
    assert all(fake.tab(item["name"])["bootstrap_existed"] is True for item in config["tabs"])
    # the bootstrap file precedes every creation: it is written before any herdr call
    assert fake.calls[0][:2] == ["do", "space.new"] or fake.calls[0] == ["ls"]


def test_s3_idempotent_second_run(project):
    mod, proj, fake = project
    assert mod.init() == 0
    names_before = [t["name"] for t in fake.spaces[0]["tabs"]]
    assert mod.init() == 0
    names_after = [t["name"] for t in fake.spaces[0]["tabs"]]
    assert names_before == names_after
    assert len(fake.created()) == len(names_after)


def test_s4_bootstrap_files_deterministic(project):
    mod, proj, fake = project
    assert mod.init() == 0
    bdir = proj / ".agentorch" / "bootstrap"
    files = sorted(p.name for p in bdir.iterdir())
    config = json.loads((proj / ".agentorch" / "agents.json").read_text())
    assert files == sorted(f"{t['key']}.md" for t in config["tabs"])
    text = (bdir / "orchestrator.md").read_text()
    item = config["tabs"][0]
    assert item["name"] in text and item["key"] in text and item["role"] in text
    assert "## Instructions" not in text
    first = {p.name: p.read_bytes() for p in bdir.iterdir()}
    assert mod.init() == 0
    assert first == {p.name: p.read_bytes() for p in bdir.iterdir()}


def test_s4_instructions_section(project):
    mod, proj, fake = project
    cfg = json.loads((proj / ".agentorch" / "agents.json").read_text())
    cfg["tabs"][1]["instructions"] = "Read docs first.\nNever push."
    (proj / ".agentorch" / "agents.json").write_text(json.dumps(cfg))
    assert mod.init() == 0
    name = cfg["tabs"][1]["key"] + ".md"
    text = (proj / ".agentorch" / "bootstrap" / name).read_text()
    assert "## Instructions" in text and "Never push." in text
    assert "## Instructions" not in (proj / ".agentorch" / "bootstrap" / "orchestrator.md").read_text()


def test_s5_pane_and_s6_app_recorded(project):
    mod, proj, fake = project
    assert mod.init() == 0
    tabs = registry(proj)["herdr"]["tabs"]
    for key, entry in tabs.items():
        assert entry["pane_id"] == fake.tab(entry["name"])["terminals"][0]["pane"]
        assert entry["pane_id"] is not None
        assert entry["app"] == "pi"


def test_s6_wait_for_apps_raises_when_space_missing(project):
    mod, proj, fake = project
    fake.hide_space = True
    with pytest.raises(mod.AgentorchError):
        mod.wait_for_apps("sp", ["Orquestador"], timeout=0, interval=0)


def test_s6_wait_for_apps_returns_pending_without_spinning(project):
    mod, proj, fake = project
    assert mod.init() == 0
    for tab in fake.spaces[0]["tabs"]:
        tab["terminals"][0]["app"] = None
    fake.report_apps = False
    space, pending = mod.wait_for_apps("sp", ["Orquestador"], timeout=0, interval=0)
    assert pending == ["Orquestador"] and space["id"] == "sp"


def test_s6_extract_tab_ids_reads_terminals_pane(tmp_path):
    mod, proj = load_project(tmp_path)
    tab = {"id": "tb1", "name": "x",
           "terminals": [{"id": "t1", "pane": "p1", "app": "pi"}]}
    assert mod.extract_tab_ids(tab) == {"terminal_id": "t1", "pane_id": "p1"}
    assert mod.tab_app(tab) == "pi"
