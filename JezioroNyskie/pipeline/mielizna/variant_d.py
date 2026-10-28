"""Wariant D - kontrola poziomów wody: powierzchnia dna z mapy KŻ dopasowana do linii brzegowej sceny.

Co robi: (1) `kz_surface` buduje z rzędnych punktowych i wierzchołków poziomic KŻ powierzchnię na siatce modelu
  (TIN, interpolacja liniowa `scipy.interpolate.griddata`); (2) `fit_level` dla linii brzegowej sceny szuka rzędnej h
  z siatki poziomów, przy której poziomica powierzchni na h leży najbliżej punktów linii brzegowej (co 10 m).
Dlaczego tak: brzeg widoczny na zdjęciu satelitarnym to przecięcie wody z dnem, więc poziomica dna na rzędnej
  poziomu wody powinna się pokrywać z brzegiem. Dopasowany h jest NIEZALEŻNĄ kontrolą `h_t` (z komunikatów, LiDAR,
  krzywej), nigdy jego źródłem (BRIEF §6.6, unikanie przecieku). Powierzchnia jest NaN poza otoczką wypukłą danych
  (TIN nie ekstrapoluje) i w żwirowni (dno przekopane po mapie, rzędne tam nie opisują brzegu); takie punkty linii
  brzegowej pomijamy, a scena z za małą liczbą punktów (`MIN_POINTS`) jest pomijana z powodem.
Wejście → wyjście: punkty (z), poziomice (level, linie), siatka, obrys żwirowni, linia brzegowa -> macierz
  powierzchni [wiersz, kolumna] w m n.p.m.; (h, średnia odległość [m]).
Jak to obronić: test na stożku (znana odpowiedź 195,0 m), test NaN w żwirowni; liczby zgodności z `h_t` w M7.
"""
import numpy as np
import shapely
from scipy.interpolate import griddata
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString
from skimage.measure import find_contours

from mielizna.grid import Grid

LEVELS = np.arange(192.5, 198.0 + 1e-9, 0.05)
SHORE_STEP_M = 10.0
MIN_POINTS = 50          # poniżej tylu punktów brzegu z powierzchnią scenę pomijamy (kilkaset m brzegu)
VERTEX_STEP_M = 20.0     # poziomice KŻ zagęszczamy do tego kroku, żeby TIN nie "ścinał" łuków


def _centres(grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    t = grid.transform
    x = t.c + (np.arange(grid.width) + 0.5) * t.a
    y = t.f + (np.arange(grid.height) + 0.5) * t.e
    return np.meshgrid(x, y)


def _line_points(geom, step: float) -> np.ndarray:
    parts = geom.geoms if hasattr(geom, "geoms") else [geom]
    pts = []
    for p in parts:
        n = max(2, int(np.ceil(p.length / step)) + 1)
        pts.extend((q.x, q.y) for q in (p.interpolate(d, normalized=True) for d in np.linspace(0, 1, n)))
    return np.asarray(pts, float).reshape(-1, 2)


def kz_surface(spots, contours, grid: Grid, gravel=None) -> np.ndarray:
    """Powierzchnia dna z punktów rzędnych i poziomic KŻ (TIN, liniowo); NaN poza otoczką i w żwirowni."""
    px = np.c_[spots.geometry.x.to_numpy(), spots.geometry.y.to_numpy(), spots["z"].to_numpy(float)]
    parts = [px]
    for g, lv in zip(contours.geometry, contours["level"]):
        xy = _line_points(g, VERTEX_STEP_M)
        parts.append(np.c_[xy, np.full(len(xy), float(lv))])
    pts = np.vstack(parts)
    pts = np.unique(np.round(pts, 3), axis=0)                    # powtórzone wierzchołki psują triangulację
    xx, yy = _centres(grid)
    surf = griddata(pts[:, :2], pts[:, 2], (xx, yy), method="linear")
    if gravel is not None:
        surf[shapely.contains_xy(gravel, xx, yy)] = np.nan
    return surf


def shore_points(shore, step: float = SHORE_STEP_M) -> np.ndarray:
    """Punkty (x, y) co `step` m wzdłuż linii brzegowej (LineString albo MultiLineString)."""
    if isinstance(shore, (LineString, MultiLineString)):
        return _line_points(shore, step)
    raise TypeError(type(shore))


def level_trees(surface: np.ndarray, grid: Grid, levels: np.ndarray = LEVELS) -> dict[float, cKDTree | None]:
    """Dla każdej rzędnej: drzewo wierzchołków poziomicy powierzchni (x, y w EPSG:2180); None gdy poziomicy nie ma."""
    t = grid.transform
    trees = {}
    for h in levels:
        segs = find_contours(surface, float(h))
        if not segs:
            trees[float(h)] = None
            continue
        v = np.vstack(segs)                                       # (wiersz, kolumna) w układzie węzłów pikseli
        x = t.c + (v[:, 1] + 0.5) * t.a
        y = t.f + (v[:, 0] + 0.5) * t.e
        trees[float(h)] = cKDTree(np.c_[x, y])
    return trees


def fit_level(shore, surface: np.ndarray, grid: Grid, levels: np.ndarray = LEVELS,
              min_points: int = MIN_POINTS, trees=None) -> tuple[float, float]:
    """(h, średnia odległość [m]) minimalizujące średnią odległość punktów brzegu od poziomicy powierzchni na h.

    Punkty brzegu bez wartości powierzchni (NaN: poza otoczką, żwirownia) są pomijane; gdy zostaje mniej niż
    `min_points`, zwraca (nan, nan). `trees` (z `level_trees`) pozwala policzyć poziomice raz dla wielu scen."""
    pts = shore_points(shore)
    rc = np.array([grid.rowcol(x, y) for x, y in pts])
    inside = (rc[:, 0] >= 0) & (rc[:, 0] < grid.height) & (rc[:, 1] >= 0) & (rc[:, 1] < grid.width)
    pts, rc = pts[inside], rc[inside]
    ok = np.isfinite(surface[rc[:, 0], rc[:, 1]])
    pts = pts[ok]
    if len(pts) < min_points:
        return float("nan"), float("nan")
    trees = trees if trees is not None else level_trees(surface, grid, levels)
    best_h, best_d = float("nan"), float("inf")
    for h in levels:
        tr = trees[float(h)]
        if tr is None:
            continue
        d = float(tr.query(pts)[0].mean())
        if d < best_d:
            best_h, best_d = float(h), d
    if not np.isfinite(best_d):
        return float("nan"), float("nan")
    return best_h, best_d


def summarize(fit, scenes, tol: float = 0.2) -> dict:
    """Zgodność h_t_d z h_t sceny: liczba scen, udział |różnicy| ≤ `tol`, mediana |różnicy|, rozbicie na metody.

    `fit`: DataFrame (date, h_t_d); `scenes`: (date, h_t, h_method). Bez scen z h_t NaN (np. qc_excluded)."""
    m = fit.merge(scenes[["date", "h_t", "h_method"]], on="date")
    m = m[np.isfinite(m.h_t) & np.isfinite(m.h_t_d)]
    diff = (m.h_t_d - m.h_t).abs()

    def block(d, sub):
        return {"n": int(len(sub)), "share_within_0_2": float((d <= tol).mean()) if len(sub) else None,
                "median_abs_diff": float(d.median()) if len(sub) else None,
                "median_diff": float((sub.h_t_d - sub.h_t).median()) if len(sub) else None}

    out = {"n_scenes": int(len(m)), "share_within_0_2": float((diff <= tol).mean()) if len(m) else None,
           "median_abs_diff": float(diff.median()) if len(m) else None,
           "median_diff": float((m.h_t_d - m.h_t).median()) if len(m) else None}
    out["by_method"] = {k: block(diff[m.h_method == k], m[m.h_method == k]) for k in ("A", "B", "R", "C")}
    return out
