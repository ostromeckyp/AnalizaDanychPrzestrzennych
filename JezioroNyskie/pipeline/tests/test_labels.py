import json
import sys
import threading
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from affine import Affine
from geopandas.testing import assert_geodataframe_equal
from shapely.geometry import Point

from mielizna.grid import Grid
from mielizna.labels import load, sample_candidates, save

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import label_server  # noqa: E402

N = 200
GRID = Grid("EPSG:2180", Affine(10, 0, 372000, 0, -10, 292500), N, N)
DATES = ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"]
CLOUD = (slice(0, 100), slice(0, 100))  # lewa górna ćwiartka zachmurzona w jednej scenie


def _ok(date):
    ok = np.ones((N, N), bool)
    if date == DATES[0]:
        ok[CLOUD] = False
    return ok


@pytest.fixture
def synthetic():
    rr, cc = np.mgrid[:N, :N]
    r = np.hypot(rr - N / 2, cc - N / 2)
    lake = r < 70
    wf = np.where(r < 60, 1.0, np.where(r < 75, 0.5, 0.0))
    return dict(scene_dates=DATES, water_freq=wf, lake=lake, grid=GRID, n_shore=40, n_auto=20,
                ok_fn=_ok)


def test_strata_and_auto_labels(synthetic):
    g = sample_candidates(**synthetic)
    assert set(g.stratum) == {"shore", "auto_water", "auto_land"}
    assert (g.stratum == "shore").sum() == 40
    assert (g.stratum == "auto_water").sum() == 10 and (g.stratum == "auto_land").sum() == 10
    assert g[g.stratum == "shore"].label.isna().all()
    assert (g[g.stratum == "auto_water"].label == "water").all()
    assert (g[g.stratum == "auto_land"].label == "land").all()
    assert (g[g.stratum != "shore"].source == "auto").all()
    assert g.id.is_unique and g.crs == "EPSG:2180"


def test_strata_follow_water_frequency(synthetic):
    g = sample_candidates(**synthetic)
    wf, lake = synthetic["water_freq"], synthetic["lake"]
    rc = (g.row.to_numpy(), g.col.to_numpy())
    f = wf[rc]
    assert ((f > 0.05) & (f < 0.95))[(g.stratum == "shore").to_numpy()].all()
    assert (f[(g.stratum == "auto_water").to_numpy()] >= 0.98).all()
    assert (f[(g.stratum == "auto_land").to_numpy()] == 0).all()
    # woda: >= 200 m od brzegu; ląd: >= 300 m od jeziora (r_pix 70 + 30)
    r = np.hypot(g.row - N / 2, g.col - N / 2)
    assert (r[g.stratum == "auto_water"] <= 70 - 20 + 1).all()
    assert (r[g.stratum == "auto_land"] >= 70 + 30 - 1).all()
    assert lake[rc][(g.stratum == "auto_water").to_numpy()].all()


def test_points_valid_in_their_scene(synthetic):
    g = sample_candidates(**synthetic)
    for d, s in g.groupby("date"):
        assert d in DATES
        assert _ok(d)[s.row.to_numpy(), s.col.to_numpy()].all()
    assert g.date.nunique() > 1


def test_xy_matches_pixel_centre(synthetic):
    g = sample_candidates(**synthetic)
    for _, p in g.head(5).iterrows():
        assert (p.x, p.y) == GRID.xy(p.row, p.col)
        assert (p.geometry.x, p.geometry.y) == (p.x, p.y)


def test_min_spacing_same_scene(synthetic):
    g = sample_candidates(**synthetic)
    for _, s in g.groupby("date"):
        pts = list(s.geometry)
        for i, a in enumerate(pts):
            for b in pts[i + 1:]:
                assert a.distance(b) >= 30


def test_deterministic_seed(synthetic):
    a, b = sample_candidates(**synthetic), sample_candidates(**synthetic)
    assert_geodataframe_equal(a, b)


def test_save_load_roundtrip(tmp_path, synthetic):
    g = sample_candidates(**synthetic)
    save(g, tmp_path / "l.gpkg")
    assert_geodataframe_equal(load(tmp_path / "l.gpkg"), g, check_dtype=False, check_like=True)


# --- serwer ------------------------------------------------------------------------

@pytest.fixture
def server(tmp_path):
    s2dir = tmp_path / "s2"
    s2dir.mkdir()
    rng = np.random.default_rng(0)
    with rasterio.open(s2dir / "2020-01-01.tif", "w", driver="GTiff", width=N, height=N, count=7,
                       dtype="float32", crs="EPSG:2180", transform=GRID.transform, nodata=np.nan) as ds:
        ds.write(rng.uniform(0, 0.3, (7, N, N)).astype("float32"))
    pts = [(100, 100, "shore", None, "auto"), (100, 120, "shore", None, "auto"),
           (50, 50, "shore", None, "auto"), (10, 10, "auto_land", "land", "auto")]
    rows = []
    for i, (r, c, st, lab, src) in enumerate(pts):
        x, y = GRID.xy(r, c)
        rows.append(dict(id=i, date="2020-01-01", row=r, col=c, x=x, y=y, stratum=st, label=lab,
                         source=src, geometry=Point(x, y)))
    path = tmp_path / "labels.gpkg"
    save(gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:2180"), path)
    srv = label_server.serve(port=0, labels_path=path, s2_dir=s2dir)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", path
    srv.shutdown()
    srv.server_close()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def _post(url, payload):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_server_index_and_crop(server):
    base, _ = server
    status, ctype, body = _get(base + "/")
    assert status == 200 and "text/html" in ctype and b"label" in body.lower()
    nxt = json.loads(_get(base + "/api/next")[2])
    assert {"id", "date", "x", "y", "lon", "lat"} <= set(nxt)
    assert 17 < nxt["lon"] < 18 and 50 < nxt["lat"] < 51
    status, ctype, png = _get(f"{base}/api/crop/{nxt['id']}.png")
    assert status == 200 and ctype == "image/png" and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_server_post_changes_file_and_next(server):
    base, path = server
    first = json.loads(_get(base + "/api/next")[2])
    assert first["total"] == 3 and first["done"] == 0
    _post(base + "/api/label", {"id": first["id"], "label": "water"})
    row = load(path).set_index("id").loc[first["id"]]
    assert row.label == "water" and row.source == "human"
    second = json.loads(_get(base + "/api/next")[2])
    assert second["id"] != first["id"] and second["done"] == 1
    _post(base + "/api/label", {"id": second["id"], "label": "skip"})
    assert load(path).set_index("id").loc[second["id"]].label == "skip"
    third = json.loads(_get(base + "/api/next")[2])
    assert third["id"] not in (first["id"], second["id"])
    _post(base + "/api/label", {"id": third["id"], "label": "land"})
    assert json.loads(_get(base + "/api/next")[2])["id"] is None


def test_server_rejects_bad_label(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base + "/api/label", {"id": 0, "label": "banana"})
    assert e.value.code == 400
