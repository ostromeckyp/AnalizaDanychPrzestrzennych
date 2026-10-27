"""Sentinel-2 L2A (Earth Search): wyszukanie, odbicie, filtr scen, wczytanie na siatkę wzorcową."""
import datetime as dt
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pystac
import pystac_client
import rasterio
import xarray as xr
from odc.geo.geobox import GeoBox
from rasterio.transform import Affine
from scipy.ndimage import binary_dilation

from mielizna.grid import Grid

BANDS = ["blue", "green", "red", "nir", "swir16", "swir22"]
STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
SCALE = 1e-4
HARMONIZED_WATER_SWIR16_MAX_DN = 500
LOAD_KW = dict(nodata=0, dtype="uint16", groupby="id",
               resampling={"*": "bilinear", "scl": "nearest"}, fail_on_error=True)


# --- wyszukiwanie i deduplikacja -------------------------------------------------

def _item_date(item: pystac.Item) -> str:
    return item.datetime.astimezone(dt.timezone.utc).date().isoformat()


def _tile(item: pystac.Item) -> str:
    return item.properties["grid:code"].removeprefix("MGRS-")


def _version_key(item: pystac.Item) -> tuple:
    """(baseline jako krotka liczb, numer _N z id); wyższy = nowsze przetworzenie."""
    base = tuple(int(p) for p in str(item.properties.get("s2:processing_baseline", "0")).split("."))
    m = re.search(r"_(\d+)_L2A$", item.id)
    return (base, int(m.group(1)) if m else -1)


def dedupe_items(items: list[pystac.Item]) -> list[pystac.Item]:
    """Jedna wersja na (platforma, kafel, data UTC): wyższy baseline, potem wyższy numer _N."""
    best: dict[tuple, pystac.Item] = {}
    for it in items:
        key = (it.properties["platform"], it.properties["grid:code"], _item_date(it))
        if key not in best or _version_key(it) > _version_key(best[key]):
            best[key] = it
    return sorted(best.values(), key=lambda i: (_item_date(i), i.id))


def group_acquisitions(items: list[pystac.Item]) -> dict[tuple[str, str], list[pystac.Item]]:
    """(data 'YYYY-MM-DD', platforma) -> kafle tej akwizycji (maks. 2)."""
    groups: dict[tuple[str, str], list[pystac.Item]] = {}
    for it in items:
        groups.setdefault((_item_date(it), it.properties["platform"]), []).append(it)
    return groups


def search_items(cfg: dict, cache: Path | None = None, refresh: bool = False) -> list[pystac.Item]:
    """Wyszukuje kafle w BBOX i okresie (chmury na kafel < max_tile_cloud); wynik po deduplikacji.

    Surowy wynik wyszukiwania jest cache'owany w `cache` (JSON), odświeżany przez `refresh`.
    """
    if cache is not None and cache.exists() and not refresh:
        items = list(pystac.ItemCollection.from_file(str(cache)))
    else:
        client = pystac_client.Client.open(STAC_URL)
        start, end = cfg["period"]["start"], cfg["period"]["end"]
        items = list(client.search(
            collections=[COLLECTION], bbox=cfg["bbox_wgs84"], datetime=f"{start}/{end}",
            query={"eo:cloud_cover": {"lt": cfg["scene_filter"]["max_tile_cloud"]}},
        ).items())
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            pystac.ItemCollection(items).save_object(str(cache))
    return dedupe_items(items)


# --- odbicie ----------------------------------------------------------------------

def reflectance_offset(item: pystac.Item) -> float:
    """Earth Search v1 COGs are harmonized to the pre-04.00 convention for every baseline
    (measured 2026-10-27, see task-4-decisions.md). Never read raster:bands.offset."""
    return 0.0


def dn_to_reflectance(dn: np.ndarray, offset: float) -> np.ndarray:
    """DN -> odbicie float32; DN == 0 to brak danych (NaN), reszta dn*1e-4 + offset."""
    r = dn.astype(np.float32) * np.float32(SCALE) + np.float32(offset)
    r[dn == 0] = np.nan
    return r


def check_harmonized(swir16_dn: np.ndarray, scl: np.ndarray, item_id: str) -> None:
    """ValueError, gdy mediana SWIR16 DN nad pikselami SCL==6 > 500 (wymaga >= 100 pikseli wody,
    inaczej nic nie robi). Odbicie wody w SWIR16 to ~0.00-0.06, więc mediana > 500 DN oznacza,
    że w danych został offset +1000."""
    dn = swir16_dn[(scl == 6) & (swir16_dn > 0)]
    if dn.size >= 100 and np.median(dn) > HARMONIZED_WATER_SWIR16_MAX_DN:
        raise ValueError(f"{item_id}: mediana SWIR16 nad wodą = {np.median(dn):.0f} DN "
                         f"(> {HARMONIZED_WATER_SWIR16_MAX_DN}); dane wyglądają na bez harmonizacji")


# --- maski i jakość sceny ---------------------------------------------------------

def valid_mask(bands: dict, scl: np.ndarray) -> np.ndarray:
    """SCL poza {0, 1} i wszystkie pasma skończone."""
    ok = ~np.isin(scl, (0, 1))
    for b in bands.values():
        ok &= np.isfinite(b)
    return ok


def cloud_mask(scl: np.ndarray) -> np.ndarray:
    """Chmury (SCL 8, 9, 10) rozszerzone o 2 px, plus cienie chmur (SCL 3)."""
    cloud = binary_dilation(np.isin(scl, (8, 9, 10)), iterations=2)
    return cloud | (scl == 3)


def scene_quality(date: str, scl: np.ndarray, valid: np.ndarray, aoi: np.ndarray,
                  lake: np.ndarray) -> dict:
    """Miary jakości sceny (procenty) w AOI i na jeziorze."""
    n_aoi, n_lake = aoi.sum(), lake.sum()
    cloud = cloud_mask(scl)
    n_valid = (valid & aoi).sum()
    classes, counts = np.unique(scl[aoi], return_counts=True)
    return {
        "date": date,
        "valid_pct": 100 * n_valid / n_aoi,
        "local_cloud_pct": 100 * (cloud & valid & aoi).sum() / n_valid if n_valid else 100.0,
        "ice_pct": 100 * ((scl == 11) & lake).sum() / n_lake,
        "lake_nodata_pct": 100 * ((~valid | cloud) & lake).sum() / n_lake,
        "scl_pct": {int(c): 100 * n / n_aoi for c, n in zip(classes, counts)},
    }


def is_usable(q: dict, cfg: dict) -> bool:
    """Progi z cfg['scene_filter'] oraz lista wykluczonych dat."""
    f = cfg["scene_filter"]
    excluded = {e["date"] if isinstance(e, dict) else e for e in f.get("exclude_dates") or []}
    return bool(q["valid_pct"] >= f["min_valid_pct"]
                and q["local_cloud_pct"] < f["max_local_cloud_pct"]
                and q["ice_pct"] <= f["max_ice_pct"]
                and str(q["date"]) not in excluded)


# --- wczytanie na siatkę ----------------------------------------------------------

def grid_geobox(grid: Grid) -> GeoBox:
    return GeoBox((grid.height, grid.width), grid.transform, grid.crs)


def _odc_load(items: list[pystac.Item], bands: list[str], geobox: GeoBox, pool: int = 4) -> xr.Dataset:
    """Jedyne wejście do odc-stac (load_day, load_scl, resample_like_load_day)."""
    import odc.stac
    return odc.stac.load(items, bands=bands, geobox=geobox, pool=pool, **LOAD_KW)


def _load_item(item: pystac.Item, bands: list[str], geobox: GeoBox, pool: int) -> dict[str, np.ndarray]:
    ds = _odc_load([item], bands, geobox, pool)
    if ds.odc.geobox != geobox:
        raise ValueError(f"{item.id}: siatka wyniku różni się od wzorcowej")
    return {b: ds[b].values[0] for b in bands}


def load_scl(items: list[pystac.Item], grid: Grid, pool: int = 4) -> list[np.ndarray]:
    """Przebieg 1: SCL (uint8, 0 = brak danych) każdego itemu na siatce wzorcowej, nearest."""
    gb = grid_geobox(grid)
    with ThreadPoolExecutor(max_workers=max(1, min(pool, len(items)))) as ex:
        res = list(ex.map(lambda it: _load_item(it, ["scl"], gb, 1)["scl"], items))
    return res


def mosaic_first_valid(per_item_bands: list[dict[str, np.ndarray]], per_item_scl: list[np.ndarray],
                       per_item_valid: list[np.ndarray]) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Mozaika: dla każdego piksela źródłem jest pierwszy item z valid=True; wszystkie pasma i SCL
    pochodzą z tego samego itemu. Brak źródła -> NaN w pasmach i 0 w SCL."""
    src = np.full(per_item_valid[0].shape, -1, dtype=np.int16)
    for i, v in enumerate(per_item_valid):
        src[(src < 0) & v] = i
    bands = {}
    for b in per_item_bands[0]:
        out = np.full(src.shape, np.nan, dtype=np.float32)
        for i, pb in enumerate(per_item_bands):
            out[src == i] = pb[b][src == i]
        bands[b] = out
    scl = np.zeros(src.shape, dtype=np.uint8)
    for i, ps in enumerate(per_item_scl):
        scl[src == i] = ps[src == i]
    return bands, scl


def load_day(items: list[pystac.Item], grid: Grid, cfg: dict, bands: list[str] = BANDS,
             pool: int = 4) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Jedna akwizycja (ta sama platforma i data), kafle posortowane od najlepszego.

    Dla każdego itemu: wczytanie pasm i SCL (uint16, nodata=0 przed interpolacją), check_harmonized,
    konwersja na odbicie, maska ważności; potem mozaika pierwszego ważnego piksela.
    Zwraca ({pasmo: odbicie float32, NaN bez źródła}, SCL uint8, 0 bez źródła)."""
    gb = grid_geobox(grid)
    all_bands, all_scl, all_valid = [], [], []
    for it in items:
        raw = _load_item(it, list(bands) + ["scl"], gb, pool)
        scl = raw["scl"]
        if "swir16" in raw:
            check_harmonized(raw["swir16"], scl, it.id)
        refl = {b: dn_to_reflectance(raw[b], reflectance_offset(it)) for b in bands}
        all_bands.append(refl)
        all_scl.append(scl)
        all_valid.append(valid_mask(refl, scl))
    return mosaic_first_valid(all_bands, all_scl, all_valid)


def resample_like_load_day(dn: np.ndarray, factor: int = 2, src_res: float = 20.0,
                           tag_nodata: bool = True) -> np.ndarray:
    """Pomocnik testów: DN zapisane do GeoTIFF (EPSG:32633, nodata=0 jako TAG, jak COG Earth Search),
    wczytane przez _odc_load na siatkę gęstszą `factor` razy; zwraca odbicie (offset 0)."""
    from pyproj import Transformer
    h, w = dn.shape
    x0, y0 = 500000.0, 5600000.0
    tr = Affine(src_res, 0, x0, 0, -src_res, y0)
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "swir16.tif")
        kw = {"nodata": 0} if tag_nodata else {}
        with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="uint16",
                           crs="EPSG:32633", transform=tr, **kw) as ds:
            ds.write(dn.astype(np.uint16), 1)
        t = Transformer.from_crs(32633, 4326, always_xy=True)
        pts = [t.transform(x, y) for x in (x0, x0 + w * src_res) for y in (y0, y0 - h * src_res)]
        bb = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
        geom = {"type": "Polygon", "coordinates": [[[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]],
                                                     [bb[0], bb[3]], [bb[0], bb[1]]]]}
        item = pystac.Item("synthetic", geom, bb, dt.datetime(2020, 1, 1), {"proj:epsg": 32633})
        item.add_asset("swir16", pystac.Asset(path, media_type="image/tiff", roles=["data"], extra_fields={
            "proj:shape": [h, w], "proj:transform": list(tr)[:6],
            "raster:bands": [{"nodata": 0, "data_type": "uint16"}]}))
        res = src_res / factor
        gb = GeoBox((h * factor, w * factor), Affine(res, 0, x0, 0, -res, y0), "EPSG:32633")
        out = _odc_load([item], ["swir16"], gb, pool=1).swir16.values[0]
    return dn_to_reflectance(out, 0.0)
