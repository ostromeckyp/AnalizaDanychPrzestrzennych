"""Ocena dokładności (spec §7): dno z satelity vs NMT, poziomy wody A/B/C/R, zmiana dna po powodzi, wybór modelu dla aplikacji.

Co robi: czyste funkcje liczące metryki (MAE, RMSE, bias), uśredniające NMT 1 m do siatki 10 m, porównujące
  model dna z NMT wyłącznie w blokach „valid", oceniające zmianę dna `pre_flood` -> `post_flood` i wybierające
  okres modelu serwowany przez aplikację (próg 5 % pikseli ze zmianą istotną).
Dlaczego tak: wariant A kalibrował poziom wody tylko w blokach „calib" (mielizna/blocks.py), więc porównanie dna z NMT
  w blokach „valid" nie jest krążące (brak przecieku). NMT jest uśredniany do 10 m (średnia ważona obecnością ważnych
  komórek 1 m, wymóg >= 50 % pokrycia), bo model ma piksel 10 m; pojedyncza komórka 1 m nie jest porównywalna z pikselem.
  Układ wysokości: NMT KRON86 sprowadzamy do EVRF2007 dokładnie raz (`offset` w `dem_to_grid`); poziomy modelu dziedziczą
  głównie układ RZGW, więc zmierzony bias zawiera też ewentualne przesunięcie RZGW <-> EVRF2007 (nie jest korygowany).
Wejście → wyjście: tablice rastrów modelu (`bottom.read_model`), rastry NMT, scenes.json -> słowniki JSON (patrz 08_evaluate.py).
Jak to obronić: każda metryka ma jawny wzór (bias = średnia(pred - ref)); filtr „NMT > h_water + 0,1 m" wycina wodę i
  strefę przyboju z ewaluacji (NMT nad wodą to lustro wody); próg 5 % pochodzi z założeń projektu (BRIEF/spec §6a).
"""
import numpy as np

SHARE_THRESHOLD = 0.05        # udział pikseli z istotną zmianą dna, od którego aplikacja przechodzi na post_flood
WATER_MARGIN = 0.1            # [m] NMT musi leżeć o tyle nad poziomem wody epoki, by uznać piksel za ląd
MIN_COVER = 0.5               # minimalny udział ważnych komórek 1 m w pikselu 10 m


def metrics(pred: np.ndarray, ref: np.ndarray) -> dict:
    """n, mae, rmse, bias (= średnia(pred - ref)) na parach skończonych; puste wejście daje NaN."""
    pred = np.asarray(pred, float)
    ref = np.asarray(ref, float)
    ok = np.isfinite(pred) & np.isfinite(ref)
    d = pred[ok] - ref[ok]
    if d.size == 0:
        return {"n": 0, "mae": float("nan"), "rmse": float("nan"), "bias": float("nan")}
    return {"n": int(d.size), "mae": float(np.abs(d).mean()), "rmse": float(np.sqrt((d ** 2).mean())),
            "bias": float(d.mean())}


def share_in_bounds(ref: np.ndarray, zmin: np.ndarray, zmax: np.ndarray) -> float:
    """Udział wartości ref w [z_min, z_max]; NaN w z_min = brak dolnej granicy, NaN w z_max = brak górnej."""
    ref = np.asarray(ref, float)
    if ref.size == 0:
        return float("nan")
    lo = np.where(np.isnan(zmin), -np.inf, zmin)
    hi = np.where(np.isnan(zmax), np.inf, zmax)
    return float(((ref >= lo) & (ref <= hi)).mean())


def bottom_vs_dem(model: dict, dem: np.ndarray, h_water: float, roles: np.ndarray) -> dict:
    """Dno modelu (`z`) vs NMT na pikselach: blok „valid", NMT > h_water + 0,1 m, model ma `z`.

    `dem` jest już na siatce modelu (10 m) i w EVRF2007; `roles` to tablica „calib"/„valid" (blocks.block_role).
    Zwraca n, mae, rmse, bias (model - NMT) i share_in_bounds (NMT w [z_min, z_max]); `errors` w kluczu pomocniczym
    nie jest zwracane (zob. `bottom_errors`).
    """
    sel = _select(model, dem, h_water, roles)
    out = metrics(model["z"][sel], dem[sel])
    out["share_in_bounds"] = share_in_bounds(dem[sel], model["z_min"][sel], model["z_max"][sel])
    # kontekst: rozrzut NMT (RMSE stałej predykcji = ref_std) i korelacja; bez nich RMSE nie mówi, czy model cokolwiek wnosi
    out["ref_std"] = float(np.std(dem[sel])) if out["n"] else float("nan")
    out["corr"] = float(np.corrcoef(model["z"][sel], dem[sel])[0, 1]) if out["n"] > 2 else float("nan")
    return out


def _select(model, dem, h_water, roles):
    return (np.asarray(roles) == "valid") & np.isfinite(dem) & (dem > h_water + WATER_MARGIN) & np.isfinite(model["z"])


def bottom_errors(model: dict, dem: np.ndarray, h_water: float, roles: np.ndarray) -> np.ndarray:
    """Błędy (model - NMT) na tych samych pikselach co `bottom_vs_dem` (do histogramu)."""
    sel = _select(model, dem, h_water, roles)
    return model["z"][sel] - dem[sel]


def dem_to_grid(tiles, grid, offset: float = 0.0, min_cover: float = MIN_COVER) -> np.ndarray:
    """Uśrednia arkusze NMT 1 m do siatki modelu: średnia ważnych komórek, NaN gdy pokrycie < `min_cover`.

    `tiles`: iterowalne (tablica, Affine, nodata). `offset` [m] dodawany raz do średniej (KRON86 -> EVRF2007).
    Pokrycie = liczba ważnych komórek / (res/|piksel|)^2; nakładające się arkusze liczą komórki podwójnie, a pokrycie
    jest obcinane do 1 (średnia pozostaje poprawna, bo oba arkusze opisują to samo miejsce).
    """
    xmin, ymin, xmax, ymax = grid.bounds()
    res = grid.transform.a
    s = np.zeros(grid.height * grid.width)
    c = np.zeros(grid.height * grid.width)
    full = 0.0
    for arr, tr, nd in tiles:
        h, w = arr.shape
        cols, rows = np.meshgrid(np.arange(w), np.arange(h))
        x = tr.c + (cols + 0.5) * tr.a
        y = tr.f + (rows + 0.5) * tr.e
        gc = np.floor((x - xmin) / res).astype(int)
        gr = np.floor((ymax - y) / res).astype(int)
        ok = np.isfinite(arr) & (gc >= 0) & (gc < grid.width) & (gr >= 0) & (gr < grid.height)
        if nd is not None:
            ok &= arr != nd
        idx = (gr * grid.width + gc)[ok]
        s += np.bincount(idx, weights=arr[ok].astype("float64"), minlength=s.size)
        c += np.bincount(idx, minlength=s.size)
        full = (res / abs(tr.a)) * (res / abs(tr.e))
    cover = np.minimum(c / full, 1.0) if full else np.zeros_like(c)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / c
    out = np.where((c > 0) & (cover >= min_cover), mean + offset, np.nan)
    return out.reshape(grid.height, grid.width)


def bottom_change(pre: dict, post: dict) -> dict:
    """Zmiana dna pre_flood -> post_flood: Δz = z_post - z_pre tam, gdzie oba modele mają `z`.

    share_significant = udział pikseli z |Δz| > unc_pre + unc_post (suma niepewności, zachowawczo liniowo);
    zwraca też statystyki Δz i histogram (kosze 0,1 m w [-1, 1], skrajne dołączone do końców).
    """
    both = np.isfinite(pre["z"]) & np.isfinite(post["z"])
    dz = (post["z"] - pre["z"])[both]
    thr = (pre["unc"] + post["unc"])[both]
    n = int(both.sum())
    if n == 0:
        return {"n": 0, "share_significant": float("nan")}
    sig = np.abs(dz) > thr
    edges = np.round(np.arange(-1.0, 1.0001, 0.1), 1)
    hist, _ = np.histogram(np.clip(dz, -1.0, 1.0), bins=edges)
    return {"n": n, "share_significant": float(np.nanmean(sig)), "n_significant": int(np.nansum(sig)),
            "mean_dz": float(dz.mean()), "median_dz": float(np.median(dz)), "mean_abs_dz": float(np.abs(dz).mean()),
            "mean_threshold": float(np.nanmean(thr)),
            "hist": {"edges": edges.tolist(), "counts": hist.tolist(), "note": "Δz obcięte do [-1, 1] m"}}


def choose_model(share_significant: float) -> dict:
    """Okres modelu dla aplikacji: „post_flood" gdy share_significant >= 5 %, inaczej „all" (domyślny)."""
    if share_significant >= SHARE_THRESHOLD:
        period = "post_flood"
        reason = (f"Istotna zmiana dna po powodzi: {100 * share_significant:.1f} % pikseli wspólnych ma |Δz| większe niż suma "
                  f"niepewności (próg {100 * SHARE_THRESHOLD:.0f} %), więc aplikacja używa modelu po powodzi.")
    else:
        period = "all"
        reason = (f"Brak istotnej zmiany dna po powodzi: {100 * share_significant:.1f} % pikseli wspólnych ma |Δz| większe niż "
                  f"suma niepewności (poniżej progu {100 * SHARE_THRESHOLD:.0f} %), więc aplikacja używa modelu z całego okresu.")
    return {"period": period, "reason": reason, "share_significant": float(share_significant)}


def describe(values) -> dict:
    """Rozkład: n, min, p10, mediana, p90, max."""
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"n": 0}
    q = np.percentile(v, [10, 50, 90])
    return {"n": int(v.size), "min": float(v.min()), "p10": float(q[0]), "median": float(q[1]),
            "p90": float(q[2]), "max": float(v.max())}
