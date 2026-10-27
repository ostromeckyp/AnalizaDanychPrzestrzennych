"""OSM: obrys jeziora, bufor AOI i przystanie (Overpass API)."""
import hashlib
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
from rasterio.features import rasterize
from shapely.geometry import LineString, Point, Polygon
import shapely
from shapely.ops import linemerge, polygonize, unary_union
from pyproj import Transformer

from mielizna.config import data_path
from mielizna.grid import Grid

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
LAKE_RELATION_ID = 2908769
TARGET_CRS = "EPSG:2180"
KIND_TAGS = (("leisure", "marina", "marina"), ("leisure", "slipway", "slipway"),
             ("man_made", "pier", "pier"))

_tr = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)


def _to_2180(geom):
    """Przelicza geometrię z EPSG:4326 (lon, lat) do EPSG:2180."""
    return shapely.transform(geom, lambda c: np.column_stack(_tr.transform(c[:, 0], c[:, 1])))


def fetch_overpass(query: str, retries: int = 4) -> dict:
    """POST zapytania na Overpass; wynik cache'owany w data/raw/osm/ (klucz = hash zapytania)."""
    key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    cache = data_path("raw", "osm", f"overpass_{key}.json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    delay = 10
    for attempt in range(retries):
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=180,
                          headers={"User-Agent": "mielizna-pipeline/0.1"})
        if r.status_code in (429, 504) and attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        break
    data = r.json()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _member_line(member: dict) -> LineString:
    return LineString([(p["lon"], p["lat"]) for p in member["geometry"]])


def lake_polygon(overpass_json: dict) -> Polygon:
    """Obrys jeziora (relacja 2908769) w EPSG:2180; outer sklejane, inner jako dziury."""
    rel = next(e for e in overpass_json["elements"]
               if e["type"] == "relation" and e["id"] == LAKE_RELATION_ID)
    members = [m for m in rel["members"] if m["type"] == "way" and m.get("geometry")]

    def rings(role):
        lines = [_member_line(m) for m in members if m["role"] == role]
        if not lines:
            return []
        return list(polygonize([linemerge(lines)]))

    outer = unary_union(rings("outer"))
    inner = unary_union(rings("inner")) if any(m["role"] == "inner" for m in members) else None
    geom = outer.difference(inner) if inner is not None else outer
    return _to_2180(geom)


def points_gdf(overpass_json: dict) -> gpd.GeoDataFrame:
    """Przystanie, slipy i pomosty (node/way; way -> centroid) w EPSG:2180."""
    rows = []
    for e in overpass_json["elements"]:
        tags = e.get("tags") or {}
        kind = next((k for key, val, k in KIND_TAGS if tags.get(key) == val), None)
        if kind is None or e["type"] not in ("node", "way"):
            continue
        if e["type"] == "node":
            geom = Point(e["lon"], e["lat"])
        elif e.get("geometry"):
            geom = LineString([(p["lon"], p["lat"]) for p in e["geometry"]]).centroid
        elif "center" in e:
            geom = Point(e["center"]["lon"], e["center"]["lat"])
        else:
            continue
        rows.append({"osm_id": e["id"], "kind": kind, "name": tags.get("name"),
                     "geometry": _to_2180(geom)})
    return gpd.GeoDataFrame(rows, columns=["osm_id", "kind", "name", "geometry"],
                            geometry="geometry", crs=TARGET_CRS)


def _mask(grid: Grid, layer: str, path: Path | None = None) -> np.ndarray:
    gdf = gpd.read_file(path or data_path("processed", "lake.gpkg"), layer=layer)
    return rasterize(((g, 1) for g in gdf.geometry), out_shape=(grid.height, grid.width),
                     transform=grid.transform, fill=0, all_touched=False, dtype="uint8").astype(bool)


def aoi_mask(grid: Grid, *, path: Path | None = None) -> np.ndarray:
    """Maska bool obszaru zainteresowania (jezioro + bufor 500 m); `path` = jawny lake.gpkg (domyślnie z data_path)."""
    return _mask(grid, "aoi", path)


def lake_mask(grid: Grid, *, path: Path | None = None) -> np.ndarray:
    """Maska bool powierzchni jeziora; `path` = jawny lake.gpkg (domyślnie z data_path)."""
    return _mask(grid, "lake", path)
