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
REF_LEVEL = 194.0        # poziom odniesienia długości poziomicy (środek zakresu, gdzie powierzchnia jest dobrze określona)
MIN_LENGTH_FRAC = 0.5    # poziomica "istnieje" gdy jej długość ≥ 50 % długości na REF_LEVEL
MIN_POINTS = 50          # poniżej tylu punktów brzegu z powierzchnią scenę pomijamy (kilkaset m brzegu)
MIN_SPOT_Z = 192.5       # mapa KŻ sama opisuje dno poniżej 192,5 m jako „orientacyjne” (blok UWAGA, KZ_ZRODLO_I_WARUNKI.md), więc
#                          punkty rzędnych głębsze niż to nie wchodzą do TIN (poziomice 192,5 i 195,0 m wchodzą). Próg wybrany po
#                          ablacji (M7 §6), uzasadniony zastrzeżeniem samej mapy.
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


def kz_surface(spots, contours, grid: Grid, gravel=None, min_spot_z: float = MIN_SPOT_Z) -> np.ndarray:
    """Powierzchnia dna z punktów rzędnych i poziomic KŻ (TIN, liniowo); NaN poza otoczką i w żwirowni.

    Punkty z rzędną < `min_spot_z` (domyślnie 192,5 m: dno „orientacyjne” wg samej mapy KŻ) są pomijane."""
    spots = spots[spots["z"].to_numpy(float) >= min_spot_z]
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


def level_lengths(surface: np.ndarray, grid: Grid, levels: np.ndarray = LEVELS) -> dict[float, float]:
    """Długość [m] poziomicy powierzchni na każdej rzędnej (suma długości odcinków find_contours)."""
    res = abs(grid.transform.a)
    out = {}
    for h in levels:
        segs = find_contours(surface, float(h))
        out[float(h)] = float(sum(np.hypot(*np.diff(sg, axis=0).T).sum() for sg in segs) * res)
    return out


def h_max_valid(surface: np.ndarray, grid: Grid, levels: np.ndarray = LEVELS, ref: float = REF_LEVEL,
                frac: float = MIN_LENGTH_FRAC) -> float:
    """Najwyższa rzędna, do której powierzchnia KŻ ma poziomicę o sensownej długości.

    Reguła: idziemy w górę od `ref` (194,0 m) i zatrzymujemy się na pierwszej rzędnej, na której długość poziomicy
    spada poniżej `frac` (50 %) długości na `ref`; `h_max_valid` to ostatnia rzędna przed spadkiem. Powyżej niej
    poziomica jest urywkiem (np. 195,0 m ma tylko wybrane odcinki, ląd 7 punktów), więc brzeg sceny z wysoką wodą nie
    ma do czego się dopasować, a fit „przykleja się” do najwyższej poziomicy, która jeszcze istnieje.
    Wybrano regułę z danych (a nie sztywne 195,0), żeby ewentualna lepsza powierzchnia sama podniosła limit."""
    L = level_lengths(surface, grid, levels)
    lv = sorted(L)
    base = L[min(lv, key=lambda h: abs(h - ref))]
    best = None
    for h in lv:
        if h < ref - 1e-9:
            continue
        if L[h] < frac * base:
            break
        best = h
    return float("nan") if best is None else float(best)


def is_valid(h: float, dist_m: float, hmax: float, levels: np.ndarray = LEVELS,
             h_ref: float | None = None) -> bool:
    """Fit `d_valid`: h < h_max_valid − 0,05 m, nie na brzegu siatki poziomów i (gdy podano) h_ref (= h_t) < h_max_valid.

    Warunek na `h_ref` to DZIEDZINA metody, nie strojenie: powierzchnia KŻ opisuje tylko poziomy poniżej `h_max_valid`,
    więc D może sprawdzić tylko sceny, których poziom odniesienia tam leży (dla wyższych fit ląduje w środku zakresu).
    Średnia odległość `dist_m` NIE jest kryterium: profil jest płaski (np. 2017-04-01: 120,3 / 118,2 / 121,3 m dla
    194,25 / 194,50 / 194,75 m), więc nie odróżnia dobrych fitów od złych; zostaje kolumną informacyjną."""
    if not (np.isfinite(h) and np.isfinite(hmax)):
        return False
    if h_ref is not None and not (np.isfinite(h_ref) and h_ref < hmax):
        return False
    edge = h <= levels[0] + 1e-9 or h >= levels[-1] - 1e-9
    return bool(h < hmax - 0.05 + 1e-9 and not edge)


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
