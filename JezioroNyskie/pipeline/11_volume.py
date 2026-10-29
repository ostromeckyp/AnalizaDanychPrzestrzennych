"""11 - Objętość: model dna vs tabela pojemność ↔ rzędna (KŻ, ta sama, którą wariant B zamienia komunikaty RZGW na h_t).

Co robi: (1) dla warstw co 0,5 m od 193,3 do 197,8 m liczy przyrost objętości wody z modelu (środek i przedział z_min/z_max)
  i z tabeli; (2) z tabeli i części dna o znanej rzędnej szacuje średnią rzędną rdzenia (piksele zawsze mokre);
  (3) dla porównania podaje średnią powierzchni KŻ (orientacyjnej poniżej 192,5 m) na tych samych pikselach rdzenia;
  (4) rysuje docs/img/eval-objetosc.png.
Dlaczego tak: patrz mielizna/volume.py. Dolna granica warstw (193,3 m) leży nad z_max rdzenia, więc ΔV nie zależy od jego
  nieznanej głębokości. Model to okres wybrany dla aplikacji (eval/model_choice.json).
Wejście → wyjście: data/processed/{model/<okres>/, eval/model_choice.json, kz/kz_surface.tif (opcjonalnie)},
  data/reference/kz_pojemnosc_rzedna.csv → data/processed/eval/volume.json, docs/img/eval-objetosc.png.
  Użycie: uv run python 11_volume.py
"""
import json
import logging
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

from mielizna import bottom, volume
from mielizna.capacity import level_to_capacity, load_table
from mielizna.config import data_path

log = logging.getLogger("11")
IMG = Path(__file__).resolve().parents[1] / "docs" / "img"
EDGES = np.round(np.arange(193.3, 197.81, 0.5), 2)  # [m] warstwy ΔV; start nad z_max rdzenia
BANDS = {"193.3-194.8": (193.3, 194.8), "194.8-196.3": (194.8, 196.3), "196.3-197.8": (196.3, 197.8)}
H_CORE = (193.5, 194.0, 194.5, 195.0, 196.0, 197.0)  # poziomy do szacunku dna rdzenia
H_CORE_MAIN = 194.0  # poziom w pasie zgodności ΔV (193,3–194,8 m), z którego podajemy wynik główny
TABLE_STEP = 0.5  # [mln m³] rozdzielczość wartości w tabeli KŻ; ΔV z dwóch odczytów ma błąd zaokrąglenia ≤ TABLE_STEP


def band_summary(rows: list[dict]) -> dict:
    out = {}
    for name, (lo, hi) in BANDS.items():
        sel = [r for r in rows if r["h1"] >= lo - 1e-6 and r["h2"] <= hi + 1e-6]
        vt, vm = sum(r["dv_table"] for r in sel), sum(r["dv_model"] for r in sel)
        out[name] = {"dv_table": vt, "dv_model": vm, "dv_model_min": sum(r["dv_model_min"] for r in sel),
                     "dv_model_max": sum(r["dv_model_max"] for r in sel), "ratio": vm / vt, "diff_pct": (vm / vt - 1) * 100,
                     "table_round_pct": TABLE_STEP / vt * 100}
    return out


def plot(rows: list[dict], path: Path) -> None:
    x = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.bar(x - 0.2, [r["area_table_km2"] for r in rows], 0.4, label="tabela pojemności (ΔV/Δh)", color="#444")
    mid = np.array([r["area_model_km2"] for r in rows])
    lo = mid - np.array([r["dv_model_min"] / (r["h2"] - r["h1"]) for r in rows])
    hi = np.array([r["dv_model_max"] / (r["h2"] - r["h1"]) for r in rows]) - mid
    ax.bar(x + 0.2, mid, 0.4, yerr=[lo, hi], capsize=3, label="model dna (przedział z_min/z_max)", color="#5aa3c8")
    ax.set_xticks(x, [f"{r['h1']:.1f}–{r['h2']:.1f}" for r in rows], rotation=30, ha="right")
    ax.set_xlabel("warstwa wody [m n.p.m.]")
    ax.set_ylabel("średnia powierzchnia warstwy [km²]")
    ax.set_title("Przyrost objętości na 1 m poziomu: model vs tabela pojemności")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    proc = data_path("processed")
    period = json.loads((proc / "eval" / "model_choice.json").read_text(encoding="utf-8"))["period"]
    model, _ = bottom.read_model(proc / "model" / period)
    b = volume.bottom_bounds(model)
    table = load_table()
    vol = lambda h: float(level_to_capacity(h, table=table))  # noqa: E731

    zmax_core = b["high"][b["core"]]
    above = float((zmax_core > EDGES[0]).mean())
    if above > 0.01:
        log.warning("%.1f %% pikseli rdzenia ma z_max > %.1f m: ΔV dolnej warstwy zależy od ich głębokości", above * 100, EDGES[0])

    rows = volume.layer_table(b, vol, EDGES)
    cores = [volume.core_bottom(b, h, vol(h)) for h in H_CORE]
    main_core = next(c for c in cores if c["h"] == H_CORE_MAIN)

    kz = None
    kz_path = proc / "kz" / "kz_surface.tif"
    if kz_path.exists():
        with rasterio.open(kz_path) as ds:
            ks = ds.read(1).astype("float64")
        m = b["core"] & np.isfinite(ks)
        kz = {"n_px": int(m.sum()), "share_of_core": float(m.sum() / b["core"].sum()), "mean": float(ks[m].mean()),
              "median": float(np.median(ks[m])), "note": "powierzchnia KŻ (TIN z punktów i poziomic); poniżej 192,5 m mapa jest orientacyjna"}

    res = {"period": period, "cell_m2": volume.CELL_M2, "table": "data/reference/kz_pojemnosc_rzedna.csv",
           "core_px": int(b["core"].sum()), "core_zmax_median": float(np.median(zmax_core)),
           "core_share_zmax_above_first_edge": above,
           "layers": rows, "bands": band_summary(rows), "core_bottom": cores, "core_bottom_main": main_core,
           "kz_core": kz,
           "note": "ΔV = przyrost objętości między poziomami; tabela i h_t wariantu B w tym samym (nieznanym) układzie wysokości; "
                   "z_core_mean = h − (V_tabela − V_reszta)/A_rdzenia, wiarygodne tylko tam, gdzie ΔV modelu zgadza się z tabelą"}
    out = proc / "eval" / "volume.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    IMG.mkdir(parents=True, exist_ok=True)
    plot(rows, IMG / "eval-objetosc.png")
    log.info("bands: %s", {k: round(v["ratio"], 3) for k, v in res["bands"].items()})
    log.info("dno rdzenia (h=%.1f): %.2f m; KŻ: %s", H_CORE_MAIN, main_core["z_core_mean"], kz and round(kz["mean"], 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
