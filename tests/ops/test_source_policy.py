import pytest

from llm_localizator.ops.patch import op_patch
from llm_localizator.ops.types import PatchRequest
from llm_localizator.projects import ConfigError, load_config
from tests.synth.factory import build_project


def _cfg(tmp_path, extra=""):
    proj = build_project(tmp_path)
    toml = proj.config_path
    toml.write_text(toml.read_text(encoding="utf-8") + extra, encoding="utf-8")
    cfg = load_config(toml)
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.tsx").write_text("export const A = () => <b>Click here now</b>;\n", encoding="utf-8")
    cfg.scan_adapter, cfg.scan_src_dirs = "source", ["src"]
    return cfg


def test_default_is_patch(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.source_edits == "patch" and cfg.target_branch == "l10n/auto"
    assert op_patch(cfg, PatchRequest()).ok


def test_never_refuses_patch(tmp_path):
    cfg = _cfg(tmp_path, '\n[source_policy]\nsource_edits = "never"\n')
    out = op_patch(cfg, PatchRequest())
    assert not out.ok and "source_policy" in out.summary


def test_agent_branch_adds_task(tmp_path):
    cfg = _cfg(tmp_path, '\n[source_policy]\nsource_edits = "agent-branch"\ntarget_branch = "l10n/bot"\n')
    task = op_patch(cfg, PatchRequest()).data["agent_task"]
    assert task["target_branch_for_translations"] == "l10n/bot"
    assert "src/a.tsx" in task["files"]


def test_bad_value_rejected(tmp_path):
    with pytest.raises(ConfigError):
        _cfg(tmp_path, '\n[source_policy]\nsource_edits = "yolo"\n')


def test_directive_suggestions_for_ignored_hits(monkeypatch):
    from types import SimpleNamespace

    from llm_localizator.ops import patch as patch_mod

    class _D:
        def items(self):
            return {patch_mod.hit_id("a.py", "Hi there"): {"status": "ignored"},
                    patch_mod.hit_id("b.ts", "Other"): {"status": "accepted"}}

    monkeypatch.setattr(patch_mod.ScanDecisions, "for_project", staticmethod(lambda cfg: _D()))
    hits = [{"file": "a.py", "line": 3, "text": "Hi there"}, {"file": "b.ts", "line": 1, "text": "Other"}]
    out = patch_mod.directive_suggestions(SimpleNamespace(), hits)
    assert out == [{"file": "a.py", "line": 3, "insert_above": "# l10n-ignore-next-line"}]


def test_patch_uses_directive_hints():
    from llm_localizator.ops.patch import _hardcoded_patches

    hit = {"file": "src/a.ts", "line": 1, "text": "Pay now", "key_hint": "pay", "namespace_hint": "checkout",
           "note": "Button", "max_length": 20, "dnt": False}
    p = _hardcoded_patches([hit], "")[0]
    assert p["suggested_catalogue_key"] == "checkout.pay"
    assert (p["note"], p["max_length"]) == ("Button", 20) and "dnt" not in p
