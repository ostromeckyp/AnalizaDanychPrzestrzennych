import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = ["08_evaluate.py", "10_kz_compare.py", "12_holdout.py", "12a_holdout_levels.py", "13_error_budget.py"]


def test_evaluation_scripts_do_not_read_combined_rasters():
    """Ocena (08, 10, 12, 12a, 13) nie może czytać rastrów łączonych `<okres>_kz` (zależność kołowa z KŻ)."""
    for name in SCRIPTS:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r'_kz"|_kz/|"_kz', text), name
