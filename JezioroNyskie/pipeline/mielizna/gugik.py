"""GUGiK: skorowidze WFS (NMT i chmury punktów LAZ), wybór arkuszy, pobieranie i konwersja NMT.

Co robi: stronicuje skorowidze WFS 2.0 GUGiK (STARTINDEX do pustej strony), czyta GML 3.2 do
  GeoDataFrame w EPSG:2180, wybiera arkusze przecinające obszar i pochodzące ze skaningu
  laserowego (błąd śr. wys. <= 0,2 m), wskazuje arkusze LAZ rozłożone po obrysie jeziora,
  pobiera pliki strumieniowo z wznawianiem i zamienia NMT (ASC / XYZ, także w ZIP) na GeoTIFF.
Dlaczego tak: serwis ucina odpowiedzi limitem COUNT i słabo filtruje BBOX, więc listę arkuszy
  trzeba zebrać stronami i dociąć po geometrii; NMT ze zdjęć lotniczych (błąd 0,5-1,5 m) nie nadaje
  się do kalibracji poziomu wody, więc odrzucamy je po błędzie wysokości; jeden arkusz LAZ na
  ćwiartkę obrysu daje próbki z całego obwodu, a nie z jednego brzegu.
Wejście → wyjście: URL skorowidza + BBOX (EPSG:2180) → GeoDataFrame arkuszy; URL pliku → plik na
  dysku (+ GeoTIFF EPSG:2180 z tagiem `uklad_h` dla NMT).
Jak to obronić: lista arkuszy jest kompletna (stronicowanie do pustej strony, bez dubli) i
  przefiltrowana geometrią, nie samym BBOX; układ wysokości (`uklad_h`) jest niesiony z indeksu aż do
  tagu GeoTIFF, nic nie jest zgadywane; pobieranie nie nadpisuje poprawnych plików.

Format odpowiedzi (sprawdzony na żywym serwisie, 2026-10): GML 3.2 (`application/gml+xml;
version=3.2`, domyślny). Warstwy są roczne (`gugik:SkorowidzNMT<rok>`,
`gugik:SkorowidzDanychPomiarowychLIDAR<rok>`). Uwaga: dla EPSG:2180 w postaci URN
(`urn:ogc:def:crs:EPSG::2180`) kolejność osi to NORTHING, EASTING, i to zarówno w BBOX, jak i w
`gml:posList` odpowiedzi; BBOX w kolejności x,y zwraca 0 obiektów. Skorowidz nie podaje rozmiaru
pliku, więc rozmiar szacujemy zapytaniem HEAD.
"""
import logging
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, Polygon
import shapely

log = logging.getLogger("mielizna.gugik")

CRS = "EPSG:2180"
URN_2180 = "urn:ogc:def:crs:EPSG::2180"
NS = {"wfs": "http://www.opengis.net/wfs/2.0", "gml": "http://www.opengis.net/gml/3.2",
      "ows": "http://www.opengis.net/ows/1.1"}
COLUMNS = ["gml_id", "godlo", "akt_rok", "asortyment", "format", "char_przestrz", "blad_sr_wys",
           "uklad_h", "zrodlo_danych", "url_do_pobrania"]
MAX_LIDAR_ERR_M = 0.2
USER_AGENT = "mielizna-pipeline/0.1"


class GugikError(RuntimeError):
    """Serwis zwrócił ExceptionReport zamiast kolekcji obiektów."""


# --- parsowanie GML -----------------------------------------------------------------------------

def _ring(pos_list: str, swap: bool) -> list[tuple[float, float]]:
    v = np.array(pos_list.split(), dtype=float).reshape(-1, 2)
    if swap:  # URN EPSG:2180 -> (northing, easting); shapely chce (x=easting, y=northing)
        v = v[:, ::-1]
    return [tuple(p) for p in v]


def _polygon(el: ET.Element) -> Polygon:
    srs = el.get("srsName") or URN_2180
    # URN i http://www.opengis.net/def/crs/... = oś northing, easting; "EPSG:2180" = x, y
    swap = "urn:ogc:def" in srs or "opengis.net/def/crs" in srs
    ext = el.find("gml:exterior/gml:LinearRing/gml:posList", NS)
    holes = [_ring(h.text, swap) for h in el.findall("gml:interior/gml:LinearRing/gml:posList", NS)]
    return Polygon(_ring(ext.text, swap), holes)


def parse_gml(text: str | bytes) -> gpd.GeoDataFrame:
    """Czyta stronę WFS (GML 3.2) do GeoDataFrame w EPSG:2180; pusta strona -> pusty GeoDataFrame."""
    root = ET.fromstring(text)
    if root.tag.endswith("ExceptionReport"):
        msg = " ".join((e.text or "").strip() for e in root.iter() if e.tag.endswith("ExceptionText"))
        raise GugikError(msg or "ExceptionReport")
    rows = []
    for member in root.findall("wfs:member", NS):
        feat = member[0]
        polys = [_polygon(p) for p in feat.iter(f"{{{NS['gml']}}}Polygon")]
        if not polys:
            continue
        row = {"gml_id": feat.get(f"{{{NS['gml']}}}id")}
        for ch in feat:
            name = ch.tag.split("}")[1]
            if name in COLUMNS and len(ch) == 0:
                row[name] = (ch.text or "").strip()
        row["geometry"] = polys[0] if len(polys) == 1 else MultiPolygon(polys)
        rows.append(row)
    gdf = gpd.GeoDataFrame(rows, columns=COLUMNS + ["geometry"], geometry="geometry", crs=CRS)
    if len(gdf):
        gdf["akt_rok"] = pd.to_numeric(gdf["akt_rok"], errors="coerce").astype("Int64")
    return gdf


def fetch_index(url: str, bbox_2180: tuple, page_size: int, get=requests.get,
                typenames: str | None = None, delay: float = 1.0) -> gpd.GeoDataFrame:
    """Pobiera cały skorowidz WFS w BBOX (xmin, ymin, xmax, ymax; EPSG:2180).

    Stronicuje `STARTINDEX` aż do pustej strony (serwis ucina odpowiedź limitem COUNT i nie podaje
    numberMatched). `typenames` = warstwa (np. `gugik:SkorowidzNMT2024`); `delay` s przerwy między
    zapytaniami. Duble (ten sam gml:id) są usuwane.
    """
    xmin, ymin, xmax, ymax = bbox_2180
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
              "COUNT": page_size,
              "BBOX": f"{ymin},{xmin},{ymax},{xmax},{URN_2180}"}  # oś: northing, easting
    if typenames:
        params["TYPENAMES"] = typenames
    pages, start, seen = [], 0, set()
    while True:
        r = get(url, params={**params, "STARTINDEX": start}, timeout=120,
                headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        page = parse_gml(r.content)
        log.info("WFS %s startindex=%d -> %d obiektów", typenames or url, start, len(page))
        if page.empty:
            break
        if set(page.gml_id) <= seen:  # serwer ignoruje STARTINDEX -> inaczej pętla w nieskończoność
            log.warning("WFS %s: strona startindex=%d bez nowych obiektów, kończę stronicowanie",
                        typenames or url, start)
            break
        seen.update(page.gml_id)
        pages.append(page)
        start += len(page)  # serwer może ściąć COUNT (wfs_maxfeatures); krok = faktyczna długość strony
        if delay:
            time.sleep(delay)
    if not pages:
        return gpd.GeoDataFrame(columns=COLUMNS + ["geometry"], geometry="geometry", crs=CRS)
    out = pd.concat(pages, ignore_index=True)
    out = out.drop_duplicates("gml_id", ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=CRS)


# --- wybór arkuszy ------------------------------------------------------------------------------

def parse_height_error(value) -> float:
    """Błąd śr. wysokościowy [m] z pola `blad_sr_wys`: "0.15", "0,15 m", "0,10-0,15" (-> max).

    Brak liczby (None, "", "brak") -> NaN, czyli arkusz nie przejdzie filtra LiDAR (nie zgadujemy).
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    nums = re.findall(r"\d+(?:[.,]\d+)?", str(value))
    return max(float(n.replace(",", ".")) for n in nums) if nums else float("nan")


def select_sheets(index: gpd.GeoDataFrame, area: shapely.Geometry, years: list[int]) -> gpd.GeoDataFrame:
    """Arkusze przecinające `area`, z `akt_rok` w `years`, pochodzące z LiDAR-u.

    LiDAR = błąd śr. wysokościowy <= 0,2 m (po sparsowaniu pola) i, jeśli jest kolumna
    `zrodlo_danych`, źródło nie jest "Zdj. lotnicze". Odrzuca NMT z fotogrametrii (błąd 0,5-1,5 m).
    """
    err = index["blad_sr_wys"].map(parse_height_error)
    keep = index["akt_rok"].isin(years) & (err <= MAX_LIDAR_ERR_M) & index.intersects(area)
    if "zrodlo_danych" in index:
        keep &= ~index["zrodlo_danych"].fillna("").str.contains("zdj", case=False)
    out = index[keep].copy()
    out["blad_sr_wys_m"] = err[keep]
    return out.reset_index(drop=True)


def _quadrant(pt, centre) -> str:
    return ("N" if pt.y >= centre.y else "S") + ("E" if pt.x >= centre.x else "W")


def pick_laz_sheets(sheets: gpd.GeoDataFrame, lake: Polygon, n: int) -> gpd.GeoDataFrame:
    """`n` arkuszy o największym udziale wody jeziora, rozłożonych po ćwiartkach obrysu.

    Udział wody = pole części wspólnej arkusza z jeziorem. Ćwiartka = położenie środka tej części
    względem środka ciężkości jeziora. Najpierw najlepszy arkusz z każdej ćwiartki (od najbogatszej
    w wodę), potem uzupełnienie najlepszymi z reszty.
    """
    if sheets.empty:
        return sheets.copy()
    inter = sheets.geometry.intersection(lake)
    s = sheets.assign(water_m2=inter.area.values,
                      quadrant=[_quadrant(g.centroid, lake.centroid) if not g.is_empty else None
                                for g in inter])
    s = s[s.water_m2 > 0].sort_values("water_m2", ascending=False)
    first = s.drop_duplicates("quadrant")  # najlepszy z każdej ćwiartki
    picked = first.head(n)
    if len(picked) < n:
        rest = s.drop(picked.index).head(n - len(picked))
        picked = pd.concat([picked, rest])
    return picked.sort_values("water_m2", ascending=False).reset_index(drop=True)


# --- pobieranie ---------------------------------------------------------------------------------

def remote_size(url: str, head=requests.head) -> int | None:
    """Rozmiar pliku [B] z nagłówka Content-Length (HEAD); None, gdy serwer go nie podaje.

    Uwaga: opendata.geoportal.gov.pl odpowiada na HEAD po ok. 40 s (generuje plik), stąd długi timeout.
    Serwer ignoruje też `Range` (zawsze 200 i cały plik), więc wznawianie ma w praktyce charakter "od nowa".
    """
    r = head(url, allow_redirects=True, timeout=240, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    n = r.headers.get("Content-Length")
    return int(n) if n else None


def download(url: str, dest: Path, get=requests.get, head=requests.head,
             chunk: int = 1 << 20, size: int | None = None) -> tuple[Path, int, str]:
    """Pobiera `url` do `dest` strumieniowo; zwraca (ścieżka, bajty, status).

    Status: "skipped" (plik istnieje i ma rozmiar z serwera), "resumed" (dokończono z `.part` przez
    Range) albo "downloaded". Zapis przez `<dest>.part`, więc przerwane pobranie nie udaje gotowego pliku.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if size is None:  # znany rozmiar (np. z planu) oszczędza ok. 40 s HEAD
        size = remote_size(url, head)
    if dest.exists() and (size is None or dest.stat().st_size == size) and dest.stat().st_size > 0:
        return dest, dest.stat().st_size, "skipped"
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if size is not None and have > size:
        part.unlink()
        have = 0
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    status = "downloaded"
    with get(url, stream=True, timeout=120, headers=headers) as r:
        r.raise_for_status()
        mode = "ab"
        if have and r.status_code == 206:
            status = "resumed"
        else:  # serwer zignorował Range -> od początku
            mode = "wb"
        with open(part, mode) as f:
            for block in r.iter_content(chunk):
                f.write(block)
    if size is not None and part.stat().st_size != size:
        raise IOError(f"{url}: pobrano {part.stat().st_size} B, oczekiwano {size} B (zostaje {part.name})")
    part.replace(dest)
    return dest, dest.stat().st_size, status


def file_ext(url: str, godlo: str) -> str:
    """Rozszerzenie pliku po godle w nazwie z URL-a (np. `asc`, `xyz.zip`, `laz`)."""
    name = url.rsplit("/", 1)[-1]
    if godlo in name:
        ext = name.split(godlo, 1)[1].lstrip("._")
        if ext:
            return ext
    return name.rsplit(".", 1)[-1]


# --- konwersja NMT -> GeoTIFF -------------------------------------------------------------------

def xyz_to_array(xyz: np.ndarray, nodata: float = -9999.0) -> tuple[np.ndarray, rasterio.Affine]:
    """Regularna siatka z punktów (x, y, z) -> (tablica [wiersz 0 = północ], transform).

    Rozdzielczość = najmniejszy niezerowy krok w x; punkty są środkami komórek, więc origin
    przesuwamy o pół kroku. Brakujące komórki = nodata.
    """
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    xs, ys = np.unique(x), np.unique(y)
    res = float(np.min(np.diff(xs))) if len(xs) > 1 else float(np.min(np.diff(ys)))
    cols = np.rint((x - xs[0]) / res).astype(int)
    rows = np.rint((ys[-1] - y) / res).astype(int)
    arr = np.full((rows.max() + 1, cols.max() + 1), nodata, dtype="float32")
    arr[rows, cols] = z
    return arr, from_origin(xs[0] - res / 2, ys[-1] + res / 2, res, res)


def _write_tif(arr, transform, dest: Path, uklad_h: str, nodata: float, extra: dict | None = None):
    """Zapis atomowy: do `<dest>.tmp`, potem replace (awaria nie zostawia połówkowego GeoTIFF-a)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        _write_tif_to(arr, transform, tmp, uklad_h, nodata, extra)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _write_tif_to(arr, transform, dest: Path, uklad_h: str, nodata: float, extra: dict | None = None):
    with rasterio.open(dest, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs=CRS, transform=transform, nodata=nodata,
                       compress="deflate", tiled=False) as dst:
        dst.write(arr.astype("float32"), 1)
        dst.update_tags(uklad_h=uklad_h, **(extra or {}))
    return dest


def nmt_to_geotiff(src: Path, dest: Path, uklad_h: str) -> Path:
    """NMT (ARC/INFO ASCII GRID `.asc`, ASCII XYZ `.xyz`, także w `.zip`) -> GeoTIFF EPSG:2180.

    Tag `uklad_h` (np. PL-EVRF2007-NH) zapisany w metadanych rastra. Nie zgadujemy układu wysokości.
    """
    src = Path(src)
    tmp_dir = None
    if src.suffix.lower() == ".zip":
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="nmt_"))
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".asc", ".xyz", ".txt"))]
            if not names:
                raise ValueError(f"{src.name}: brak .asc/.xyz w archiwum")
            z.extract(names[0], tmp_dir)
        src = tmp_dir / names[0]
    try:
        if src.suffix.lower() == ".asc":
            with rasterio.open(src) as r:
                arr = r.read(1).astype("float32")
                nodata = r.nodata if r.nodata is not None else -9999.0
                transform = r.transform
        else:
            xyz = np.loadtxt(src, dtype="float64", ndmin=2, usecols=(0, 1, 2))
            nodata = -9999.0
            arr, transform = xyz_to_array(xyz, nodata)
        return _write_tif(arr, transform, dest, uklad_h, nodata)
    finally:
        if tmp_dir is not None:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


def ensure_geotiff(src: Path, dest: Path, uklad_h: str, force: bool = False) -> bool:
    """Konwertuje NMT, gdy GeoTIFF nie istnieje, `force` (surowy plik pobrany na nowo) albo jest starszy od surowego.

    Zwraca True, jeśli konwersja się odbyła.
    """
    src, dest = Path(src), Path(dest)
    if not force and dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return False
    nmt_to_geotiff(src, dest, uklad_h)
    return True
