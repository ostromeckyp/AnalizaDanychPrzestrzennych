"""Generator i wspólne obliczenia referencji ścieżki głębokości na prawdziwych danych.

Co robi: liczy sha1 klas stref, statystyki i ostrzeżenia dla siatki h × draft × margin oraz `point_info`
  dla losowych pikseli każdego wariantu; zapisuje wynik do `tests/fixtures/depth_baseline.json`.
Dlaczego tak: refaktor ścieżki głębokości (plan 6) ma nie zmienić ani jednego piksela; zamrażamy obecne
  zachowanie na `data/processed/`, a nie na syntetyku 20×30 px. Fixture trzyma sha1 zamiast tablic (mały plik).
Wejście → wyjście: `uv run python tests/depth_baseline.py` (z katalogu backend, na kodzie sprzed refaktoru)
  → `tests/fixtures/depth_baseline.json`; `compute_zones` / `compute_point` używa też test regresji.
Jak to obronić: punkty wybiera generator (seed 0) i zapisuje we fixture, więc test liczy dokładnie te same;
  porównanie jest dokładne (`==`), bo ten sam kod na tych samych danych daje bity identyczne.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import rasterio.transform
from pyproj import Transformer
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data import load_products                                    # noqa: E402
from app.point import point_info                                      # noqa: E402
from app.zones import zone_classes, zone_stats, zone_warnings         # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "depth_baseline.json"

H_ZONES = (193.0, 194.0, 195.0, 195.91)
DRAFTS = (0.3, 0.5, 1.0)
MARGINS = (0.0, 0.3)
H_POINTS = (193.0, 194.5)
PER_VARIANT = 3
N_GRAVEL = 2


def compute_zones(p, h: float, draft: float, margin: float) -> dict:
    classes = zone_classes(h, draft, margin, p.z_lo, p.z_hi, p.in_model)
    return {"sha1": hashlib.sha1(classes.tobytes()).hexdigest(),
            "stats": zone_stats(classes, h, p.z_lo, p.in_model),
            "warnings": zone_warnings(h, draft, margin, p)}


def compute_point(p, lon: float, lat: float, h: float, draft: float = 0.5, margin: float = 0.3) -> dict:
    return point_info(p, lon, lat, h, draft, margin)


def zone_key(h: float, draft: float, margin: float) -> str:
    return f"{h}|{draft}|{margin}"


def _lonlat(p, rows, cols):
    xs, ys = rasterio.transform.xy(p.transform, rows, cols)
    lon, lat = Transformer.from_crs(p.crs, 4326, always_xy=True).transform(np.array(xs), np.array(ys))
    return list(zip(map(float, lon), map(float, lat)))


def _pick_points(p) -> list[tuple[float, float]]:
    rng = np.random.default_rng(0)
    rows, cols = np.indices(p.shape)
    rows, cols = rows.ravel(), cols.ravel()
    lonlat = _lonlat(p, rows, cols)
    # wariant wg point_info przy h = 194.5 (ta sama klasyfikacja co w popupie)
    kinds = {}
    in_model = p.in_model[rows, cols]
    kinds["outside"] = np.flatnonzero(~in_model)
    zlo = p.z_lo[rows, cols]
    with np.errstate(invalid="ignore"):
        kinds["land"] = np.flatnonzero(in_model & (194.5 <= zlo))
        kinds["always_water"] = np.flatnonzero(in_model & (zlo == -np.inf))
        kinds["model"] = np.flatnonzero(in_model & (194.5 > zlo) & (zlo != -np.inf))
    chosen = []
    for name, idx in kinds.items():
        pick = rng.choice(idx, size=PER_VARIANT, replace=False)
        for i in pick:
            lon, lat = lonlat[i]
            assert compute_point(p, lon, lat, 194.5)["kind"] == name, name   # klasyfikacja zgodna z kodem
            chosen.append((lon, lat))
    if p.gravel_geom is not None:
        xs, ys = rasterio.transform.xy(p.transform, rows, cols)
        # pełny przegląd jest drogi: zawężamy do ramki obrysu
        x0, y0, x1, y1 = p.gravel.total_bounds
        near = np.flatnonzero((np.array(xs) >= x0) & (np.array(xs) <= x1) & (np.array(ys) >= y0) & (np.array(ys) <= y1))
        inside = [i for i in near if p.gravel_geom.contains(Point(xs[i], ys[i]))]
        pick = rng.choice(inside, size=N_GRAVEL, replace=False)
        for i in pick:
            lon, lat = lonlat[i]
            assert compute_point(p, lon, lat, 194.5)["gravel"] is True
            chosen.append((lon, lat))
    return chosen


def main() -> None:
    p = load_products(DATA, "all")
    zones = {zone_key(h, d, m): compute_zones(p, h, d, m) for h in H_ZONES for d in DRAFTS for m in MARGINS}
    points = [{"lon": lon, "lat": lat, "h": h, "draft": 0.5, "margin": 0.3, "out": compute_point(p, lon, lat, h)}
              for lon, lat in _pick_points(p) for h in H_POINTS]
    FIXTURE.parent.mkdir(exist_ok=True)
    FIXTURE.write_text(json.dumps({"zones": zones, "points": points}, indent=1, ensure_ascii=False, allow_nan=False))
    print(f"zapisano {len(zones)} stref i {len(points)} punktów → {FIXTURE}")


if __name__ == "__main__":
    main()
