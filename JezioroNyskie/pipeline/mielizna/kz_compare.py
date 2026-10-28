"""Porównanie modelu dna z mapą KŻ (K5): rzędne punktowe w pasmach, poziomice 192,5 i 195,0 m, werdykt go/no-go.

Co robi: (1) `compare_points` zestawia rzędne punktowe mapy KŻ z dnem modelu `pre_flood` w pasmach wysokości
  [192,5; 195,0), [195,0; NPP), >= NPP i osobno < 192,5 (orientacyjne), bez obrysu żwirowni; (2) `model_contour` wyznacza
  poziomicę modelu (`find_contours` na `z`), a `compare_contours` mierzy odległość od linii KŻ (średnia symetryczna,
  Hausdorff) i pokrycie; (3) `go_no_go` ocenia |bias| > 0,5 m i wypisuje sprawdzone przyczyny.
Dlaczego tak: mapa KŻ powstała „sposobem amatorskim”, a poniżej 192,5 m jest orientacyjna, więc metryki główne liczymy
  od 192,5 m wzwyż, a dolne pasmo osobno. Przy werdykcie georeferencji `aggregated_only` porównujemy komórki 50 m
  (mediana punktów KŻ vs mediana `z` modelu), bo punkt nie leży dokładnie w pikselu; przy `good/acceptable` bierzemy
  piksel 10 m pod punktem. Bias = średnia(model - KŻ); zawsze raportowany. Układ wysokości mapy KŻ jest nieznany,
  więc nic nie jest korygowane: bias jest tylko zestawiany z przesunięciem KRON86->EVRF2007 i z biasami z oceny LiDAR.
  NPP liczymy tak jak backend (`backend/app/data.py`): `capacity_to_level(65,69 mln m³)` z tabeli KŻ.
Wejście → wyjście: punkty KŻ (z, geometry; EPSG:2180), model {z, z_min, z_max}, siatka, obrys żwirowni → słowniki JSON
  (n, mae, rmse, bias, share_in_bounds na pasmo + `pooled`); linie → odległości w metrach.
Jak to obronić: testy na stałym modelu z policzonym ręcznie biasem, na równoległych liniach (10 m) i na ukośnej
  płaszczyźnie ze znaną poziomicą; poziomice KŻ to próbka „precision-first”, więc raportujemy długości porównane.
"""
import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString
from skimage.measure import find_contours

from mielizna import capacity, evaluate

NPP_MLN_M3 = 65.69        # jak backend/app/data.py (brief §4): normalny poziom piętrzenia, tabela KŻ Nysa [mln m³]
MAIN_FROM = 192.5         # poniżej mapa KŻ jest orientacyjna
CELL_M = 50.0
BIAS_LIMIT = 0.5
LINE_STEP_M = 10.0
CLIP_M = 150.0            # model porównujemy z KŻ tylko w tym buforze wokół linii KŻ (KŻ to próbka, nie cała poziomica)
BAND_KEYS = ("192.5-195.0", "195.0-npp", "npp+", "below_192.5")


def npp_level(table=None) -> float:
    """NPP [m n.p.m.] z tabeli pojemność-rzędna, dokładnie jak w backendzie."""
    return float(capacity.capacity_to_level(NPP_MLN_M3, table=table))


def _band(z: np.ndarray, npp: float) -> np.ndarray:
    return np.select([z < MAIN_FROM, z < 195.0, z < npp], ["below_192.5", "192.5-195.0", "195.0-npp"], default="npp+")


def _pairs_points(spots, model: dict, gravel, grid):
    """Pary (KŻ z, model z, z_min, z_max) na pikselu 10 m pod punktem; punkty w żwirowni lub poza siatką odpadają."""
    x = spots.geometry.x.to_numpy(float)
    y = spots.geometry.y.to_numpy(float)
    z = spots["z"].to_numpy(float)
    keep = np.ones(len(z), bool)
    if gravel is not None:
        keep &= ~shapely.contains_xy(gravel, x, y)
    col = np.floor((x - grid.transform.c) / grid.transform.a).astype(int)
    row = np.floor((y - grid.transform.f) / grid.transform.e).astype(int)
    inside = (row >= 0) & (row < grid.height) & (col >= 0) & (col < grid.width)
    keep &= inside
    r, c = row[keep], col[keep]
    return z[keep], model["z"][r, c], model["z_min"][r, c], model["z_max"][r, c]


def _nanmedian(a: np.ndarray) -> float:
    a = a[np.isfinite(a)]
    return float(np.median(a)) if a.size else float("nan")


def _pairs_cells(spots, model: dict, gravel, grid):
    """Pary na komórkach 50 m: mediana rzędnych KŻ w komórce vs mediana `z` modelu w tej komórce (piksele 10 m)."""
    k = int(round(CELL_M / abs(grid.transform.a)))
    x = spots.geometry.x.to_numpy(float)
    y = spots.geometry.y.to_numpy(float)
    z = spots["z"].to_numpy(float)
    keep = np.ones(len(z), bool)
    if gravel is not None:
        keep &= ~shapely.contains_xy(gravel, x, y)
    ci = np.floor((x - grid.transform.c) / CELL_M).astype(int)
    ri = np.floor((y - grid.transform.f) / (-CELL_M)).astype(int)
    keep &= (ri >= 0) & (ci >= 0) & (ri * k < grid.height) & (ci * k < grid.width)
    out = {}
    for r, c, v in zip(ri[keep], ci[keep], z[keep]):
        out.setdefault((r, c), []).append(v)
    ref, zz, lo, hi = [], [], [], []
    for (r, c), vals in out.items():
        sl = (slice(r * k, (r + 1) * k), slice(c * k, (c + 1) * k))
        ref.append(float(np.median(vals)))
        zz.append(_nanmedian(model["z"][sl]))
        lo.append(_nanmedian(model["z_min"][sl]))
        hi.append(_nanmedian(model["z_max"][sl]))
    return tuple(np.asarray(a, float) for a in (ref, zz, lo, hi))


def _block(ref, pred, lo, hi, n_spots: int, unit: str) -> dict:
    ok = np.isfinite(ref) & np.isfinite(pred)
    out = evaluate.metrics(pred[ok], ref[ok])
    out["share_in_bounds"] = evaluate.share_in_bounds(ref[ok], lo[ok], hi[ok]) if ok.any() else float("nan")
    out.update({"n_spots": int(n_spots), "unit": unit})
    return out


def compare_points(spots, model: dict, gravel, npp: float, grid, verdict: str = "good") -> dict:
    """Metryki dna modelu względem rzędnych KŻ w pasmach; `pooled` = pasma >= 192,5 m łącznie (bez < 192,5).

    `verdict == "aggregated_only"` -> komórki 50 m, w przeciwnym razie piksel 10 m pod punktem. Punkty bez `z` modelu
    nie wchodzą do `n` (liczy je różnica `n_spots - n`). Zwraca słownik pasm, `pooled` i `unit`."""
    cells = verdict == "aggregated_only"
    ref, pred, lo, hi = (_pairs_cells if cells else _pairs_points)(spots, model, gravel, grid)
    unit = "cell50" if cells else "pixel10"
    band = _band(ref, npp)
    out = {k: _block(ref[band == k], pred[band == k], lo[band == k], hi[band == k], int((band == k).sum()), unit)
           for k in BAND_KEYS}
    main = band != "below_192.5"
    out["pooled"] = _block(ref[main], pred[main], lo[main], hi[main], int(main.sum()), unit)
    out["pooled"]["bands"] = "192.5+"
    out["unit"] = unit
    out["npp"] = float(npp)
    return out


def _parts(geom) -> list:
    if geom is None or geom.is_empty:
        return []
    return [g for g in getattr(geom, "geoms", [geom]) if g.length > 0]


def _sample(geom, step: float = LINE_STEP_M) -> np.ndarray:
    pts = []
    for p in _parts(geom):
        n = max(2, int(np.ceil(p.length / step)) + 1)
        pts.extend(p.interpolate(d, normalized=True).coords[0] for d in np.linspace(0, 1, n))
    return np.asarray(pts, float).reshape(-1, 2)


def _dists(a, b, step: float = LINE_STEP_M) -> np.ndarray:
    """Odległości punktów próbkowanych na `a` (co `step` m) do geometrii `b`."""
    pts = _sample(a, step)
    return shapely.distance(shapely.points(pts), b) if len(pts) else np.array([])


def mean_distance(a, b, step: float = LINE_STEP_M) -> float:
    """Średnia odległość symetryczna linii: (śr. a->b + śr. b->a) / 2 [m]; równoległe linie o odstępie 10 m dają 10."""
    return float((_dists(a, b, step).mean() + _dists(b, a, step).mean()) / 2)


def model_contour(z: np.ndarray, grid, level: float):
    """Poziomica `level` rastra `z` (NaN omijane) jako MultiLineString w EPSG:2180; pusta, gdy poziom poza zakresem."""
    t = grid.transform
    lines = []
    for seg in find_contours(np.asarray(z, float), float(level)):
        if len(seg) < 2:
            continue
        x = t.c + (seg[:, 1] + 0.5) * t.a
        y = t.f + (seg[:, 0] + 0.5) * t.e
        lines.append(LineString(np.c_[x, y]))
    return MultiLineString(lines)


def compare_contours(kz_geom, model_geom, clip_m: float = CLIP_M) -> dict:
    """Poziomica KŻ vs modelu: odległości [m] i pokrycie [km].

    KŻ to próbka poziomicy (precision-first), więc model jest przycięty do bufora `clip_m` wokół linii KŻ; średnia symetryczna
    i Hausdorff dotyczą pary (KŻ, model w buforze). `kz_to_model_*` liczy odległość od linii KŻ do CAŁEJ poziomicy modelu
    (to ona mówi, jak daleko od KŻ leży model); sama zależy tylko od KŻ, więc nie zależy od bufora."""
    clipped = model_geom.intersection(kz_geom.buffer(clip_m)) if not model_geom.is_empty else model_geom
    km = lambda g: float(sum(p.length for p in _parts(g)) / 1000.0)           # noqa: E731
    out = {"kz_length_km": km(kz_geom), "model_length_km_total": km(model_geom), "model_length_km_compared": km(clipped)}
    if not _parts(clipped) or not _parts(kz_geom):
        return {**out, "mean_distance_m": float("nan"), "hausdorff_m": float("nan"),
                "kz_to_model_mean_m": float("nan"), "kz_to_model_p90_m": float("nan")}
    d = _dists(kz_geom, model_geom)
    out.update({"mean_distance_m": mean_distance(kz_geom, clipped), "hausdorff_m": float(shapely.hausdorff_distance(kz_geom, clipped)),
                "kz_to_model_mean_m": float(d.mean()), "kz_to_model_p90_m": float(np.percentile(d, 90)),
                "clip_m": float(clip_m)})
    return out


def go_no_go(bias: float, datum_offset: float, other_biases: dict) -> dict:
    """|bias| > 0,5 m -> „investigate” z listą sprawdzonych przyczyn; inaczej „go”. Same fakty, bez korekt.

    `datum_offset`: przesunięcie KRON86 -> EVRF2007 [m]; `other_biases`: biasy z oceny LiDAR (Task 8) do zestawienia."""
    notes = [f"Układ wysokości: układ rzędnych mapy KŻ jest nieznany (prawdopodobnie wodowskaz lokalny/RZGW). Bias względem KŻ "
             f"{bias:+.2f} m, przesunięcie KRON86->EVRF2007 {datum_offset:+.3f} m: różnica bias - offset = {bias - datum_offset:+.2f} m."]
    for name, b in other_biases.items():
        notes.append(f"Bias dna względem LiDAR ({name}): {b:+.2f} m; różnica bias_KŻ - bias_LiDAR = {bias - b:+.2f} m.")
    notes.append("Dno z 2023: mapa KŻ (aktualizacja 23.05.2023) opisuje dno sprzed powodzi z września 2024, model pre_flood obejmuje "
                 "sceny do 31.08.2024, więc zmiany dna po 2023 nie są przyczyną różnic przed powodzią, ale różnica dat zostaje.")
    notes.append("Sposób pomiaru: dane KŻ pozyskano sposobem amatorskim (echosonda/odczyty, bez opisu niepewności); "
                 "poniżej 192,5 m dno jest orientacyjne.")
    decision = "investigate" if abs(bias) > BIAS_LIMIT else "go"
    return {"decision": decision, "bias": float(bias), "limit": BIAS_LIMIT, "datum_offset": float(datum_offset), "notes": notes}
