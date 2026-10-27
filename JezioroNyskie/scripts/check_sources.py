#!/usr/bin/env python3
"""Sprawdza, czy źródła danych dla projektu "Mielizna" (Jezioro Nyskie) są osiągalne.

Tylko biblioteka standardowa. Uruchom u siebie:  python3 scripts/check_sources.py
Nic nie zapisuje poza małym plikiem testowym NMT w ./data/raw/check/.
"""
import json
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

BBOX = (17.20, 50.425, 17.32, 50.485)  # lon_min, lat_min, lon_max, lat_max (BRIEF §4, v1.5)
UA = {"User-Agent": "mielizna-source-check/1.0 (projekt naukowy, PO)"}
OUT = os.path.join("data", "raw", "check")
results = []


def report(name, ok, detail):
    results.append((name, ok, detail))
    print(f"[{'OK ' if ok else 'BŁĄD'}] {name}: {detail}", flush=True)


def get(url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def stac_search(name, base, collection, extra=None):
    body = {
        "collections": [collection],
        "bbox": list(BBOX),
        "datetime": "2023-05-01T00:00:00Z/2023-09-30T23:59:59Z",
        "limit": 100,
        "query": {"eo:cloud_cover": {"lt": 20}},
    }
    try:
        s, _, b = get(base + "/search", json.dumps(body).encode(),
                      {"Content-Type": "application/json"})
        feats = json.loads(b).get("features", [])
        if not feats:
            report(name, False, "0 scen (sprawdź bbox/okres)")
            return None
        a = feats[0]["assets"]
        report(name, True, f"{len(feats)} scen (chmury<20%, V-IX 2023); "
                           f"assety np.: {sorted(a)[:8]}…")
        return feats[0]
    except Exception as e:
        report(name, False, repr(e))
        return None


def read_range(name, href):
    """Czyta pierwsze 16 B pliku COG po HTTP Range -> dowód, że pobranie działa."""
    try:
        s, _, b = get(href, headers={"Range": "bytes=0-15"})
        magic = b[:4]
        ok = magic[:2] in (b"II", b"MM")
        report(name, ok, f"HTTP {s}, nagłówek TIFF: {magic!r}")
    except Exception as e:
        report(name, False, repr(e))


# 1. Sentinel-2: Earth Search (AWS, bez konta)
f = stac_search("S2 Earth Search STAC", "https://earth-search.aws.element84.com/v1",
                "sentinel-2-l2a")
if f:
    href = f["assets"].get("green", {}).get("href") or f["assets"].get("B03", {}).get("href")
    if href and href.startswith("http"):
        read_range("S2 Earth Search pobranie COG (Range)", href)
    else:
        report("S2 Earth Search pobranie COG", False, f"nietypowy href: {href}")

# 2. Sentinel-2: Planetary Computer (token SAS)
f = stac_search("S2 Planetary Computer STAC",
                "https://planetarycomputer.microsoft.com/api/stac/v1", "sentinel-2-l2a")
if f:
    try:
        _, _, tb = get("https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-2-l2a")
        tok = json.loads(tb)["token"]
        href = f["assets"]["B03"]["href"] + "?" + tok
        read_range("S2 Planetary Computer pobranie COG (SAS)", href)
    except Exception as e:
        report("S2 Planetary Computer token/pobranie", False, repr(e))

# 3. Sentinel-2: CDSE (samo wyszukiwanie; pobranie wymaga konta)
stac_search("S2 CDSE STAC (tylko katalog)", "https://stac.dataspace.copernicus.eu/v1",
            "sentinel-2-l2a")

# 4. NMT: WCS 2.0.1, mały wycinek GeoTIFF (EPSG:2180)
WCS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFF"
try:
    q = urllib.parse.urlencode({"SERVICE": "WCS", "VERSION": "2.0.1", "REQUEST": "DescribeCoverage",
                                "COVERAGEID": "DTM_PL-KRON86-NH_TIFF"})
    _, _, b = get(WCS + "?" + q)
    t = b.decode("utf-8", "replace")
    import re
    lc = re.search(r"<gml:lowerCorner>([^<]+)", t)
    uc = re.search(r"<gml:upperCorner>([^<]+)", t)
    report("NMT WCS DescribeCoverage", bool(lc), f"envelope: {lc and lc.group(1)} .. {uc and uc.group(1)} "
           "(oś: sprawdź kolejność N/E w CRS)")
except Exception as e:
    report("NMT WCS DescribeCoverage", False, repr(e))

try:
    # ~300x300 m w okolicy zapory (przybliżone EPSG:4326); test dostępności, nie analiza
    sub = [("Lat", "50.4600,50.4630"), ("Long", "17.3300,17.3340")]
    q = "SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage&COVERAGEID=DTM_PL-KRON86-NH_TIFF" \
        "&FORMAT=image/tiff&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326" \
        + "".join(f"&SUBSET={k}({v})" for k, v in sub)
    s, ct, b = get(WCS + "?" + q)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "nmt_test.tif")
    open(p, "wb").write(b)
    ok = b[:2] in (b"II", b"MM")
    report("NMT WCS GetCoverage (GeoTIFF)", ok,
           f"HTTP {s}, {ct}, {len(b)} B -> {p}" if ok else f"{ct}: {b[:200]!r}")
except urllib.error.HTTPError as e:
    report("NMT WCS GetCoverage (GeoTIFF)", False, f"HTTP {e.code}: {e.read()[:300]!r}")
except Exception as e:
    report("NMT WCS GetCoverage (GeoTIFF)", False, repr(e))

# 5. LiDAR: skorowidz WFS (daty nalotu, linki LAZ)
WFS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NumerycznyModelTerenuEVRF2007/WFS/Skorowidze"
try:
    _, _, b = get(WFS + "?SERVICE=WFS&REQUEST=GetCapabilities")
    names = sorted(set(__import__("re").findall(r"<(?:\w+:)?Name>([^<]+)</", b.decode("utf-8", "replace"))))
    report("LiDAR WFS skorowidze (EVRF2007)", True,
           f"typy: {names[:6]} — dalej: GetFeature z BBOX, pola z datą pomiaru i linkiem")
except Exception as e:
    report("LiDAR WFS skorowidze (EVRF2007)", False, repr(e))

# 6. IMGW: lista stacji hydrologicznych
base = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/"
try:
    _, _, b = get(base + "lista_stacji_hydro.csv")
    t = b.decode("cp1250", "replace")
    nysa = [l.strip() for l in t.splitlines() if "ysa" in l]
    report("IMGW lista stacji", True, f"{len(t.splitlines())} wierszy; z 'ysa': {nysa[:6]}")
except Exception as e:
    report("IMGW lista stacji", False, repr(e))

# 7. Wody Polskie: komunikat o zbiornikach
try:
    s, _, b = get("https://www.gov.pl/web/wody-polskie/komunikat-w-sprawie-sytuacji-na-zbiornikach-przeciwpowodziowych")
    report("Wody Polskie komunikat zbiorniki", "Nysa" in b.decode("utf-8", "replace"),
           f"HTTP {s}, {len(b)} B (szukam 'Nysa' w treści)")
except Exception as e:
    report("Wody Polskie komunikat zbiorniki", False, repr(e))

# 8. OSM Overpass: przystanie/slipy w bbox
try:
    ql = (f'[out:json][timeout:60];(nwr["leisure"="marina"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]});'
          f'nwr["leisure"="slipway"]({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]}););out tags center;')
    _, _, b = get("https://overpass-api.de/api/interpreter", urllib.parse.urlencode({"data": ql}).encode())
    el = json.loads(b)["elements"]
    report("OSM Overpass", True, f"{len(el)} obiektów (marina/slipway): "
           f"{[e.get('tags', {}).get('name') for e in el][:6]}")
except Exception as e:
    report("OSM Overpass", False, repr(e))

print("\n=== PODSUMOWANIE ===")
for n, ok, _ in results:
    print(("OK   " if ok else "BŁĄD ") + n)
print("\nWklej mi cały wynik (zwłaszcza linie BŁĄD).")
sys.exit(0 if all(o for _, o, _ in results) else 1)
