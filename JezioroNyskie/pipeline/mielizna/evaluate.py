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
MIN_WATER_SHARE = 0.02       # dominanta histogramu arkusza uznawana za płaską wodę, gdy obejmuje >= 2 % komórek
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


def bottom_vs_dem(model: dict, dem: np.ndarray, h_water: float, roles: np.ndarray, exclude=None) -> dict:
    """Dno modelu (`z`) vs NMT na pikselach: blok „valid", NMT > h_water + 0,1 m, model ma `z`.

    `dem` jest już na siatce modelu (10 m) i w EVRF2007; `roles` to tablica „calib"/„valid" (blocks.block_role).
    `exclude` (opcjonalnie, bool) wyłącza piksele (np. żwirownię). Zwraca n, mae, rmse, bias (model - NMT),
    share_in_bounds (NMT w [z_min, z_max]), ref_std i corr; same błędy zwraca `bottom_errors`.
    """
    sel = _select(model, dem, h_water, roles, exclude)
    out = metrics(model["z"][sel], dem[sel])
    out["share_in_bounds"] = share_in_bounds(dem[sel], model["z_min"][sel], model["z_max"][sel])
    # kontekst: rozrzut NMT (RMSE stałej predykcji = ref_std) i korelacja; bez nich RMSE nie mówi, czy model cokolwiek wnosi
    out["ref_std"] = float(np.std(dem[sel])) if out["n"] else float("nan")
    out["corr"] = float(np.corrcoef(model["z"][sel], dem[sel])[0, 1]) if out["n"] > 2 else float("nan")
    return out


def _select(model, dem, h_water, roles, exclude=None):
    sel = (np.asarray(roles) == "valid") & np.isfinite(dem) & (dem > h_water + WATER_MARGIN) & np.isfinite(model["z"])
    return sel & ~exclude if exclude is not None else sel


def bottom_pairs(model: dict, dem: np.ndarray, h_water: float, roles: np.ndarray, exclude=None) -> dict:
    """Piksele użyte w `bottom_vs_dem` jako tablice (z, z_min, z_max, ref) - do zbiorczej oceny po epokach."""
    sel = _select(model, dem, h_water, roles, exclude)
    return {"z": model["z"][sel], "z_min": model["z_min"][sel], "z_max": model["z_max"][sel], "ref": dem[sel]}


def pooled_bottom(parts: list[dict]) -> dict:
    """Metryki dna (n, mae, rmse, bias, share_in_bounds) z połączonych pikseli wielu epok (piksele liczone osobno dla epoki)."""
    cat = {k: np.concatenate([p[k] for p in parts]) if parts else np.array([]) for k in ("z", "z_min", "z_max", "ref")}
    out = metrics(cat["z"], cat["ref"])
    out["share_in_bounds"] = share_in_bounds(cat["ref"], cat["z_min"], cat["z_max"])
    return out


def bottom_errors(model: dict, dem: np.ndarray, h_water: float, roles: np.ndarray, exclude=None) -> np.ndarray:
    """Błędy (model - NMT) na tych samych pikselach co `bottom_vs_dem` (do histogramu)."""
    sel = _select(model, dem, h_water, roles, exclude)
    return model["z"][sel] - dem[sel]


def sheet_water_surface(arr: np.ndarray, nodata=None, min_share: float = MIN_WATER_SHARE) -> float:
    """Powierzchnia wody arkusza NMT: dominanta (zaokrąglenie do 0,01 m) wartości; NaN, gdy dominanta < `min_share` komórek.

    Dlaczego tak: NMT z LiDAR ma jezioro „spłaszczone hydrologicznie" do jednej rzędnej na arkusz (nie zawsze równej poziomowi
    wody z epochs.csv: różnice do ok. 1 m). Płaska woda to wielka dominanta histogramu; arkusz bez wody (sam ląd) nie ma
    wyraźnej dominanty, więc zwraca NaN i nic nie jest wycinane.
    """
    v = arr[np.isfinite(arr)]
    if nodata is not None:
        v = v[v != nodata]
    if v.size == 0:
        return float("nan")
    vals, cnt = np.unique(np.round(v, 2), return_counts=True)
    return float(vals[cnt.argmax()]) if cnt.max() / v.size >= min_share else float("nan")


def dem_to_grid(tiles, grid, offset: float = 0.0, min_cover: float = MIN_COVER, water_margin=None,
                min_std=None, return_info: bool = False):
    """Uśrednia arkusze NMT 1 m do siatki modelu: średnia ważnych komórek, NaN gdy pokrycie < `min_cover`.

    `tiles`: iterowalne (tablica, Affine, nodata); wszystkie arkusze muszą mieć tę samą rozdzielczość. `offset` [m] dodawany
    raz do średniej (KRON86 -> EVRF2007). Pokrycie = liczba ważnych komórek / (res/|piksel|)^2, obcięte do 1 (nakładające się
    arkusze liczą komórki podwójnie; średnia pozostaje poprawna).
    `water_margin` (np. 0,1): dla każdego arkusza wyznacza `sheet_water_surface` (w układzie natywnym) i traktuje komórki
    <= woda + margines jako nieważne (woda), więc płaska woda nie jest liczona jako ląd; `min_std` (np. 0,03 m): piksel,
    którego komórki 1 m mają odchylenie standardowe mniejsze niż próg (płaski), dostaje NaN.
    `return_info=True` zwraca (średnia, [powierzchnie wody arkuszy]).
    """
    xmin, ymin, xmax, ymax = grid.bounds()
    res = grid.transform.a
    s = np.zeros(grid.height * grid.width)
    s2 = np.zeros_like(s)
    c = np.zeros_like(s)
    full = 0.0
    steps = set()
    waters = []
    for arr, tr, nd in tiles:
        steps.add((round(abs(tr.a), 6), round(abs(tr.e), 6)))
        if len(steps) > 1:
            raise ValueError(f"arkusze NMT o różnych rozdzielczościach: {sorted(steps)}")
        h, w = arr.shape
        cols, rows = np.meshgrid(np.arange(w), np.arange(h))
        x = tr.c + (cols + 0.5) * tr.a
        y = tr.f + (rows + 0.5) * tr.e
        gc = np.floor((x - xmin) / res).astype(int)
        gr = np.floor((ymax - y) / res).astype(int)
        ok = np.isfinite(arr) & (gc >= 0) & (gc < grid.width) & (gr >= 0) & (gr < grid.height)
        if nd is not None:
            ok &= arr != nd
        sw = sheet_water_surface(arr, nd) if water_margin is not None else float("nan")
        waters.append(sw)
        if np.isfinite(sw):
            ok &= arr > sw + water_margin
        idx = (gr * grid.width + gc)[ok]
        v = arr[ok].astype("float64")
        s += np.bincount(idx, weights=v, minlength=s.size)
        s2 += np.bincount(idx, weights=v * v, minlength=s.size)
        c += np.bincount(idx, minlength=s.size)
        full = (res / abs(tr.a)) * (res / abs(tr.e))
    cover = np.minimum(c / full, 1.0) if full else np.zeros_like(c)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / c
        std = np.sqrt(np.maximum(s2 / c - mean ** 2, 0.0))
    good = (c > 0) & (cover >= min_cover)
    if min_std is not None:
        good &= std >= min_std
    out = np.where(good, mean + offset, np.nan).reshape(grid.height, grid.width)
    return (out, waters) if return_info else out


def bottom_change(pre: dict, post: dict, common=None) -> dict:
    """Zmiana dna pre_flood -> post_flood: Δz = z_post - z_pre tam, gdzie oba modele mają `z`.

    share_significant = liczba pikseli z |Δz| > unc_pre + unc_post (suma niepewności) / liczba pikseli akwenu wspólnego `common`
    (bool; obserwowane w obu okresach; brak `common` = tylko piksele z z w obu modelach); `share_significant_overlap` dzieli
    przez piksele z z w obu modelach (wąski pas przedziałów);
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
    n_common = int(common.sum()) if common is not None else n
    return {"n": n, "n_common": n_common, "share_significant": float(np.nansum(sig) / n_common),
            "share_significant_overlap": float(np.nanmean(sig)), "n_significant": int(np.nansum(sig)),
            "mean_dz": float(dz.mean()), "median_dz": float(np.median(dz)), "mean_abs_dz": float(np.abs(dz).mean()),
            "mean_threshold": float(np.nanmean(thr)),
            "hist": {"edges": edges.tolist(), "counts": hist.tolist(), "note": "Δz obcięte do [-1, 1] m"}}


def choose_model(share_significant: float) -> dict:
    """Okres modelu dla aplikacji: „post_flood" gdy share_significant >= 5 %, inaczej „all" (domyślny)."""
    if share_significant >= SHARE_THRESHOLD:
        period = "post_flood"
        reason = (f"Istotna zmiana dna po powodzi: {100 * share_significant:.1f} % akwenu wspólnego ma |Δz| większe niż suma "
                  f"niepewności (próg {100 * SHARE_THRESHOLD:.0f} %), więc aplikacja używa modelu po powodzi.")
    else:
        period = "all"
        reason = (f"Brak istotnej zmiany dna po powodzi: {100 * share_significant:.1f} % akwenu wspólnego ma |Δz| większe niż "
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
