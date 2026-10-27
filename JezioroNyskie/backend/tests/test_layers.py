import dataclasses
import io

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer

from app.layers import (bottom_breaks, image_coordinates, render_bottom_png, render_uncertainty_png,
                        to_web_mercator)


def _img(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def test_known_pixel_lands_on_its_lonlat(products):
    marker = np.full(products.shape, np.nan, np.float32)
    marker[5, 7] = 1.0
    dst, tr = to_web_mercator(marker, products)
    r, c = np.argwhere(np.isfinite(dst)).mean(axis=0)
    x, y = rasterio.transform.xy(tr, r, c)
    lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform(x, y)
    exp = Transformer.from_crs(products.crs, 4326, always_xy=True).transform(
        *rasterio.transform.xy(products.transform, 5, 7))
    assert abs(lon - exp[0]) < 1.5e-4 and abs(lat - exp[1]) < 1e-4      # < ~10 m


def test_bool_layer_reprojects_via_float(products):
    dst, _ = to_web_mercator(products.in_model, products)
    assert dst.dtype == np.float32 and np.nanmax(dst) == 1.0


def test_coordinates_order(products):
    _, tr = to_web_mercator(products.z.astype(np.float32), products)
    tl, tr_, br, bl = image_coordinates(tr, (3, 3))
    assert tl[1] == tr_[1] > br[1] == bl[1] and tl[0] == bl[0] < tr_[0] == br[0]


def test_bottom_breaks_six_sorted(products):
    b = bottom_breaks(products)
    assert len(b) == 6 and b == sorted(b) and b[0] == 193.0 and b[-1] == 196.5
    assert all(round(x, 2) == x for x in b)


def test_bottom_png_transparent_outside(products):
    img = _img(render_bottom_png(products, "light"))
    assert img.mode == "RGBA" and img.getextrema()[3] == (0, 255)


def test_bottom_png_themes_differ_and_use_endpoint_colors(products):
    light = np.asarray(_img(render_bottom_png(products, "light")))
    dark = np.asarray(_img(render_bottom_png(products, "dark")))
    assert not np.array_equal(light, dark)
    opaque = light[light[..., 3] == 255][:, :3]
    colors = {tuple(c) for c in opaque}
    assert (0xC4, 0xDD, 0xE9) in colors          # klasa 0 (najpłycej)
    assert (0x21, 0x5C, 0x86) in colors          # klasa 4 (najgłębiej)


def test_uncertainty_png_empty_when_all_below_threshold(products):
    img = _img(render_uncertainty_png(products, "light"))
    assert img.mode == "RGBA" and img.getextrema()[3] == (0, 0)


def test_uncertainty_png_dots_2x2_in_4x4_cells(products):
    unc = np.full(products.shape, 0.2, np.float32)
    unc[3, 4] = 0.6
    p2 = dataclasses.replace(products, unc=unc)
    cells, _ = to_web_mercator(np.where(unc >= 0.5, 1.0, np.nan), products)
    n_cells = int(np.isfinite(cells).sum())
    img = np.asarray(_img(render_uncertainty_png(p2, "light")))
    assert img.shape[:2] == (cells.shape[0] * 4, cells.shape[1] * 4)
    ys, xs = np.nonzero(img[..., 3])
    assert len(ys) == 4 * n_cells and set(ys % 4) == {1, 2} and set(xs % 4) == {1, 2}
    assert set(map(tuple, img[ys, xs])) == {(0x0E, 0x24, 0x33, 153)}
    dark = np.asarray(_img(render_uncertainty_png(p2, "dark")))
    assert set(map(tuple, dark[ys, xs][:, :3])) == {(0xE6, 0xEE, 0xF3)}


def test_meta_has_layers(client):
    L = client.get("/api/meta").json()["layers"]
    assert len(L["bottom"]["coordinates"]) == 4 and len(L["bottom"]["breaks"]) == 6
    assert L["bottom"]["url"] == "/api/layers/bottom.png"
    assert L["uncertainty"]["url"] == "/api/layers/uncertainty.png" and L["uncertainty"]["min_unc"] == 0.5
    assert len(L["uncertainty"]["coordinates"]) == 4


def test_layer_endpoint_png_etag_and_304(client):
    r = client.get("/api/layers/bottom.png?theme=dark")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert r.headers["etag"].endswith('-bottom-dark"') and _img(r.content).mode == "RGBA"
    r2 = client.get("/api/layers/bottom.png?theme=dark", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b""
    assert client.get("/api/layers/uncertainty.png?theme=light").status_code == 200


def test_layer_endpoint_rejects_bad_theme(client):
    assert client.get("/api/layers/bottom.png?theme=neon").status_code == 422
    assert client.get("/api/layers/uncertainty.png").status_code == 422
