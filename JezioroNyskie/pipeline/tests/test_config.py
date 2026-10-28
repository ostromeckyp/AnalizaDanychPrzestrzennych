from mielizna import config
from mielizna.config import data_path


def test_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MIELIZNA_DATA_DIR", str(tmp_path))
    assert data_path("processed", "x.tif") == tmp_path / "processed" / "x.tif"


def test_data_dir_default_without_env(monkeypatch):
    monkeypatch.delenv("MIELIZNA_DATA_DIR", raising=False)
    assert config.data_dir() == config.DATA_DIR


def test_load_config_merges_lidar_and_kz_part_files():
    """kz/lidar są w osobnych plikach (tuning KŻ nie unieważnia łańcucha S2), ale API cfg["kz"]/cfg["lidar"] bez zmian."""
    cfg = config.load_config()
    assert "spot_position_reject" in cfg["kz"] and cfg["lidar"]["epochs"]
    assert "grid" in cfg and "paths" in cfg
    import yaml
    main = yaml.safe_load(config.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    assert "kz" not in main and "lidar" not in main


def test_load_config_part_files_next_to_explicit_path(tmp_path):
    (tmp_path / "config.yaml").write_text("grid: {res: 10}\n", encoding="utf-8")
    (tmp_path / "config_kz.yaml").write_text("kz: {a: 1}\n", encoding="utf-8")
    cfg = config.load_config(tmp_path / "config.yaml")
    assert cfg == {"grid": {"res": 10}, "kz": {"a": 1}}          # brak config_lidar.yaml jest dozwolony


def test_load_config_rejects_duplicate_top_level_key(tmp_path):
    import pytest
    (tmp_path / "config.yaml").write_text("kz: {a: 1}\n", encoding="utf-8")
    (tmp_path / "config_kz.yaml").write_text("kz: {a: 2}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="kz"):
        config.load_config(tmp_path / "config.yaml")
