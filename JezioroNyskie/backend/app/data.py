"""Wczytanie produktów pipeline'u do pamięci przy starcie backendu.

Co robi: czyta rastry modelu dna, sceny, linie brzegowe, przystanie, krzywą powierzchnia↔poziom i
  metryki RF; wylicza pochodne (granice z ±∞, maska modelu, NPP i Max PP).
Dlaczego tak: model jest mały (kilka rastrów), a każde zapytanie o strefy to czysta arytmetyka na
  tablicach - trzymanie w RAM jest najprostsze i najszybsze. NaN w z_min znaczy „zawsze woda" (−∞),
  NaN w z_max „zawsze ląd" (+∞) - zgodnie z `meta["nan_semantics"]`; poza modelem zostaje NaN.
  NPP i Max PP liczymy z tabeli KŻ (`mielizna.capacity`), by była jedna implementacja interpolacji.
Wejście → wyjście: katalog danych + okres → `Products`. Do sceny wchodzą tylko `qc_ok` z `h_t`
  (scena z qc_ok False nie publikuje poziomu, powierzchni ani linii brzegowej).
Jak to obronić: „poza modelem" = obs_count 0 lub 65535 lub flags 255; bit 8 flag jest opisowy i
  nie wpływa na nic. Pojemności 65,69 i 121,70 mln m³ to stałe z briefu §4 (tabela KŻ Nysa).
"""
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from affine import Affine

from app.depth import SOURCE_KZ, Bounds, combined_bounds, satellite_bounds
from app.settings import get_settings
from app.zones import mask_geometry
from mielizna import bottom, capacity, levels
from mielizna.capacity import MAX_PP_MLN_M3, NPP_MLN_M3  # brief §4, wspólne z pipeline'em (kz_compare)
from mielizna.levels import AreaLevelCurve

CRS = "EPSG:2180"
log = logging.getLogger(__name__)


@dataclass
class Products:
    transform: Affine
    crs: str
    shape: tuple[int, int]
    bounds: Bounds          # granice dna (z_lo/z_hi z ±∞, in_model, źródło); patrz app/depth.py
    z: np.ndarray           # float32
    unc: np.ndarray         # float32
    obs_count: np.ndarray   # uint16
    meta: dict
    version: str
    scenes: list[dict]
    shorelines: gpd.GeoDataFrame
    marinas: gpd.GeoDataFrame
    curve: AreaLevelCurve
    rf_metrics: dict
    z_max_floor: float
    npp: float
    max_pp: float
    capacity_table: pd.DataFrame   # tabela KŻ pojemność↔rzędna, wczytana raz (bez zmiany środowiska procesu)
    eval: dict = field(default_factory=dict)          # pliki oceny `processed/eval/*.json` (klucz = nazwa pliku bez .json); brak plików → {}
    gravel: gpd.GeoDataFrame | None = None            # obrys żwirowni (EPSG:2180) albo None, gdy brak pliku
    eval_hash: str = ""                               # odcisk treści plików oceny (część ETagu /api/meta)
    gravel_hash: str = ""                             # odcisk bajtów pliku obrysu (część ETagu /api/gravel)
    hazards: dict | None = None                       # przeszkody z locji KŻ ({"source", "features"}) albo None, gdy brak pliku
    hazards_hash: str = ""                            # odcisk bajtów pliku przeszkód (część ETagu /api/hazards)
    gravel_geom: object | None = None                 # suma obrysów jako przygotowana geometria do testu „punkt w obrysie"
    kz_interp: dict | None = None                     # {"p5", "p95"} z meta.json rastrów łączonych albo None, gdy ich nie wczytano
    kz_outline: dict | None = None                    # geometria GeoJSON (4326) obszaru dna z mapy KŻ, liczona raz przy starcie

    @property
    def z_lo(self) -> np.ndarray:
        """float64, −∞ gdzie z_min = NaN (zawsze woda), NaN poza modelem."""
        return self.bounds.z_lo

    @property
    def z_hi(self) -> np.ndarray:
        """float64, +∞ gdzie z_max = NaN (zawsze ląd), NaN poza modelem."""
        return self.bounds.z_hi

    @property
    def in_model(self) -> np.ndarray:
        """bool, maska pikseli modelu."""
        return self.bounds.in_model


def capacity_to_level(p: Products, v: float) -> float:
    """Pojemność [mln m³] → rzędna [m n.p.m.] z tabeli KŻ; poza tabelą NaN (jedna implementacja interpolacji)."""
    return float(capacity.capacity_to_level(v, table=p.capacity_table))


def level_to_capacity(p: Products, h: float) -> float:
    """Rzędna [m n.p.m.] → pojemność [mln m³] z tabeli KŻ; poza tabelą NaN."""
    return float(capacity.level_to_capacity(h, table=p.capacity_table))


EVAL_FILES = ("bottom_vs_nmt", "levels", "bottom_change", "model_choice", "variant_d", "kz_compare",
              "holdout", "error_budget", "calibration", "kz_loo", "kz_deep", "holdout_level_sources")


def load_eval(data_dir: Path) -> dict:
    """Wczytuje istniejące `processed/eval/<nazwa>.json`; brakujący lub uszkodzony plik jest pomijany."""
    out = {}
    for name in EVAL_FILES:
        try:
            body = json.loads((Path(data_dir) / "processed" / "eval" / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(body, dict):          # poprawny JSON, ale nie obiekt (null, lista, napis): pomijamy jak brak pliku
            out[name] = body
    return out


def short_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:10]


def load_gravel(data_dir: Path) -> gpd.GeoDataFrame | None:
    """Obrys żwirowni z `reference/zwirownia.gpkg` (EPSG:2180) albo None, gdy plik nie istnieje."""
    f = Path(data_dir) / "reference" / "zwirownia.gpkg"
    return gpd.read_file(f).to_crs(CRS) if f.exists() else None


def load_hazards(data_dir: Path) -> dict | None:
    """Przeszkody z locji KŻ Nysa (`reference/locja_przeszkody.geojson`, EPSG:4326) jako {"source", "features"}.

    Brak pliku albo uszkodzony plik daje None; niepoprawne cechy (nie-punkt, współrzędne poza zakresem,
    brak lub zły typ właściwości) są pomijane pojedynczo.
    """
    from pydantic import ValidationError
    from app.schemas import HazardProperties
    try:
        body = json.loads((Path(data_dir) / "reference" / "locja_przeszkody.geojson").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict) or not isinstance(body.get("features"), list):
        return None
    out, seen = [], set()
    for f in body["features"]:
        geom = f.get("geometry") if isinstance(f, dict) else None
        c = geom.get("coordinates") if isinstance(geom, dict) and geom.get("type") == "Point" else None
        if (not isinstance(c, list) or len(c) < 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in c[:2])
                or not (-180 <= c[0] <= 180 and -90 <= c[1] <= 90)):
            continue
        try:
            props = HazardProperties.model_validate(f.get("properties"))
        except ValidationError:
            continue
        if not math.isfinite(props.z):
            continue
        if not props.source_url.startswith(("https://", "http://")):    # link trafia do popupu: tylko http(s), nigdy javascript:
            continue
        if props.id in seen:
            log.warning("locja_przeszkody: powtórzone id %r, pomijam kolejną cechę", props.id)
            continue
        seen.add(props.id)
        out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(c[0]), float(c[1])]},
                    "properties": props.model_dump()})
    source = body.get("source")
    return {"source": source if isinstance(source, str) else "", "features": out}


def kz_version_suffix(data_dir: Path, kz_dir: Path, kz_meta: dict) -> str:
    """Przyrostek wersji `-kz<sha>`: odcisk wejść łączenia, bajtów rastrów łączonych i `meta.json` oraz plików oceny.

    Co: hashuje `inputs_sha1` z meta.json, bajty `bottom_zlo.tif`, `bottom_zhi.tif`, `bottom_source.tif`, `meta.json`
      z `kz_dir` oraz `kz_loo.json` i `calibration.json`.
    Dlaczego: ETagi i klucze cache wynikają z wersji, więc każda zmiana serwowanych granic, kalibracji albo oceny KŻ
      musi ją zmienić (spec: wersja obejmuje odcisk rastrów łączonych).
    """
    h = hashlib.sha1(str(kz_meta.get("inputs_sha1", "")).encode())
    files = [Path(kz_dir) / f for f in ("bottom_zlo.tif", "bottom_zhi.tif", "bottom_source.tif", "meta.json")]
    files += [Path(data_dir) / "processed" / "eval" / f"{name}.json" for name in ("kz_loo", "calibration")]
    for f in files:
        h.update(f.read_bytes() if f.exists() else b"")
    return f"-kz{h.hexdigest()[:10]}"


def load_products(data_dir: Path, period: str = "all", use_kz: bool | None = None) -> Products:
    """Wczytuje wszystkie produkty z `data_dir/processed` (okres modelu `period`).

    `use_kz` None → decyduje `MIELIZNA_NO_KZ`; bez katalogu `model/<okres>_kz/` wynik jest jak dla samego satelity.
    """
    data_dir = Path(data_dir)
    proc = data_dir / "processed"
    arrays, meta = bottom.read_model(proc / "model" / period)

    import rasterio
    with rasterio.open(proc / "model" / period / "bottom_zmin.tif") as ds:
        transform, crs = ds.transform, ds.crs.to_string()

    obs, flags = arrays["obs_count"], arrays["flags"]
    bounds = satellite_bounds(arrays["z_min"], arrays["z_max"], obs, flags)
    finite_max = bounds.z_hi[bounds.in_model & np.isfinite(bounds.z_hi)]   # próg ostrzeżenia z SUROWEGO satelity, nie z połączonych granic
    z_max_floor = float(finite_max.min())
    kz_dir = proc / "model" / f"{period}_kz"
    version_suffix, kz_interp, kz_outline = "", None, None
    if (use_kz if use_kz is not None else not get_settings().no_kz) and (kz_dir / "bottom_zlo.tif").exists():
        kz_meta = json.loads((kz_dir / "meta.json").read_text(encoding="utf-8"))
        bounds = combined_bounds(bounds, kz_dir)
        version_suffix = kz_version_suffix(data_dir, kz_dir, kz_meta)
        kz_interp = {"p5": float(kz_meta["p5"]), "p95": float(kz_meta["p95"])}
        kz_outline = mask_geometry(bounds.in_model & (bounds.source == SOURCE_KZ), transform, crs)

    scenes = [s for s in json.loads((proc / "scenes.json").read_text(encoding="utf-8"))
              if s["qc_ok"] and s["h_t"] is not None]
    scenes.sort(key=lambda s: s["date"])
    if not scenes:
        raise ValueError("brak opublikowanych scen (qc_ok z h_t) w scenes.json - backend nie ruszy bez fallbacku pipeline")
    dates = {s["date"] for s in scenes}

    shorelines = gpd.read_file(proc / "shorelines.gpkg")
    shorelines = shorelines[shorelines["date"].isin(dates)].set_index("date", drop=False)
    shorelines.index.name = None
    marinas = gpd.read_file(proc / "marinas.gpkg")

    rf_metrics = json.loads((proc / "model" / "rf_metrics.json").read_text(encoding="utf-8"))
    curve = levels.load_area_level_curve(proc / "model" / "area_level_curve.json")
    capacity_table = capacity.load_table(data_dir / "reference" / "kz_pojemnosc_rzedna.csv")
    npp = float(capacity.capacity_to_level(NPP_MLN_M3, table=capacity_table))
    max_pp = float(capacity.capacity_to_level(MAX_PP_MLN_M3, table=capacity_table))

    gravel = load_gravel(data_dir)
    ev = load_eval(data_dir)
    gf = data_dir / "reference" / "zwirownia.gpkg"
    gravel_hash = short_hash(gf.read_bytes()) if gf.exists() else ""
    hf = data_dir / "reference" / "locja_przeszkody.geojson"
    hazards_hash = short_hash(hf.read_bytes()) if hf.exists() else ""
    gravel_geom = None
    if gravel is not None and len(gravel):
        from shapely.prepared import prep
        gravel_geom = prep(gravel.geometry.union_all())

    return Products(
        transform=transform, crs=crs, shape=obs.shape, bounds=bounds, z=arrays["z"],
        unc=arrays["unc"], obs_count=obs, meta=meta,
        version=f"{period}-{meta['version']}{version_suffix}", scenes=scenes, shorelines=shorelines, marinas=marinas,
        curve=curve, rf_metrics=rf_metrics, z_max_floor=z_max_floor, npp=npp, max_pp=max_pp,
        capacity_table=capacity_table, eval=ev, eval_hash=short_hash(json.dumps(ev, sort_keys=True).encode()),
        gravel_hash=gravel_hash, gravel=gravel, gravel_geom=gravel_geom,
        hazards=load_hazards(data_dir), hazards_hash=hazards_hash, kz_interp=kz_interp, kz_outline=kz_outline,
    )
