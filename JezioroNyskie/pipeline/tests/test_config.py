from mielizna import config
from mielizna.config import data_path


def test_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MIELIZNA_DATA_DIR", str(tmp_path))
    assert data_path("processed", "x.tif") == tmp_path / "processed" / "x.tif"


def test_data_dir_default_without_env(monkeypatch):
    monkeypatch.delenv("MIELIZNA_DATA_DIR", raising=False)
    assert config.data_dir() == config.DATA_DIR
