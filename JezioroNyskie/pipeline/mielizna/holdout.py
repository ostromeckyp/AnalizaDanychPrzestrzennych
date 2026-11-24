"""Funkcje pomocnicze rocznego testu hold-out modelu dna (rok poza treningiem).

Co robi: dzieli sceny na foldy rocznych (trening bez roku fałdy, test = sceny z poziomem z pomiaru B/R), przewiduje maskę
  wody ze zbudowanego na treningu modelu dla poziomu sceny testowej i porównuje ją z obserwacją: IoU, odległość linii
  brzegowych oraz błąd pionowy na pikselach brzegowych (rzędna dna z modelu − poziom wody sceny).
Dlaczego tak: na linii brzegowej sceny dno leży na poziomie wody, więc z − h to bezpośredni błąd rzędnej, a poziom h
  pochodzi spoza modelu. Piksele brzegowe bez obu granic nie znikają: wchodzą do mianownika jako `share_no_pred`.
Wejście → wyjście: DataFrame scen (`bottom.select_scenes`), słowniki modelu (`bottom.read_model`), maski uint8
  {0 ląd, 1 woda, 255 nieznane} → foldy, maski, statystyki.
Jak to obronić: każda funkcja ma test na ręcznie zbudowanej, małej tablicy; piksel sprzeczny (UNRESOLVED) daje 255, nie 0.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import kz_compare, shoreline, volume


@dataclass
class Fold:
    year: int
    train: np.ndarray  # indeksy wierszy `sel`
    test: np.ndarray


def year_folds(sel: pd.DataFrame, years=range(2020, 2027), test_methods=("B", "R")) -> list[Fold]:
    """Foldy roczne: test = sceny roku z `h_method` ∈ `test_methods`; trening = wszystkie sceny innych lat.

    Sceny roku fałdy o innej metodzie poziomu (np. A) nie trafiają ani do testu, ani do treningu (ten sam rok = przeciek).
    Rok bez scen testowych jest pomijany.
    """
    yr = sel["date"].astype(str).str[:4].astype(int).to_numpy()
    meth = sel["h_method"].to_numpy()
    folds = []
    for y in years:
        test = np.flatnonzero((yr == y) & np.isin(meth, list(test_methods)))
        if len(test) == 0:
            continue
        folds.append(Fold(int(y), np.flatnonzero(yr != y), test))
    return folds


def shore_pixels(ev: np.ndarray) -> np.ndarray:
    """Piksele wody (1) mające co najmniej jednego 4-sąsiada lądu (0); 255 nie jest lądem, skośni sąsiedzi się nie liczą."""
    land = ev == 0
    nb = np.zeros(ev.shape, bool)
    nb[1:, :] |= land[:-1, :]
    nb[:-1, :] |= land[1:, :]
    nb[:, 1:] |= land[:, :-1]
    nb[:, :-1] |= land[:, 1:]
    return (ev == 1) & nb


def predict_water(model: dict, h: float) -> tuple[np.ndarray, np.ndarray]:
    """Maska wody (0/1/255) dla poziomu `h` i maska pikseli „niepewnych” (low < h < high).

    Woda, gdy środek dna < h. Piksel poza modelem albo bez żadnej granicy (UNRESOLVED: z, z_min, z_max NaN, czyli low = −inf
    i high = +inf) dostaje 255, a nie 0: nie wiemy, więc nie twierdzimy, że to ląd.
    """
    b = volume.bottom_bounds(model)
    unknown = np.isnan(b["mid"]) | (np.isneginf(b["low"]) & np.isposinf(b["high"]))
    pred = np.where(b["mid"] < h, 1, 0).astype("uint8")
    pred[unknown] = 255
    uncertain = (b["low"] < h) & (h < b["high"]) & ~unknown
    return pred, uncertain


def vertical_errors(model: dict, shore: np.ndarray, h: float) -> dict:
    """Błąd pionowy z − h na pikselach brzegowych, które mają obie granice (skończone z_min i z_max).

    Zwraca `err`, `in_bounds` (z_min ≤ h ≤ z_max), `n_shore` (wszystkie piksele brzegowe) i `n_pred` (z obiema granicami).
    """
    zmin, zmax = np.asarray(model["z_min"], float), np.asarray(model["z_max"], float)
    z = np.asarray(model["z"], float)
    ok = shore & np.isfinite(zmin) & np.isfinite(zmax) & np.isfinite(z)
    return {"err": z[ok] - h, "in_bounds": (zmin[ok] <= h) & (h <= zmax[ok]),
            "n_shore": int(shore.sum()), "n_pred": int(ok.sum())}


def iou(pred: np.ndarray, ref: np.ndarray, zone: np.ndarray) -> float:
    """IoU wody na pikselach `zone`, w których obie maski ≠ 255; pusty mianownik → NaN."""
    valid = zone & (pred != 255) & (ref != 255)
    p, r = (pred == 1) & valid, (ref == 1) & valid
    union = int((p | r).sum())
    return float((p & r).sum() / union) if union else float("nan")


def shoreline_distance(pred: np.ndarray, ref: np.ndarray, transform) -> dict:
    """Odległości linii brzegowych [m]: średnia symetryczna oraz mediana i p90 (przewidywana → obserwowana)."""
    lp, _ = shoreline.mask_to_shoreline(pred, transform)
    lr, _ = shoreline.mask_to_shoreline(ref, transform)
    nan = {"mean_sym": float("nan"), "median": float("nan"), "p90": float("nan")}
    if lp.is_empty or lr.is_empty:
        return nan
    d_pr, d_rp = kz_compare.line_distances(lp, lr), kz_compare.line_distances(lr, lp)
    if len(d_pr) == 0 or len(d_rp) == 0:
        return nan
    return {"mean_sym": float((d_pr.mean() + d_rp.mean()) / 2), "median": float(np.median(d_pr)),
            "p90": float(np.percentile(d_pr, 90))}


def summarize(err: np.ndarray, in_bounds: np.ndarray, n_shore: int) -> dict:
    """Statystyki błędu pionowego; `share_no_pred` = 1 − n / n_shore (piksele brzegowe bez obu granic). Brak danych → NaN."""
    err = np.asarray(err, float)
    n = int(len(err))
    nan = float("nan")
    a = np.abs(err)
    return {"n": n, "bias": float(err.mean()) if n else nan, "mae": float(a.mean()) if n else nan,
            "rmse": float(np.sqrt((err ** 2).mean())) if n else nan,
            "p90_abs": float(np.percentile(a, 90)) if n else nan,
            "share_in_bounds": float(np.mean(in_bounds)) if n else nan,
            "share_no_pred": float(1 - n / n_shore) if n_shore else nan}


def jsonable(x):
    """Rekurencyjnie zamienia NaN/inf na None, numpy na typy pythonowe (do `json.dump(..., allow_nan=False)`)."""
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    return x


def _dist(values: list[float]) -> dict:
    """Mediana, p10, p90 po scenach; NaN pomijane (nan-aware); brak wartości → None."""
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return {"median": None, "p10": None, "p90": None}
    return {"median": float(np.median(v)), "p10": float(np.percentile(v, 10)), "p90": float(np.percentile(v, 90))}


def aggregate(per_scene: list[dict]) -> dict:
    """Zbiera wyniki scen testowych w statystyki zbiorcze (JSON bez NaN).

    Co robi: pomija sceny z `n_shore == 0` (liczy je w `n_skipped`), skleja `err`/`in_bounds` pozostałych w `summarize`
      i liczy rozkłady (mediana, p10, p90) IoU, udziału niepewnych i odległości linii brzegowych po scenach.
    Dlaczego tak: scena bez pikseli brzegowych nic nie mówi o błędzie pionowym; NaN IoU (pusty mianownik) nie może
      zaniżać ani zawyżać rozkładu, więc jest wykluczany, a w JSON-ie nigdy nie pojawia się NaN.
    Wejście → wyjście: lista słowników sceny (n_shore, err, in_bounds, iou_zone, iou_lake, share_uncertain,
      shore_dist_median, shore_dist_p90) → słownik zbiorczy.
    Jak to obronić: test z pustą sceną i NaN w IoU sprawdza liczniki oraz `json.dumps(allow_nan=False)`.
    """
    used = [s for s in per_scene if s["n_shore"] > 0]
    err = np.concatenate([np.asarray(s["err"], float) for s in used]) if used else np.array([])
    ib = np.concatenate([np.asarray(s["in_bounds"], bool) for s in used]) if used else np.array([], bool)
    n_shore = int(sum(s["n_shore"] for s in used))
    out = {"n_test_scenes": len(used), "n_skipped": len(per_scene) - len(used),
           "vertical": summarize(err, ib, n_shore),
           "iou_zone": _dist([s["iou_zone"] for s in used]), "iou_lake": _dist([s["iou_lake"] for s in used]),
           "share_uncertain": _dist([s["share_uncertain"] for s in used]),
           "shore_dist_m": {"median": _dist([s["shore_dist_median"] for s in used])["median"],
                            "p90": _dist([s["shore_dist_p90"] for s in used])["median"]}}
    return jsonable(out)
