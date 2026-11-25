"""14 - Rastry łączone: granice satelitarne po kalibracji + głęboka powierzchnia KŻ (model/<okres>_kz/).

Co robi: czyta model satelitarny okresu z eval/model_choice.json, liczy granice z semantyką ±∞ (jak
  backend/app/depth.py:satellite_bounds), stosuje kalibrację (calibration.json), buduje głęboką powierzchnię KŻ
  (bez poziomicy 195,0 m), mierzy jej błąd metodą LOO w pikselach „zawsze woda” (z_lo = −∞) i łączy: `merge_kz`.
  Zapisuje model/<okres>_kz/{bottom_zlo,bottom_zhi,bottom_source}.tif + meta.json oraz eval/{kz_loo,kz_deep}.json.
Dlaczego tak: kolejność kalibracja → KŻ (sprzeczność liczona względem skalibrowanego z_hi). Skrypty oceny
  (08, 10, 12, 12a, 13) NIE czytają tych rastrów (test_independence): KŻ nie może oceniać modelu, którego jest częścią.
Wejście → wyjście: model/<okres>/*, eval/{model_choice,calibration}.json, kz/{kz_spot_ocr.gpkg,kz_contours.gpkg},
  reference/{kz_spot_qc.csv,zwirownia.gpkg} → rastry float32 (±inf zachowane, NaN poza modelem), uint8 source
  (bit 0 = KŻ, bit 1 = sprzeczność), meta.json (period, p5, p95, deltas, inputs_sha1), kz_loo.json, kz_deep.json.
  `inputs_sha1` = SHA-1 po bajtach kolejno: rastry satelitarne okresu (z_min, z_max, obs_count, flags), calibration.json,
  kz_spot_ocr.gpkg, kz_spot_qc.csv (jeśli jest), kz_contours.gpkg, zwirownia.gpkg.
Jak to obronić: P5/P95 z LOO (poza próbą), maska LOO = dokładnie piksele z z_lo = −∞ (zawsze woda).
  Udziały stref: „przed” = surowe granice satelity, „po” = skalibrowane + KŻ; osobno w modelu i w „zawsze woda”.
  „po, tylko dwustronne” (`zones_after_two_sided_only`, tylko do raportu, nie trafia do rastrów) = kalibracja wyłącznie
  pikseli z obiema granicami skończonymi (tam, gdzie δ zmierzono), potem ta sama reguła KŻ. Wariant serwowany
  kalibruje też granice jednostronne (decyzja użytkownika, ekstrapolacja); raport pokazuje oba.
  `contour_195_check` (tylko do raportu): pokrycie „zawsze woda” i udział pikseli z rzędną KŻ powyżej surowego z_max
  satelity dla powierzchni z poziomicą 195,0 m (jak wariant D) i bez niej (powierzchnia serwowana) — uzasadnienie
  pominięcia poziomicy. To nie jest sprzeczność reguły łączenia (ta uwzględnia P95 i kalibrację: `n_conflict`).
  Użycie: uv run python 14_kz_deep.py
"""
import hashlib
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.shutil

from mielizna import bottom, calibration, combine, kz, kz_deep, variant_d
from mielizna.config import data_path
from mielizna.grid import reference_grid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("14_kz_deep")
LEVELS, DRAFT, MARGIN = (194.5, 193.6), 0.5, 0.3
SAT_RASTERS = ("z_min", "z_max", "obs_count", "flags")


def _native(o):
    """Numpy → typy natywne Pythona (JSON); NaN/inf → None."""
    if isinstance(o, dict):
        return {str(k): _native(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_native(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(_native(obj), ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")


def _write_cog(path: Path, arr: np.ndarray, grid, nodata) -> None:
    tmp = path.with_name(path.stem + ".tmp.tif")
    with rasterio.open(tmp, "w", driver="GTiff", width=grid.width, height=grid.height, count=1, dtype=arr.dtype,
                       crs=grid.crs, transform=grid.transform, nodata=nodata) as ds:
        ds.write(arr, 1)
    rasterio.shutil.copy(tmp, path, driver="COG", compress="deflate")
    tmp.unlink()


def _sha1(paths) -> str:
    h = hashlib.sha1()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def sat_bounds(arrays: dict):
    """Granice z rastrów satelitarnych: reguła backend/app/depth.py:satellite_bounds (±∞, NaN poza modelem)."""
    obs, fl = arrays["obs_count"], arrays["flags"]
    in_model = ~((obs == 0) | (obs == 65535) | (fl == 255))
    zmin, zmax = arrays["z_min"].astype(np.float64), arrays["z_max"].astype(np.float64)
    z_lo = np.where(in_model, np.where(np.isnan(zmin), -np.inf, zmin), np.nan)
    z_hi = np.where(in_model, np.where(np.isnan(zmax), np.inf, zmax), np.nan)
    return z_lo, z_hi, in_model


def calibrate_two_sided_only(z_lo, z_hi, deltas: dict):
    """Kalibracja tylko pikseli z obiema granicami skończonymi; granice jednostronne i ±∞ zostają surowe."""
    lo_c, hi_c = calibration.apply(z_lo, z_hi, deltas)
    both = np.isfinite(z_lo) & np.isfinite(z_hi)
    return np.where(both, lo_c, z_lo), np.where(both, hi_c, z_hi)


def kz_above_zmax(surf, z_hi_raw, always) -> dict:
    """Pokrycie „zawsze woda” powierzchnią KŻ i udział pokrytych pikseli z rzędną KŻ > surowe z_max satelity."""
    cov = always & np.isfinite(surf)
    n_always, n_cov = int(always.sum()), int(cov.sum())
    with np.errstate(invalid="ignore"):
        above = int((cov & (surf > z_hi_raw)).sum())
    return {"coverage": n_cov / n_always if n_always else None, "n_covered": n_cov,
            "kz_above_zmax_share": above / n_cov if n_cov else None}


def zones(z_lo, z_hi, in_model, always):
    out = {}
    for h in LEVELS:
        out[str(h)] = {"in_model": combine.zone_shares(z_lo, z_hi, in_model, h, DRAFT, MARGIN),
                       "always_water": combine.zone_shares(z_lo, z_hi, always, h, DRAFT, MARGIN)}
    return out


def main() -> dict:
    proc = data_path("processed")
    ref = data_path("reference")
    period = json.loads((proc / "eval" / "model_choice.json").read_text(encoding="utf-8"))["period"]
    grid = reference_grid()
    mdir = proc / "model" / period
    arrays, _ = bottom.read_model(mdir)
    z_lo0, z_hi0, in_model = sat_bounds(arrays)
    always = in_model & np.isnan(arrays["z_min"].astype(np.float64))        # R6: dokładnie z_lo = −∞
    assert (always == (np.isneginf(z_lo0))).all()

    cal_path = proc / "eval" / "calibration.json"
    deltas = json.loads(cal_path.read_text(encoding="utf-8"))["bands"]
    z_lo_c, z_hi_c = calibration.apply(z_lo0, z_hi0, deltas)

    ocr_path, qc_path = proc / "kz" / "kz_spot_ocr.gpkg", ref / "kz_spot_qc.csv"
    cont_path, grav_path = proc / "kz" / "kz_contours.gpkg", ref / "zwirownia.gpkg"
    ocr = gpd.read_file(ocr_path)
    qc = pd.read_csv(qc_path) if qc_path.exists() else None
    spots = kz.load_qc_spots(ocr, qc)
    contours = gpd.read_file(cont_path)
    gravel = gpd.read_file(grav_path).geometry.union_all()

    res = kz_deep.loo(spots, contours, grid, gravel, always)
    p5, p95 = float(res["p5"]), float(res["p95"])
    log.info("LOO: n=%d pominięte=%d p5=%.3f p95=%.3f", res["n"], res["n_skipped"], p5, p95)
    surf = kz_deep.deep_surface(spots, contours, grid, gravel)
    z_lo, z_hi, source, conflict = combine.merge_kz(z_lo_c, z_hi_c, surf, p5, p95)
    src = (source | (conflict.astype(np.uint8) << 1)).astype(np.uint8)

    out = proc / "model" / f"{period}_kz"
    out.mkdir(parents=True, exist_ok=True)
    _write_cog(out / "bottom_zlo.tif", z_lo.astype(np.float32), grid, np.nan)
    _write_cog(out / "bottom_zhi.tif", z_hi.astype(np.float32), grid, np.nan)
    _write_cog(out / "bottom_source.tif", src, grid, None)
    inputs = [p for p in (mdir / f"{bottom._RASTERS[k][0]}.tif" for k in SAT_RASTERS)]
    inputs += [cal_path, ocr_path] + ([qc_path] if qc_path.exists() else []) + [cont_path, grav_path]
    _dump(out / "meta.json", {"period": period, "p5": p5, "p95": p95, "deltas": deltas,
                              "inputs_sha1": _sha1(inputs), "inputs": [p.name for p in inputs]})

    ev = proc / "eval"
    _dump(ev / "kz_loo.json", {k: v for k, v in res.items()})
    covered = always & np.isfinite(surf)
    n_always = int(always.sum())
    n_conf = int((conflict & always).sum())
    summary = {"period": period, "p5": p5, "p95": p95, "n_loo": res["n"], "n_skipped": res["n_skipped"],
               "n_always_water": n_always, "n_covered": int(covered.sum()),
               "coverage": float(covered.sum() / n_always) if n_always else None,
               "n_conflict": n_conf, "conflict_share": float(n_conf / covered.sum()) if covered.sum() else None,
               "draft": DRAFT, "margin": MARGIN,
               "zones_before": zones(z_lo0, z_hi0, in_model, always),
               "zones_after": zones(z_lo, z_hi, in_model, always)}
    lo2, hi2 = calibrate_two_sided_only(z_lo0, z_hi0, deltas)
    lo2, hi2, _, _ = combine.merge_kz(lo2, hi2, surf, p5, p95)
    summary["zones_after_two_sided_only"] = zones(lo2, hi2, in_model, always)
    surf_195 = variant_d.kz_surface(spots, contours, grid, gravel=gravel)      # punkty + 192,5 + 195,0 (jak wariant D)
    summary["contour_195_check"] = {"with_195": kz_above_zmax(surf_195, z_hi0, always),
                                    "without_195": kz_above_zmax(surf, z_hi0, always)}
    _dump(ev / "kz_deep.json", summary)
    return summary


if __name__ == "__main__":
    s = main()
    print(json.dumps(_native(s), ensure_ascii=False, indent=1))
