import importlib.util
import logging
from pathlib import Path

from mielizna import bottom

_SPEC = importlib.util.spec_from_file_location("bottom07", Path(__file__).parents[1] / "07_bottom_model.py")
s07 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(s07)


def _meta(proc, name):
    p = proc / "model" / name / "model_meta.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}")
    return p


def test_failed_verify_removes_meta_of_run_periods_and_returns_1(tmp_path, caplog):
    """M1: Make nie moze uznac niezweryfikowanego modelu za zbudowany (meta = cel Make)."""
    metas = {n: _meta(tmp_path, n) for n in ("all", "pre_flood", "post_flood")}
    with caplog.at_level(logging.INFO):
        rc = s07.finish(["asercja X"], tmp_path, ["all", "pre_flood"])
    assert rc == 1
    assert not metas["all"].exists() and not metas["pre_flood"].exists()
    assert metas["post_flood"].exists()          # okres niebiegnący w tym wywołaniu zostaje
    assert "model_meta.json" in caplog.text


def test_passing_verify_keeps_meta(tmp_path):
    m = _meta(tmp_path, "all")
    assert s07.finish([], tmp_path, ["all"]) == 0 and m.exists()


def test_flag8_meaning_has_no_hardcoded_share():
    assert "58" not in bottom.FLAG_MEANING["8"] and "c_water_ignored_px" in bottom.FLAG_MEANING["8"]
