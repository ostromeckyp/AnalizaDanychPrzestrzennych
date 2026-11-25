"""Łączenie granic dna z satelity (po kalibracji) z powierzchnią KŻ tam, gdzie satelita nie ma dolnej granicy.

Co robi: `merge_kz` dla pikseli „zawsze woda” (z_lo = −∞) ze skończoną rzędną KŻ wpisuje dolną granicę
  z_lo = kz − P95 i zawęża górną: z_hi = min(z_hi, kz − P5), gdzie P5/P95 to kwantyle błędu LOO (odczyt − punkt).
  `zone_shares` liczy udziały stref (bezpieczna / ryzykowna / zbyt płytka) dla poziomu h.
Dlaczego tak: prawdziwe dno = kz − błąd, więc przy błędzie z [P5; P95] leży w [kz − P95; kz − P5]. Granica górna
  nie może wyjść ponad kalibrowaną granicę satelity (obie są prawdziwe naraz).
Sprzeczność: kz − P95 > z_hi (KŻ twierdzi, że dno jest płycej, niż pozwala satelita) → zostaje satelita
  (z_lo = −∞, z_hi bez zmian), source = satelita, conflict = True. Satelita wygrywa, bo KŻ to mapa amatorska.
Wejście → wyjście: tablice z_lo, z_hi, kz (NaN = brak) i P5, P95 → (z_lo, z_hi, source uint8, conflict bool).
Jak to obronić: testy przypadków (skończony piksel, wypełnienie, ograniczenie z_hi, sprzeczność, brak KŻ).
  `zone_shares` powtarza regułę backend/app/depth.py:classify (pipeline nie zależy od backendu).
"""
from __future__ import annotations

import numpy as np

EPS = 1e-6


def merge_kz(z_lo, z_hi, kz, p5: float, p95: float):
    """Zwraca (z_lo, z_hi, source, conflict); source: 0 = satelita, 1 = KŻ; nie zmienia wejść."""
    lo = np.array(z_lo, dtype=np.float64)
    hi = np.array(z_hi, dtype=np.float64)
    kz = np.asarray(kz, dtype=np.float64)
    cand = np.isneginf(lo) & np.isfinite(kz)
    with np.errstate(invalid="ignore"):
        new_lo = kz - p95
        new_hi = np.minimum(hi, kz - p5)
        conflict = cand & (new_lo > hi)
    use = cand & ~conflict
    lo = np.where(use, new_lo, lo)
    hi = np.where(use, new_hi, hi)
    return lo, hi, use.astype(np.uint8), conflict


def zone_shares(z_lo, z_hi, mask, h: float, draft: float, margin: float) -> dict:
    """Udziały {safe, risk, danger} wśród pikseli `mask` (reguła backend/app/depth.py:classify, §6.4)."""
    z_lo, z_hi = np.asarray(z_lo, float), np.asarray(z_hi, float)
    with np.errstate(invalid="ignore"):
        d_lo, d_hi = h - z_hi, h - z_lo
        danger = d_hi < draft
        safe = (d_lo >= draft + margin - EPS) & ~danger
    n = int(np.asarray(mask).sum())
    if n == 0:
        return {"safe": None, "risk": None, "danger": None, "n": 0}
    s, d = int((safe & mask).sum()), int((danger & mask).sum())
    return {"safe": s / n, "risk": (n - s - d) / n, "danger": d / n, "n": n}
