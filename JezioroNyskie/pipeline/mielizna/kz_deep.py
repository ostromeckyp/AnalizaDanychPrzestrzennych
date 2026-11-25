"""Powierzchnia dna KŻ dla głębokiej części jeziora i sprawdzenie jej błędu metodą leave-one-out (LOO).

Co robi: (1) `deep_surface` buduje z punktów rzędnych KŻ i poziomicy 192,5 m powierzchnię dna (TIN, jak
  `variant_d.kz_surface`), z POMINIĘCIEM poziomicy 195,0 m; (2) `loo` dla punktów leżących w obszarze „zawsze woda”
  (poza żwirownią) usuwa po kolei jeden punkt, odbudowuje powierzchnię bez niego i czyta ją w pikselu tego punktu.
Dlaczego tak: model satelitarny nie widzi dna poniżej ok. 193,05 m w pikselach zawsze mokrych, więc tam jedynym
  źródłem rzędnych jest mapa KŻ. Poziomica 195,0 m (urywki) powoduje większość sprzeczności z obrazem satelitarnym,
  a głęboka część jej nie potrzebuje. LOO mierzy błąd interpolacji MIĘDZY punktami pomiarowymi (nie błąd samych
  punktów): to uczciwa, zewnętrzna ocena powierzchni. Dla szybkości LOO liczy TIN tylko w jednym pikselu
  (`LinearNDInterpolator` na identycznym zbiorze wierzchołków jak `kz_surface`: to samo zagęszczenie poziomic,
  zaokrąglenie i `unique`); test porównuje to z pełnym `deep_surface` odczytanym w tym pikselu.
Konwencja znaku: err = odczyt − rzędna punktu (dodatni, gdy powierzchnia leży wyżej, czyli płycej niż punkt).
  Punkt, który po usunięciu wypada poza otoczką wypukłą pozostałych danych (TIN nie ekstrapoluje), jest pomijany
  i liczony w `n_skipped`; w statystykach nie ma NaN. P5/P95 to kwantyle błędu ZE ZNAKIEM, `p90_abs` z |err|.
Wejście → wyjście: punkty (id, z, geometry), poziomice (level, linie), siatka, żwirownia, maska zawsze-woda
  [wiersz, kolumna] -> macierz powierzchni; słownik {n, n_skipped, mae, bias, p5, p95, p90_abs, below_192_9, errors}.
Jak to obronić: test płaszczyzny (LOO ≈ 0), pominięcie wierzchołka otoczki, brak wpływu poziomicy 195,0, znak błędu
  i zgodność obliczenia punktowego z pełną powierzchnią.
"""
import numpy as np
import shapely
from scipy.interpolate import LinearNDInterpolator

from mielizna import variant_d
from mielizna.grid import Grid

DEEP_CONTOURS = (192.5,)
BELOW_Z = 192.9      # podzbiór „głęboki”: punkty o rzędnej poniżej tego progu


def _deep(contours):
    keep = np.isclose(contours["level"].to_numpy(float)[:, None], np.asarray(DEEP_CONTOURS)[None, :]).any(axis=1)
    return contours[keep]


def deep_surface(spots, contours, grid: Grid, gravel=None) -> np.ndarray:
    """Powierzchnia KŻ bez poziomicy 195,0 m (tylko `DEEP_CONTOURS`); NaN poza otoczką i w żwirowni."""
    return variant_d.kz_surface(spots, _deep(contours), grid, gravel=gravel)


def _stats(err: np.ndarray) -> dict:
    if len(err) == 0:
        return {"n": 0, "mae": None, "bias": None, "p5": None, "p95": None, "p90_abs": None}
    return {"n": int(len(err)), "mae": float(np.abs(err).mean()), "bias": float(err.mean()),
            "p5": float(np.quantile(err, 0.05)), "p95": float(np.quantile(err, 0.95)),
            "p90_abs": float(np.quantile(np.abs(err), 0.90))}


def loo(spots, contours, grid: Grid, gravel, mask: np.ndarray) -> dict:
    """Błąd interpolacji `deep_surface` między punktami (leave-one-out) w obszarze `mask` poza żwirownią."""
    spots = spots.reset_index(drop=True)
    sx, sy = spots.geometry.x.to_numpy(float), spots.geometry.y.to_numpy(float)
    sz = spots["z"].to_numpy(float)
    parts = []
    for g, lv in zip(_deep(contours).geometry, _deep(contours)["level"]):
        xy = variant_d._line_points(g, variant_d.VERTEX_STEP_M)
        parts.append(np.c_[xy, np.full(len(xy), float(lv))])
    cont = np.vstack(parts) if parts else np.empty((0, 3))
    t = grid.transform
    errors, n_skipped = [], 0
    for i in range(len(spots)):
        row, col = grid.rowcol(sx[i], sy[i])
        if not (0 <= row < grid.height and 0 <= col < grid.width) or not mask[row, col]:
            continue
        cx, cy = grid.xy(row, col)                                   # środek piksela, jak w kz_surface
        if gravel is not None and shapely.contains_xy(gravel, cx, cy):
            continue
        others = np.arange(len(spots)) != i
        pts = np.vstack([np.c_[sx[others], sy[others], sz[others]], cont])
        pts = np.unique(np.round(pts, 3), axis=0)
        pred = float(LinearNDInterpolator(pts[:, :2], pts[:, 2])(cx, cy))
        if not np.isfinite(pred):
            n_skipped += 1
            continue
        errors.append({"id": spots["id"].iloc[i] if "id" in spots else i, "z": float(sz[i]), "pred": pred,
                       "err": pred - float(sz[i])})
    err = np.array([e["err"] for e in errors], float)
    z = np.array([e["z"] for e in errors], float)
    out = _stats(err)
    out["n_skipped"] = int(n_skipped)
    out["below_192_9"] = _stats(err[z < BELOW_Z])
    out["errors"] = errors
    return out
