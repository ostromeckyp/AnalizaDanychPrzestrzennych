"""13 - Budżet błędu pionowego modelu dna wg pasm rzędnej.

Co robi: zestawia w trzech pasmach (<192,9; 192,9-194,8; 194,8+) błąd modelu dna z trzech źródeł w metrach (roczny
  hold-out, LiDAR, mapa KŻ), a jako kontekst dodaje stosunek objętości model/tabela i niepewność poziomów wody.
  Zapisuje eval/error_budget.json.
Dlaczego tak: żadne pojedyncze źródło nie pokrywa całego zakresu; zakres [min MAE, max MAE] z dostępnych źródeł jest
  uczciwszy niż jedna liczba. Pasmo <192,9 nie dostaje liczby: model nie ma tam dolnej granicy dna (sprawdzi to echosonda).
  Pięć kontroli to nie pięć niezależnych źródeł: trzy są na danych niezależnych od satelity (LiDAR, KŻ, objętość).
Wejście → wyjście: eval/{holdout,bottom_vs_nmt,kz_points,volume,levels}.json (+ opcjonalnie kz_loo.json) → eval/error_budget.json.
  Użycie: uv run python 13_error_budget.py (sekundy; nie czyta rastrów).
Jak to obronić: wszystkie liczby pochodzą z JSON-ów wejściowych; `lidar_note` mówi, że bias LiDAR może zawierać
  przesunięcie RZGW<->EVRF2007 i że liczba się przez to nie zmienia (MAE wprost).
"""
import json
import logging
import sys

from mielizna import budget
from mielizna.config import data_path

log = logging.getLogger("13")
NO_DATA_NOTE = "model nie ma dolnej granicy dna; sprawdzi to echosonda"
LIDAR_NOTE = ("Obciążenie względem LiDAR może zawierać przesunięcie układów wysokościowych RZGW↔EVRF2007 "
              "(hipoteza, niezmierzona). MAE bierzemy bez korekty o to przesunięcie.")
SOURCE_PL = {"holdout": "hold-out", "lidar": "LiDAR", "kz": "mapa KŻ"}


def fmt(x: float, nd: int = 2) -> str:
    """Liczba z przecinkiem dziesiętnym i prawdziwym minusem (U+2212)."""
    return f"{x:.{nd}f}".replace(".", ",").replace("-", "−")


def sfmt(x: float, nd: int = 2) -> str:
    """Liczba ze znakiem: plus dla dodatnich, U+2212 dla ujemnych."""
    return ("+" if x > 0 else "") + fmt(x, nd)


def nfmt(n: int) -> str:
    """Liczba całkowita z wąską nierozdzielającą spacją (U+202F) jako separatorem tysięcy."""
    return f"{int(n):,}".replace(",", "\u202f")


def _stat(st: dict) -> dict:
    """Wycina {n, mae, bias} z bloku statystyk źródła (puste n=0 zostaje samo)."""
    if not st or st.get("n", 0) == 0:
        return {"n": 0}
    return {k: st[k] for k in ("n", "mae", "bias") if k in st}


def _note(band: str, comb: dict) -> str:
    srcs = comb["sources"]
    if band == "<192.9":
        return NO_DATA_NOTE
    if comb["range_m"] is None:
        return "brak źródeł z wystarczającą liczbą punktów"
    parts = [f"{SOURCE_PL[k]}: MAE {fmt(v['mae'])} m (n = {nfmt(v['n'])})" for k, v in srcs.items() if "excluded" not in v]
    note = "Zakres z MAE źródeł: " + "; ".join(parts) + "."
    small = [SOURCE_PL[k] for k, v in srcs.items() if "excluded" in v]
    if small:
        note += f" Pominięto (n<{budget.MIN_N}): {', '.join(small)}."
    signs = {k: v["bias"] > 0 for k, v in srcs.items() if "excluded" not in v and v.get("bias")}
    if len(set(signs.values())) > 1:
        note += " Znaki obciążenia źródeł się różnią (" + ", ".join(
            f"{SOURCE_PL[k]} {sfmt(srcs[k]['bias'])} m" for k in signs) + ")."
    return note


def _kz_loo_deep(kz_loo: dict | None) -> dict | None:
    """Wycina {n, mae, p5, p95} z kz_loo.below_192_9; None, gdy brak pliku albo pasmo puste."""
    d = (kz_loo or {}).get("below_192_9")
    if not d or d.get("n", 0) == 0:
        return None
    return {k: d[k] for k in ("n", "mae", "p5", "p95")}


def _loo_note(loo: dict) -> str:
    return (f"Błąd interpolacji mapy KŻ (punkt odłożony, n = {nfmt(loo['n'])}): MAE {fmt(loo['mae'])} m; "
            "to błąd mapy względem samej siebie, nie modelu. " + NO_DATA_NOTE[0].upper() + NO_DATA_NOTE[1:] + ".")


def build(ho: dict, bvn: dict, kz: dict, vol: dict, lv: dict, kz_loo: dict | None = None) -> dict:
    """Składa error_budget.json z już wczytanych JSON-ów oceny (czysta funkcja, bez dysku).

    `kz_loo` (opcjonalny): pasmo <192,9 dostaje osobne pole `kz_loo`; nie wchodzi do `combine_band`
    (to błąd interpolacji mapy względem samej siebie, nie modelu względem odniesienia)."""
    bands = {}
    for band, (lo, hi) in budget.BANDS.items():
        src = {"holdout": _stat(ho["by_band"][band]["vertical"]),
               "lidar": _stat(bvn["all_by_band"][band]),
               "kz": _stat(kz["budget_bands"][band])}
        comb = budget.combine_band(src)
        if band == "<192.9":  # R5: bez liczby; KŻ tylko jako kontekst
            comb["range_m"] = None
            comb["dominant"] = None
        bands[band] = {**comb, "volume": budget.volume_context(vol["layers"], lo, hi), "note": _note(band, comb)}
        loo = _kz_loo_deep(kz_loo) if band == "<192.9" else None
        if loo:
            bands[band]["kz_loo"] = loo
            bands[band]["note"] = _loo_note(loo)

    hv = ho["holdout"]["vertical"]
    lid = bvn["all_by_band"]
    lid_parts = [f"{budget.BAND_LABELS[b]}: MAE {fmt(v['mae'])} m, obciążenie {sfmt(v['bias'])} m "
                 f"(n = {nfmt(v['n'])})" for b, v in lid.items() if v.get("n", 0) > 0]
    kzb = {b: v for b, v in kz["budget_bands"].items() if v.get("n", 0) >= budget.MIN_N}
    kz_parts = [f"{budget.BAND_LABELS[b]}: MAE {fmt(v['mae'])} m (n = {nfmt(v['n'])})" for b, v in kzb.items()]
    ratios = [(b, d["volume"]["ratio"]) for b, d in bands.items() if d["volume"]]
    vol_parts = [f"{fmt(d['volume']['ratio'], 3)} dla {fmt(d['volume']['covered'][0], 1)}–"
                 f"{fmt(d['volume']['covered'][1], 1)} m" for d in bands.values() if d["volume"]]
    vol_txt = ("model/tabela: " + "; ".join(vol_parts)) if vol_parts else "brak warstw"
    sig = lv["h_sigma_by_method"]
    rb = lv["control_r_2025"]["by_method"].get("B", {})
    avb = lv["a_vs_b"]
    level_ctx = {"h_sigma_median_m": {m: v["median"] for m, v in sig.items()},
                 "a_vs_b": {"mae": avb["mae"], "bias": avb["bias"], "n": avb.get("n")},
                 "control_r_2025_B": {k: rb[k] for k in ("n", "mae", "bias") if k in rb},
                 "volume_ratio_by_band": {b: r for b, r in ratios}}
    lvl_txt = f"niepewność poziomu B {fmt(sig['B']['median'])} m; A vs B: MAE {fmt(avb['mae'])} m"
    if rb.get("n"):
        lvl_txt += f"; kontrola R 2025 dla B: MAE {fmt(rb['mae'])} m"
    checks = [
        {"name": "Roczny hold-out", "compared_with": "poziom wody sceny testowej (pomiar B/R), model bez roku sceny",
         "result": f"MAE {fmt(hv['mae'])} m, obciążenie {sfmt(hv['bias'])} m (zależy od proporcji stron linii "
                   f"brzegowej; n = {nfmt(hv['n'])} pikseli, {ho['n_test_scenes']} scen)"},
        {"name": "LiDAR", "compared_with": "NMT z lotniczego skanowania: teren odsłonięty przy brzegu "
                                          "(suchy w dniu nalotu), model z całego okresu",
         "result": "; ".join(lid_parts) if lid_parts else "brak danych"},
        {"name": "Mapa KŻ", "compared_with": "punkty głębokości z mapy KŻ (2023), model sprzed powodzi; poniżej "
                                             "196 m praktycznie równy modelowi z całego okresu "
                                             "(pasma z co najmniej 5 punktami)",
         "result": "; ".join(kz_parts) if kz_parts else "brak pasm z co najmniej 5 punktami"},
        {"name": "Objętość", "compared_with": "tabela pojemności KŻ", "result": vol_txt},
        {"name": "Poziomy wody", "compared_with": "poziomy z metod A/B/C i kontrola R", "result": lvl_txt},
    ]
    return {"bands": bands, "level_context": level_ctx, "checks": checks,
            "leakage_note": ho["leakage_note"],
            "lidar_note": LIDAR_NOTE}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ev = data_path("processed") / "eval"
    load = lambda n: json.loads((ev / n).read_text(encoding="utf-8"))  # noqa: E731
    loo_path = ev / "kz_loo.json"
    kz_loo = json.loads(loo_path.read_text(encoding="utf-8")) if loo_path.exists() else None
    res = build(load("holdout.json"), load("bottom_vs_nmt.json"), load("kz_points.json"), load("volume.json"),
                load("levels.json"), kz_loo)
    out = ev / "error_budget.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    for b, d in res["bands"].items():
        log.info("%s: range=%s dominant=%s", b, d["range_m"], d["dominant"])
    log.info("zapisano %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
