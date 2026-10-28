"""Testy gugik.py bez sieci: fikstury GML 3.2 (struktura jak z żywego serwisu GUGiK, oś N,E)."""
import io
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import box

from mielizna import gugik

FIX = Path(__file__).parent / "fixtures"
BBOX = (372000, 285500, 381000, 292500)
LAKE = box(374000, 287000, 378000, 290000)  # 4 x 3 km, środek (376000, 288500)


class Resp:
    def __init__(self, content=b"", headers=None, status=200, chunks=None):
        self.content, self.headers, self.status_code, self._chunks = content, headers or {}, status, chunks

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield from (self._chunks or [self.content])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class FakeGet:
    """Kolejne strony fikstur; zapamiętuje STARTINDEX i BBOX."""
    def __init__(self):
        self.pages = [(FIX / f"wfs_page{i}.xml").read_bytes() for i in (1, 2, 3)]
        self.startindices, self.bboxes = [], []

    def __call__(self, url, params=None, **kw):
        self.startindices.append(params["STARTINDEX"])
        self.bboxes.append(params["BBOX"])
        return Resp(self.pages[len(self.startindices) - 1])


@pytest.fixture
def fake_get():
    return FakeGet()


@pytest.fixture
def index(fake_get):
    return gugik.fetch_index("http://x/wfs", BBOX, page_size=3, get=fake_get, delay=0)


def test_fetch_index_pages_until_empty(fake_get):
    gdf = gugik.fetch_index("http://x/wfs", BBOX, page_size=3, get=fake_get, delay=0)
    assert len(gdf) == 5 and fake_get.startindices == [0, 3, 5]  # krok = długość strony
    assert gdf.crs.to_epsg() == 2180
    # oś N,E: BBOX idzie jako ymin,xmin,ymax,xmax; geometria czytana z posList (N,E) -> x=easting
    assert fake_get.bboxes[0].startswith("285500,372000,292500,381000,urn:ogc:def:crs:EPSG::2180")
    first = gdf.iloc[0]
    assert first.geometry.bounds == (374000.0, 288500.0, 376000.0, 290000.0)
    assert first.godlo == "M-33-35-C-c-1-1" and first.akt_rok == 2011
    assert first.uklad_h == "PL-EVRF2007-NH" and first.url_do_pobrania.endswith(".asc")


def test_parse_gml_exception_report():
    xml = (b'<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1"><ows:Exception>'
           b'<ows:ExceptionText>brak warstwy</ows:ExceptionText></ows:Exception></ows:ExceptionReport>')
    with pytest.raises(gugik.GugikError, match="brak warstwy"):
        gugik.parse_gml(xml)


@pytest.mark.parametrize("raw,expected", [("0.15", 0.15), ("0,15 m", 0.15), ("0,10-0,15", 0.15),
                                          ("0.02", 0.02), ("1.50", 1.5), ("", np.nan), (None, np.nan),
                                          ("brak", np.nan)])
def test_parse_height_error(raw, expected):
    got = gugik.parse_height_error(raw)
    assert (np.isnan(got) and np.isnan(expected)) or got == pytest.approx(expected)


def test_select_sheets_drops_outside_and_photogrammetric(index):
    s = gugik.select_sheets(index, LAKE.buffer(300), years=[2011, 2024])
    # odpada: -2-1 (błąd 0,90 i zdj. lotnicze), -9-9 (poza jeziorem), -2-2 (rok 2018)
    assert set(s.godlo) == {"M-33-35-C-c-1-1", "M-33-35-C-c-1-2"}


def test_select_sheets_nan_error_is_not_lidar(index):
    index.loc[0, "blad_sr_wys"] = ""
    s = gugik.select_sheets(index, LAKE.buffer(300), years=[2011, 2024])
    assert set(s.godlo) == {"M-33-35-C-c-1-2"}


def _sheet(godlo, x0, y0, x1, y1):
    return {"godlo": godlo, "geometry": box(x0, y0, x1, y1)}


def test_pick_laz_sheets_spreads_over_quadrants():
    # NW ma dwa duże arkusze (kuszą), pozostałe ćwiartki po jednym mniejszym
    rows = [_sheet("nw1", 374000, 288500, 375900, 290000), _sheet("nw2", 374000, 288600, 375800, 290000),
            _sheet("ne", 376500, 289000, 377500, 290000), _sheet("sw", 374500, 287200, 375500, 288000),
            _sheet("se", 376500, 287500, 377200, 288000), _sheet("far", 300000, 200000, 301000, 201000)]
    sheets = gpd.GeoDataFrame(rows, geometry="geometry", crs=2180)
    p = gugik.pick_laz_sheets(sheets, LAKE, n=4)
    assert len(p) == 4 and set(p.quadrant) == {"NW", "NE", "SW", "SE"}
    assert "nw1" in set(p.godlo) and "nw2" not in set(p.godlo) and "far" not in set(p.godlo)


def test_pick_laz_sheets_fills_when_fewer_quadrants():
    rows = [_sheet("a", 374000, 288600, 375000, 290000), _sheet("b", 375000, 288600, 375900, 290000),
            _sheet("c", 374000, 288600, 374500, 289000)]
    p = gugik.pick_laz_sheets(gpd.GeoDataFrame(rows, geometry="geometry", crs=2180), LAKE, n=2)
    assert len(p) == 2 and list(p.godlo) == ["a", "b"]


def test_file_ext():
    assert gugik.file_ext("https://h/x/1_2_M-33-1.xyz.zip", "M-33-1") == "xyz.zip"
    assert gugik.file_ext("https://h/x/1_2_M-33-1.laz", "M-33-1") == "laz"
    assert gugik.file_ext("https://h/x/NMT-M-33-1.zip", "M-33-1") == "zip"


# --- pobieranie -----------------------------------------------------------------------------

def test_download_skips_existing_same_size(tmp_path):
    dest = tmp_path / "a" / "f.laz"
    dest.parent.mkdir()
    dest.write_bytes(b"12345")
    get = lambda *a, **k: pytest.fail("nie powinno pobierać")
    head = lambda *a, **k: Resp(headers={"Content-Length": "5"})
    assert gugik.download("http://x/f.laz", dest, get=get, head=head) == (dest, 5, "skipped")


def test_download_streams_and_resumes(tmp_path):
    dest = tmp_path / "f.laz"
    head = lambda *a, **k: Resp(headers={"Content-Length": "6"})
    seen = {}

    def get(url, stream, timeout, headers):
        seen.update(headers)
        return Resp(b"def", status=206, chunks=[b"d", b"ef"])
    (tmp_path / "f.laz.part").write_bytes(b"abc")
    path, n, status = gugik.download("http://x/f.laz", dest, get=get, head=head)
    assert status == "resumed" and n == 6 and path.read_bytes() == b"abcdef"
    assert seen["Range"] == "bytes=3-" and not (tmp_path / "f.laz.part").exists()


def test_download_size_mismatch_keeps_part(tmp_path):
    dest = tmp_path / "f.laz"
    head = lambda *a, **k: Resp(headers={"Content-Length": "10"})
    get = lambda url, stream, timeout, headers: Resp(b"abc")
    with pytest.raises(IOError):
        gugik.download("http://x/f.laz", dest, get=get, head=head)
    assert not dest.exists() and (tmp_path / "f.laz.part").exists()


# --- konwersja ------------------------------------------------------------------------------

ASC = """ncols 3
nrows 2
xllcorner 374000
yllcorner 288000
cellsize 1
NODATA_value -9999
10 11 -9999
12 13 14
"""


def test_asc_to_geotiff_tags_and_crs(tmp_path):
    src = tmp_path / "s.asc"
    src.write_text(ASC)
    out = gugik.nmt_to_geotiff(src, tmp_path / "o" / "s.tif", "PL-KRON86-NH")
    with rasterio.open(out) as r:
        assert r.crs.to_epsg() == 2180 and r.tags()["uklad_h"] == "PL-KRON86-NH"
        assert r.bounds == (374000, 288000, 374003, 288002) and r.nodata == -9999
        a = r.read(1)
    assert a[0, 0] == 10 and a[1, 2] == 14 and a[0, 2] == -9999


def test_xyz_zip_to_geotiff(tmp_path):
    # środki komórek 1 m; wiersz północny pierwszy
    xyz = "374000.5 288001.5 10\n374001.5 288001.5 11\n374000.5 288000.5 12\n374001.5 288000.5 13\n"
    zp = tmp_path / "s.xyz.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("M-33-1.xyz", xyz)
    out = gugik.nmt_to_geotiff(zp, tmp_path / "s.tif", "PL-EVRF2007-NH")
    with rasterio.open(out) as r:
        assert r.bounds == (374000, 288000, 374002, 288002) and r.tags()["uklad_h"] == "PL-EVRF2007-NH"
        assert r.read(1).tolist() == [[10, 11], [12, 13]]


def test_fetch_index_short_pages_collects_all(fake_get):
    # serwer tnie COUNT (np. wfs_maxfeatures=3), a my prosimy o 100: nic nie może przepaść
    gdf = gugik.fetch_index("http://x/wfs", BBOX, page_size=100, get=fake_get, delay=0)
    assert len(gdf) == 5 and fake_get.startindices == [0, 3, 5]


def test_fetch_index_ignored_startindex_terminates():
    page = (FIX / "wfs_page1.xml").read_bytes()
    calls = []

    def get(url, params=None, **kw):
        calls.append(params["STARTINDEX"])
        return Resp(page)
    gdf = gugik.fetch_index("http://x/wfs", BBOX, page_size=3, get=get, delay=0)
    assert len(gdf) == 3 and len(calls) == 2


def test_parse_gml_ogc_http_crs_is_northing_first():
    xml = (FIX / "wfs_page1.xml").read_text().replace("urn:ogc:def:crs:EPSG::2180",
                                                      "http://www.opengis.net/def/crs/EPSG/0/2180")
    assert gugik.parse_gml(xml).iloc[0].geometry.bounds == (374000.0, 288500.0, 376000.0, 290000.0)


def test_download_known_size_skips_head(tmp_path):
    dest = tmp_path / "f.laz"
    dest.write_bytes(b"12345")
    head = lambda *a, **k: pytest.fail("HEAD niepotrzebny")
    assert gugik.download("http://x/f.laz", dest, head=head, size=5)[2] == "skipped"


def test_geotiff_write_is_atomic(tmp_path, monkeypatch):
    src = tmp_path / "s.asc"
    src.write_text(ASC)
    dest = tmp_path / "s.tif"

    real_open = rasterio.open

    def crashing_open(path, mode="r", **k):
        if mode == "w":  # zapis zaczęty, potem awaria w połowie
            Path(path).write_bytes(b"II*\x00partial")
            raise RuntimeError("crash")
        return real_open(path, mode, **k)
    monkeypatch.setattr(gugik.rasterio, "open", crashing_open)
    with pytest.raises(RuntimeError):
        gugik.nmt_to_geotiff(src, dest, "X")
    assert not dest.exists()


def test_ensure_geotiff_reconverts_when_forced_or_stale(tmp_path):
    import os
    src = tmp_path / "s.asc"
    src.write_text(ASC)
    dest = tmp_path / "s.tif"
    assert gugik.ensure_geotiff(src, dest, "A") is True       # brak -> konwersja
    assert gugik.ensure_geotiff(src, dest, "A") is False      # aktualny -> pomiń
    assert gugik.ensure_geotiff(src, dest, "B", force=True) is True   # pobrano na nowo
    with rasterio.open(dest) as r:
        assert r.tags()["uklad_h"] == "B"
    t = dest.stat().st_mtime
    os.utime(src, (t + 10, t + 10))                            # surowy nowszy niż tif
    assert gugik.ensure_geotiff(src, dest, "C") is True
