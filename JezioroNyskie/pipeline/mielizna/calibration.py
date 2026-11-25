"""Kalibracja przedziałów dna [z_min, z_max] z rocznego hold-outu (jednostronne poszerzenia per pasmo rzędnych).

Co robi: z reszt hold-outu (o ile prawdziwe dno wychodzi poza przedział) liczy dla każdego pasma budżetu poszerzenia
  δ_lo i δ_hi (P95) i stosuje je do granic skończonych: z_lo − δ_lo, z_hi + δ_hi. Liczy też pokrycie przed i po.
Dlaczego tak: przedział z modelu obejmuje dno tylko w ok. 17 % pikseli brzegowych hold-outu. Reszty z modeli foldów
  (poza próbą) są uczciwsze niż z modelu serwowanego, a poszerzenie jednostronne nie zakłada symetrii błędu.
Wejście → wyjście: reszty max(0, z_min − h) i max(0, h − z_max) per pasmo → `deltas`, `coverage`; rastry granic → `apply`.
Jak to obronić: puste pasmo daje δ = 0 z notą „brak pikseli” (nigdy NaN w rastrach); pasmo „<192.9” nie ma pikseli
  hold-outu (poziomy scen ≥ 192,9 m), więc pożycza δ pasma „192.9-194.8”; ±∞ i NaN zostają nietknięte.
  P95 każdej strony osobno daje łączne pokrycie ≥ ok. 90 %, nie dokładnie 90 %.
"""
from __future__ import annotations

import numpy as np

from . import budget

BORROW_FROM = "192.9-194.8"
NO_PIXELS = "brak pikseli"


def deltas(res_lo_by_band: dict[str, np.ndarray], res_hi_by_band: dict[str, np.ndarray], q: float = 95) -> dict[str, dict]:
    """Poszerzenia {pasmo: {delta_lo, delta_hi, n, note}}: percentyl `q` reszt; puste pasmo → 0 i nota „brak pikseli”."""
    out = {}
    for b in budget.BANDS:
        lo = np.asarray(res_lo_by_band.get(b, []), float)
        hi = np.asarray(res_hi_by_band.get(b, []), float)
        n = int(len(lo))
        if n == 0:
            out[b] = {"delta_lo": 0.0, "delta_hi": 0.0, "n": 0, "note": NO_PIXELS}
        else:
            out[b] = {"delta_lo": float(np.percentile(lo, q)), "delta_hi": float(np.percentile(hi, q)), "n": n,
                      "note": None}
    return out


def coverage(res_lo_by_band: dict[str, np.ndarray], res_hi_by_band: dict[str, np.ndarray], d: dict) -> dict:
    """Udział pikseli z dnem w przedziale przed i po poszerzeniu: ogółem i per pasmo (parami po pikselach)."""
    def share(ok, n):
        return float(ok / n) if n else None

    tot = {"n": 0, "before": 0, "after": 0}
    bands = {}
    for b in budget.BANDS:
        lo = np.asarray(res_lo_by_band.get(b, []), float)
        hi = np.asarray(res_hi_by_band.get(b, []), float)
        n = len(lo)
        before = int(((lo <= 0) & (hi <= 0)).sum())
        after = int(((lo <= d[b]["delta_lo"]) & (hi <= d[b]["delta_hi"])).sum())
        bands[b] = {"before": share(before, n), "after": share(after, n), "n": int(n)}
        tot["n"] += n
        tot["before"] += before
        tot["after"] += after
    return {"overall": {"before": share(tot["before"], tot["n"]), "after": share(tot["after"], tot["n"]), "n": tot["n"]},
            "bands": bands}


def apply(z_lo: np.ndarray, z_hi: np.ndarray, d: dict) -> tuple[np.ndarray, np.ndarray]:
    """Poszerza skończone granice: z_lo − δ_lo, z_hi + δ_hi; ±∞ i NaN bez zmian.

    Pasmo piksela: środek przedziału (obie granice skończone) albo jedyna skończona granica; poniżej 192,9 m δ pasma
    „192.9-194.8”. Piksel bez skończonej granicy nie jest zmieniany.
    """
    lo, hi = np.asarray(z_lo, float), np.asarray(z_hi, float)
    flo, fhi = np.isfinite(lo), np.isfinite(hi)
    with np.errstate(invalid="ignore"):
        mid = (lo + hi) / 2
    ref = np.where(flo & fhi, mid, np.where(flo, lo, np.where(fhi, hi, np.nan)))
    dlo, dhi = np.zeros(lo.shape), np.zeros(lo.shape)
    has = np.isfinite(ref)
    band = np.full(lo.shape, "", dtype=object)
    band[has] = budget.band_of(ref[has])
    band[band == "<192.9"] = BORROW_FROM
    for b in budget.BANDS:
        m = band == b
        if m.any():
            dlo[m], dhi[m] = d[b]["delta_lo"], d[b]["delta_hi"]
    out_lo = np.where(flo, lo - dlo, lo).astype(np.asarray(z_lo).dtype if np.asarray(z_lo).dtype.kind == "f" else float)
    out_hi = np.where(fhi, hi + dhi, hi).astype(np.asarray(z_hi).dtype if np.asarray(z_hi).dtype.kind == "f" else float)
    return out_lo, out_hi
