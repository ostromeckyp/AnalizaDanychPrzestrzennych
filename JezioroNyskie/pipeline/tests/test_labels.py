import json
import sys
import threading
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from affine import Affine
from geopandas.testing import assert_geodataframe_equal
from shapely.geometry import Point

from mielizna.grid import Grid
from mielizna import labels
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


def test_server_unlabel_restores_point(server):
    base, path = server
    first = json.loads(_get(base + "/api/next")[2])
    _post(base + "/api/label", {"id": first["id"], "label": "water"})
    assert json.loads(_get(base + "/api/next")[2])["id"] != first["id"]
    assert _post(base + "/api/unlabel", {"id": first["id"]}) == {"ok": True}
    row = load(path).set_index("id").loc[first["id"]]
    assert row.label is None and row.source == "auto"
    assert json.loads(_get(base + "/api/next")[2])["id"] == first["id"]


def test_server_unlabel_unknown_id(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base + "/api/unlabel", {"id": 999})
    assert e.value.code == 404


def test_next_reports_class_count(server):
    base, _ = server
    nxt = json.loads(_get(base + "/api/next")[2])
    assert nxt["n_class"] == 0
    _post(base + "/api/label", {"id": nxt["id"], "label": "water"})
    nxt = json.loads(_get(base + "/api/next")[2])
    assert nxt["n_class"] == 1
    _post(base + "/api/label", {"id": nxt["id"], "label": "skip"})
    assert json.loads(_get(base + "/api/next")[2])["n_class"] == 1


def test_human_class_labels_excludes_skip_and_none():
    assert labels.CLASS_LABELS == ("water", "land")
    g = gpd.GeoDataFrame(
        dict(label=["water", "land", "skip", None, "water", "land"],
             source=["human", "human", "human", "auto", "auto", "auto"]),
        geometry=[Point(0, 0)] * 6, crs="EPSG:2180")
    assert list(labels.human_class_labels(g).index) == [0, 1]


def test_set_label_save_error_leaves_memory_unchanged(server, monkeypatch):
    base, path = server
    first = json.loads(_get(base + "/api/next")[2])

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(labels, "save", boom)
    with pytest.raises(urllib.error.HTTPError):
        _post(base + "/api/label", {"id": first["id"], "label": "water"})
    assert json.loads(_get(base + "/api/next")[2])["id"] == first["id"]


# --- runda 2: shore_low, podejrzane punkty, kolejność w serwerze -------------------------

def _human_gdf(rows):
    """rows: (id, stratum, label, source, review) -> GeoDataFrame z kolumnami rundy 2."""
    recs = []
    for i, st, lab, src, rev in rows:
        recs.append(dict(id=i, date="2020-01-01", row=100 + i, col=100, x=float(i), y=0.0, stratum=st,
                         label=lab, source=src, label_v1=None, review=rev, geometry=Point(i, 0)))
    return gpd.GeoDataFrame(recs, geometry="geometry", crs="EPSG:2180")


def test_sample_extra_appends_only_new_rows(synthetic):
    old = sample_candidates(**synthetic)
    kw = dict(scene_dates=DATES, water_freq=np.where(np.hypot(*(np.mgrid[:N, :N] - N / 2)) > 90, 0.1, synthetic["water_freq"]),
              lake=synthetic["lake"], grid=GRID, ok_fn=_ok)
    new = labels.sample_extra(old, n=15, **kw)
    assert len(new) == 15 and (new.stratum == "shore_low").all()
    assert list(new.id) == list(range(old.id.max() + 1, old.id.max() + 16))
    assert new.label.isna().all() and (new.source == "auto").all()
    f = kw["water_freq"][new.row.to_numpy(), new.col.to_numpy()]
    assert ((f > 0.05) & (f <= 0.30)).all()
    used = set(zip(old.row, old.col))
    assert not used & set(zip(new.row, new.col))
    # odstęp 30 m względem WSZYSTKICH punktów tej samej sceny (starych i nowych)
    both = pd.concat([old, new])
    for _, s in both.groupby("date"):
        pts = list(s.geometry)
        for i, a in enumerate(pts):
            for b in pts[i + 1:]:
                assert a.distance(b) >= 30
    for d, s in new.groupby("date"):
        assert _ok(d)[s.row.to_numpy(), s.col.to_numpy()].all()
    again = labels.sample_extra(old, n=15, **kw)
    assert_geodataframe_equal(new, again)


def test_sample_extra_leaves_existing_rows_identical(tmp_path, synthetic):
    old = sample_candidates(**synthetic)
    save(old, tmp_path / "old.gpkg")
    old = load(tmp_path / "old.gpkg")
    wf = np.full((N, N), 0.1)
    new = labels.sample_extra(old, scene_dates=DATES, water_freq=wf, lake=synthetic["lake"], grid=GRID,
                              n=10, ok_fn=_ok)
    merged = pd.concat([old, new], ignore_index=True)
    save(merged, tmp_path / "m.gpkg")
    back = load(tmp_path / "m.gpkg")
    assert_geodataframe_equal(back.iloc[:len(old)].reset_index(drop=True), old, check_dtype=False)


def test_mark_suspect_resets_only_low_human_water():
    g = _human_gdf([(0, "shore", "water", "human", False),   # podejrzany
                    (1, "shore", "water", "human", False),   # OK
                    (2, "shore", "land", "human", False),    # land: bez zmian
                    (3, "shore", "skip", "human", False),
                    (4, "auto_water", "water", "auto", False),
                    (5, "shore", None, "auto", False)])
    margin = pd.Series({0: -0.5, 1: -0.1, 2: -0.9, 3: -0.9, 4: -0.9, 5: -0.9})
    out, ids = labels.mark_suspect(g, margin)
    assert ids == [0]
    r = out.set_index("id")
    assert r.loc[0, "label"] is None and r.loc[0, "source"] == "auto"
    assert r.loc[0, "label_v1"] == "water" and bool(r.loc[0, "review"])
    assert r.loc[1, "label"] == "water" and r.loc[1, "label_v1"] == "water" and not r.loc[1, "review"]
    assert r.loc[2, "label"] == "land" and r.loc[2, "label_v1"] == "land"
    assert r.loc[3, "label_v1"] == "skip"
    assert r.loc[4, "label_v1"] is None and r.loc[5, "label_v1"] is None
    assert not r.loc[[1, 2, 3, 4, 5], "review"].any()
    assert g.loc[0, "label"] == "water"   # wejście nie jest mutowane


def test_save_load_roundtrip_new_columns(tmp_path):
    g = _human_gdf([(0, "shore", None, "auto", True), (1, "shore", "land", "human", False)])
    g.loc[0, "label_v1"] = "water"
    save(g, tmp_path / "r.gpkg")
    back = load(tmp_path / "r.gpkg")
    assert back.review.tolist() == [True, False] and back.review.dtype == bool
    assert back.label_v1.tolist() == ["water", None]
    assert back.label.tolist() == [None, "land"]


def test_load_old_file_without_new_columns(tmp_path, synthetic):
    g = sample_candidates(**synthetic).drop(columns=["label_v1", "review"])
    g.to_file(tmp_path / "old.gpkg", layer="labels", driver="GPKG")
    back = load(tmp_path / "old.gpkg")
    assert back.review.dtype == bool and not back.review.any()
    assert back.label_v1.isna().all()


@pytest.fixture
def server2(tmp_path):
    s2dir = tmp_path / "s2"
    s2dir.mkdir()
    with rasterio.open(s2dir / "2020-01-01.tif", "w", driver="GTiff", width=N, height=N, count=7,
                       dtype="float32", crs="EPSG:2180", transform=GRID.transform, nodata=np.nan) as ds:
        ds.write(np.full((7, N, N), 0.1, "float32"))
    g = _human_gdf([(0, "shore_low", None, "auto", False), (1, "shore", None, "auto", False),
                    (2, "shore", None, "auto", True), (3, "shore_low", None, "auto", True),
                    (4, "auto_land", "land", "auto", False)])
    g.loc[2, "label_v1"] = "water"
    g.loc[3, "label_v1"] = "land"
    path = tmp_path / "labels.gpkg"
    save(g, path)
    srv = label_server.serve(port=0, labels_path=path, s2_dir=s2dir)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", path
    srv.shutdown()
    srv.server_close()


def test_next_order_review_then_shore_then_shore_low(server2):
    base, _ = server2
    seen = []
    for _ in range(4):
        nxt = json.loads(_get(base + "/api/next")[2])
        assert "label_v1" not in nxt and "label" not in nxt     # stara etykieta nie trafia na stronę
        seen.append(nxt["id"])
        _post(base + "/api/label", {"id": nxt["id"], "label": "water"})
    assert seen == [2, 3, 1, 0]
    nxt = json.loads(_get(base + "/api/next")[2])
    assert nxt["id"] is None and nxt["n_review"] == 0


def test_next_reports_remaining_review_and_unchanged_n_class(server2):
    base, path = server2
    nxt = json.loads(_get(base + "/api/next")[2])
    assert nxt["n_review"] == 2 and nxt["n_class"] == 0 and nxt["total"] == 4
    _post(base + "/api/label", {"id": nxt["id"], "label": "land"})
    nxt = json.loads(_get(base + "/api/next")[2])
    assert nxt["n_review"] == 1 and nxt["n_class"] == 1
    row = load(path).set_index("id").loc[2]
    assert row.label == "land" and row.source == "human" and bool(row.review) and row.label_v1 == "water"


def test_unlabel_returns_review_point_to_queue(server2):
    base, _ = server2
    _post(base + "/api/label", {"id": 2, "label": "land"})
    _post(base + "/api/unlabel", {"id": 2})
    nxt = json.loads(_get(base + "/api/next")[2])
    assert nxt["id"] == 2 and nxt["n_review"] == 2
