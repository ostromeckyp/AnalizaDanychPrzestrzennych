import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("kzcompare10", Path(__file__).parents[1] / "10_kz_compare.py")
s10 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(s10)


def _setup(tmp_path, monkeypatch, nmt=None, epochs=None):
    monkeypatch.setenv("MIELIZNA_DATA_DIR", str(tmp_path))
    proc = tmp_path / "processed"
    (proc / "eval").mkdir(parents=True)
    (proc / "lidar").mkdir(parents=True)
    if nmt is not None:
        (proc / "eval" / "bottom_vs_nmt.json").write_text(nmt, encoding="utf-8")
    if epochs is not None:
        (proc / "lidar" / "epochs.csv").write_text(epochs, encoding="utf-8")
    return proc


EPOCHS = "epoch,uklad_h,datum_offset\n2011,PL-KRON86-NH,0.199\n2024,PL-EVRF2007-NH,0.0\n"
NMT = '{"all": {"bias": 1.1}, "pre_flood": {"bias": 0.2}}'


def test_compare_inputs_ok(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, NMT, EPOCHS)
    offset, nmt = s10.compare_inputs()
    assert offset == pytest.approx(0.199) and nmt["all"]["bias"] == 1.1


@pytest.mark.parametrize("nmt,epochs,msg", [
    (None, EPOCHS, "bottom_vs_nmt.json"),
    (NMT, None, "epochs.csv"),
    ('{"all": {"bias": 1.1}}', EPOCHS, "pre_flood"),
    (NMT, "epoch,uklad_h,datum_offset\n2024,PL-EVRF2007-NH,0.0\n", "KRON86"),
])
def test_compare_inputs_missing_gives_clear_exit(tmp_path, monkeypatch, nmt, epochs, msg):
    _setup(tmp_path, monkeypatch, nmt, epochs)
    with pytest.raises(SystemExit) as e:
        s10.compare_inputs()
    assert msg in str(e.value) and "make" in str(e.value)
