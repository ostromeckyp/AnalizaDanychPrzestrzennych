"""Spójność liczb w `docs/raport.md` z plikami oceny `data/processed/eval/*.json`.

Co sprawdza: każda liczba w raporcie oznaczona znacznikiem ``<!-- eval:plik.json:ścieżka -->`` musi być
wartością z tego pliku, zaokrągloną do tylu miejsc po przecinku, ile pokazuje raport.

Gramatyka znacznika (ustalona w Task 12 planu 4):

- Znacznik stoi **bezpośrednio po liczbie** (bez spacji), np. ``RMSE 1,51<!-- eval:bottom_vs_nmt.json:all.rmse --> m``.
  Jednostka (``m``, ``km``) idzie **za** znacznikiem; wyjątek to procent (niżej).
- Liczba: opcjonalny znak (``+``, ``-`` albo typograficzny minus ``−``), cyfry z opcjonalnymi separatorami tysięcy
  (spacja lub twarda spacja, np. ``8 477``), opcjonalnie **przecinek dziesiętny** (polski zapis, ``0,84``; kropka też
  jest akceptowana). Liczba miejsc po przecinku w raporcie wyznacza zaokrąglenie przy porównaniu.
- Procent: liczba zakończona ``%`` (z opcjonalną spacją, ``6,4 %``) przed znacznikiem oznacza wartość × 100
  (w JSON-ach udziały są ułamkami 0–1).
- ``plik.json`` jest względem ``data/processed/eval/``; dozwolone są ścieżki względne do sąsiednich katalogów
  (np. ``../kz/kz_meta.json``).
- Ścieżka klucza: segmenty rozdzielone kropką; segment z kropkami w nazwie w nawiasach kwadratowych
  (``contours.[195.0].mean_distance_m``, ``[192.5-195.0].bias``); liczba całkowita jako segment na liście = indeks.
- Porównanie: ``|wartość − wyświetlona| ≤ 0,5 · 10^(−miejsca)`` (plus margines na błąd zmiennoprzecinkowy).

Test pomijany, gdy nie ma ``data/processed/eval/`` (dane poza gitem). Funkcje parsera mają własne testy bez danych.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "raport.md"
EVAL_DIR = ROOT / "data" / "processed" / "eval"

# liczba (z %) bezpośrednio przed znacznikiem; grupa „num” to sama liczba
_NUMBER = r"(?P<num>[+\-−]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|[+\-−]?\d+(?:[.,]\d+)?)(?P<pct>\s?%)?"
MARKER_RE = re.compile(_NUMBER + r"<!--\s*eval:(?P<file>[^:\s]+):(?P<path>[^\s]+?)\s*-->")
ANY_MARKER_RE = re.compile(r"<!--\s*eval:")
_SEGMENT_RE = re.compile(r"\[([^\]]+)\]|([^.\[\]]+)")


def parse_number(text: str) -> tuple[float, int]:
    """Zwraca (wartość, liczba miejsc po przecinku) dla zapisu polskiego albo z kropką."""
    t = text.replace("−", "-").replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    decimals = len(t.split(".")[1]) if "." in t else 0
    return float(t), decimals


def split_path(path: str) -> list[str]:
    """``a.[195.0].b`` → ``["a", "195.0", "b"]``."""
    return [br or plain for br, plain in _SEGMENT_RE.findall(path)]


def resolve(data, path: str):
    """Wartość pod ścieżką; KeyError/IndexError, gdy jej nie ma."""
    node = data
    for seg in split_path(path):
        if isinstance(node, list):
            node = node[int(seg)]
        else:
            node = node[seg]
    return node


def find_markers(text: str) -> list[dict]:
    """Wszystkie znaczniki z liczbą przed sobą: dict(num, pct, file, path, line)."""
    out = []
    for m in MARKER_RE.finditer(text):
        out.append({"num": m.group("num"), "pct": bool(m.group("pct")), "file": m.group("file"),
                    "path": m.group("path"), "line": text.count("\n", 0, m.start()) + 1})
    return out


def check_marker(marker: dict, eval_dir: Path) -> str | None:
    """None, gdy liczba zgadza się z plikiem; w przeciwnym razie opis błędu."""
    where = f"linia {marker['line']}: {marker['num']}{' %' if marker['pct'] else ''} ← {marker['file']}:{marker['path']}"
    f = eval_dir / marker["file"]
    if not f.exists():
        return f"{where}: brak pliku {f}"
    try:
        value = resolve(json.loads(f.read_text(encoding="utf-8")), marker["path"])
    except (KeyError, IndexError, ValueError, TypeError):
        return f"{where}: brak klucza w pliku"
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return f"{where}: wartość nie jest liczbą ({value!r})"
    shown, decimals = parse_number(marker["num"])
    v = value * 100 if marker["pct"] else value
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    if abs(v - shown) > tol:
        return f"{where}: w pliku {v:.6g}, w raporcie {shown} (tolerancja {tol:g})"
    return None


# ---------------- testy parsera (bez danych) ----------------

def test_parse_number_polish_comma_sign_and_thousands():
    assert parse_number("+1,16") == (1.16, 2)
    assert parse_number("−0,21") == (-0.21, 2)
    assert parse_number("8 477") == (8477.0, 0)
    assert parse_number("47") == (47.0, 0)


def test_split_path_brackets_keep_dots():
    assert split_path("contours.[195.0].mean_distance_m") == ["contours", "195.0", "mean_distance_m"]
    assert split_path("[192.5-195.0].bias") == ["192.5-195.0", "bias"]
    assert split_path("control_r_2025.scenes.0.dB") == ["control_r_2025", "scenes", "0", "dB"]


def test_resolve_list_index():
    assert resolve({"a": [{"b": 2}]}, "a.0.b") == 2


def test_find_and_check_markers(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({"r": 0.84033, "s": 0.0641, "c": {"195.0": {"d": 47.19}}}))
    text = ("RMSE 0,84<!-- eval:x.json:r --> m\nudział 6,4 %<!-- eval:x.json:s -->\n"
            "średnio 47<!-- eval:x.json:c.[195.0].d --> m\nźle 0,85<!-- eval:x.json:r -->")
    ms = find_markers(text)
    assert [m["pct"] for m in ms] == [False, True, False, False]
    errors = [check_marker(m, tmp_path) for m in ms]
    assert errors[:3] == [None, None, None]
    assert errors[3] is not None and "linia 4" in errors[3]


def test_missing_key_is_reported(tmp_path):
    (tmp_path / "x.json").write_text("{}")
    m = find_markers("1,0<!-- eval:x.json:nope -->")[0]
    assert "brak klucza" in check_marker(m, tmp_path)


# ---------------- test raportu (na prawdziwych danych) ----------------

@pytest.mark.skipif(not EVAL_DIR.is_dir(), reason="brak data/processed/eval/ (dane poza gitem)")
def test_report_numbers_match_eval_json():
    assert REPORT.exists(), f"brak raportu {REPORT}"
    text = REPORT.read_text(encoding="utf-8")
    markers = find_markers(text)
    assert len(markers) >= 30, f"za mało oznaczonych liczb w raporcie: {len(markers)}"
    # każdy znacznik musi mieć liczbę bezpośrednio przed sobą (inaczej nie zostałby sprawdzony)
    assert len(ANY_MARKER_RE.findall(text)) == len(markers), "znacznik eval bez liczby bezpośrednio przed nim"
    errors = [e for e in (check_marker(m, EVAL_DIR) for m in markers) if e]
    assert not errors, "\n".join(errors)
