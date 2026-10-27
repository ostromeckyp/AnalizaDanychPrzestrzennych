#!/usr/bin/env python3
"""Druga runda sprawdzeń źródeł danych dla projektu "Mielizna" (Jezioro Nyskie).

Tylko biblioteka standardowa. Uruchom:  python3 scripts/check_sources_2.py
Wyniki (CSV/JSON) zapisuje w ./data/raw/check/  — te pliki przydadzą się w implementacji.
Pełny przebieg trwa kilka minut (pełna lista scen S2 i Wayback).
"""
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter

BBOX = (17.20, 50.425, 17.32, 50.485)  # lon_min, lat_min, lon_max, lat_max (BRIEF §4, v1.5)
BBOX_2180_NE = (285500, 372000, 292500, 381000)  # N_min, E_min, N_max, E_max (EPSG:2180, oś N,E)
UA = {"User-Agent": "mielizna-source-check/2.0 (projekt naukowy, Politechnika Opolska)"}
OUT = os.path.join("data", "raw", "check")
os.makedirs(OUT, exist_ok=True)
results = []


def report(name, ok, detail):
    results.append((name, ok, detail))
    print(f"[{'OK ' if ok else 'BŁĄD'}] {name}: {detail}", flush=True)


def get(url, data=None, headers=None, timeout=90, follow=True):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    if follow:
        opener = urllib.request.build_opener()
    else:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
    with opener.open(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def save(name, data, mode="wb"):
    p = os.path.join(OUT, name)
    with open(p, mode) as f:
        f.write(data)
    return p


def local(tag):
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# 1. Sentinel-2: pełna lista scen 2017–dziś (Earth Search, paginacja)
# ---------------------------------------------------------------------------
def s2_full_list():
    base = "https://earth-search.aws.element84.com/v1/search"
    body = {"collections": ["sentinel-2-l2a"], "bbox": list(BBOX),
            "datetime": "2017-01-01T00:00:00Z/2026-12-31T23:59:59Z",
            "limit": 200, "query": {"eo:cloud_cover": {"lt": 60}},
            "fields": {"include": ["id", "properties.datetime", "properties.eo:cloud_cover",
                                   "properties.s2:mgrs_tile", "properties.mgrs:utm_zone",
                                   "properties.mgrs:latitude_band", "properties.mgrs:grid_square"],
                       "exclude": ["assets", "links", "geometry"]}}
    rows, pages, nxt = [], 0, None
    try:
        while True:
            pages += 1
            payload = nxt if nxt is not None else body
            _, _, b = get(base, json.dumps(payload).encode(), {"Content-Type": "application/json"})
            j = json.loads(b)
            for f in j.get("features", []):
                p = f.get("properties", {})
                tile = p.get("s2:mgrs_tile") or "".join(str(p.get(k, "")) for k in
                                                         ("mgrs:utm_zone", "mgrs:latitude_band", "mgrs:grid_square"))
                rows.append((f["id"], p.get("datetime", ""), p.get("eo:cloud_cover"), tile))
            link = next((l for l in j.get("links", []) if l.get("rel") == "next"), None)
            if not link or pages > 60:
                break
            nxt = link.get("body") or None
            if nxt is not None and (link.get("merge") or "collections" not in nxt):
                nxt = {**body, **nxt}
            if nxt is None:  # paginacja GET
                _, _, b = get(link["href"])
                break
        rows.sort(key=lambda r: r[1])
        with open(os.path.join(OUT, "s2_scenes_earthsearch.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "datetime", "cloud_cover", "mgrs_tile"])
            w.writerows(rows)
        per_year = Counter(r[1][:4] for r in rows)
        clear = Counter(r[1][:4] for r in rows if (r[2] or 100) < 20)
        tiles = Counter(r[3] for r in rows)
        report("S2 pełna lista scen (Earth Search, chmury<60%)", bool(rows),
               f"{len(rows)} scen, kafle {dict(tiles)}; na rok (wszystkie/<20%): "
               + ", ".join(f"{y}: {per_year[y]}/{clear[y]}" for y in sorted(per_year))
               + f" -> {OUT}/s2_scenes_earthsearch.csv")
    except Exception as e:
        report("S2 pełna lista scen (Earth Search)", False, repr(e))


# ---------------------------------------------------------------------------
# 2. LiDAR i NMT: skorowidze WFS -> daty pomiaru, linki do plików
# ---------------------------------------------------------------------------
WFS = {
    "LAZ EVRF2007": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/DanePomiaroweLidarEVRF2007/WFS/Skorowidze",
    "LAZ KRON86": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/DanePomiaroweLidarKRON86/WFS/Skorowidze",
    "NMT EVRF2007": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NumerycznyModelTerenuEVRF2007/WFS/Skorowidze",
    "NMT KRON86": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NumerycznyModelTerenuKRON86/WFS/Skorowidze",
    "ORTO": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WFS/Skorowidze",
}


def wfs_features(url, typename):
    """Zwraca listę słowników atrybutów (bez geometrii) dla BBOX projektu."""
    tries = [
        f"{BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]},urn:ogc:def:crs:EPSG::4326",
        ",".join(map(str, BBOX_2180_NE)) + ",urn:ogc:def:crs:EPSG::2180",
        f"{BBOX_2180_NE[1]},{BBOX_2180_NE[0]},{BBOX_2180_NE[3]},{BBOX_2180_NE[2]},EPSG:2180",
    ]
    last = None
    for bb in tries:
        q = urllib.parse.urlencode({"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                                    "TYPENAMES": typename, "COUNT": "200", "BBOX": bb})
        try:
            _, _, b = get(url + "?" + q, timeout=120)
            root = ET.fromstring(b)
            if local(root.tag) == "ExceptionReport":
                last = b[:300]
                continue
            feats = []
            for m in root.iter():
                if local(m.tag) in ("member", "featureMember"):
                    for feat in m:
                        attrs = {}
                        for child in feat:
                            if len(child) == 0 and child.text and child.text.strip():
                                attrs[local(child.tag)] = child.text.strip()
                        feats.append(attrs)
            if feats:
                return feats, bb
        except Exception as e:  # noqa
            last = repr(e)
    return [], last


def lidar_dates():
    summary = {}
    for label, url in WFS.items():
        try:
            _, _, b = get(url + "?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetCapabilities", timeout=120)
            types = sorted(set(re.findall(r"<(?:\w+:)?Name>([^<]+)</", b.decode("utf-8", "replace"))))
            types = [t for t in types if ":" in t]
        except Exception as e:
            report(f"WFS {label} GetCapabilities", False, repr(e))
            continue
        if label == "ORTO":  # tylko najnowsze lata, żeby nie mielić 70 warstw
            types = [t for t in types if re.search(r"20(1[5-9]|2\d)", t)]
        found = {}
        for t in types:
            feats, info = wfs_features(url, t)
            if feats:
                found[t] = feats
        summary[label] = found
        if not found:
            report(f"WFS {label}", False, f"warstwy: {types[:12]}…; brak obiektów w BBOX ({info})")
            continue
        keys = sorted({k for fs in found.values() for f in fs for k in f})
        report(f"WFS {label}", True, f"warstwy z danymi w BBOX: {list(found)}; pola: {keys}")
        for t, fs in found.items():
            for f in fs[:3]:
                short = {k: (v if len(v) < 90 else v[:87] + "…") for k, v in f.items()}
                print(f"      {t}: {short}")
    save("wfs_skorowidze.json", json.dumps(summary, ensure_ascii=False, indent=1), "w")
    print(f"      -> pełne atrybuty: {OUT}/wfs_skorowidze.json")


# ---------------------------------------------------------------------------
# 3. Ortofotomapa: WMTS (podkład do etykietowania) + mały kafel WMS
# ---------------------------------------------------------------------------
def ortho():
    u = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/HighResolution?SERVICE=WMTS&REQUEST=GetCapabilities"
    try:
        _, _, b = get(u, timeout=120)
        ok = b"TileMatrixSet" in b
        report("Ortofoto WMTS HighResolution GetCapabilities", ok, f"{len(b)} B")
    except Exception as e:
        report("Ortofoto WMTS HighResolution", False, repr(e))
    q = urllib.parse.urlencode({"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "Raster",
                                "STYLES": "", "CRS": "EPSG:2180", "FORMAT": "image/jpeg",
                                "BBOX": "288500,375500,289000,376000", "WIDTH": "500", "HEIGHT": "500"})
    try:
        _, ct, b = get("https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution?" + q)
        ok = ct.startswith("image/")
        p = save("orto_test.jpg", b) if ok else None
        report("Ortofoto WMS GetMap (500x500 m)", ok, f"{ct}, {len(b)} B" + (f" -> {p}" if p else f": {b[:200]!r}"))
    except Exception as e:
        report("Ortofoto WMS GetMap", False, repr(e))


# ---------------------------------------------------------------------------
# 4. Poziom/objętość zbiornika
# ---------------------------------------------------------------------------
OLD = ("https://wroclaw.wody.gov.pl/images/Pliki_do_pobrania/Sytuacja_Hydrologiczna_Raporty/"
       "2023-05/Komunikat_o_sytuacji_w_regionie_z_dn_08-05-2023.pdf")


def reservoir():
    # 4a. stary adres RZGW bezpośrednio
    try:
        s, ct, b = get(OLD, follow=False)
        report("RZGW stary PDF (bezpośrednio)", b[:4] == b"%PDF", f"HTTP {s}, {ct}, {len(b)} B")
    except urllib.error.HTTPError as e:
        report("RZGW stary PDF (bezpośrednio)", False, f"HTTP {e.code} -> {e.headers.get('Location')}")
    except Exception as e:
        report("RZGW stary PDF (bezpośrednio)", False, repr(e))

    # 4b. Wayback Machine: ile komunikatów zarchiwizowano (CDX)
    cdx = ("https://web.archive.org/cdx/search/cdx?url=wroclaw.wody.gov.pl/images/Pliki_do_pobrania/"
           "Sytuacja_Hydrologiczna_Raporty/&matchType=prefix&output=json&fl=timestamp,original,statuscode,mimetype"
           "&filter=statuscode:200&collapse=urlkey&limit=20000")
    try:
        _, _, b = get(cdx, timeout=180)
        rows = json.loads(b)[1:] if b.strip() else []
        pdfs = [r for r in rows if r[1].lower().endswith(".pdf")]
        months = Counter(re.search(r"Raporty/(\d{4}-\d{2})/", r[1]).group(1)
                         for r in pdfs if re.search(r"Raporty/(\d{4}-\d{2})/", r[1]))
        with open(os.path.join(OUT, "rzgw_wayback_index.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["timestamp", "original", "status", "mime"])
            w.writerows(pdfs)
        years = Counter(m[:4] for m in months.elements())
        report("RZGW archiwum w Wayback (CDX)", bool(pdfs),
               f"{len(pdfs)} PDF; na rok: {dict(sorted(years.items()))}; miesięcy: {len(months)} "
               f"-> {OUT}/rzgw_wayback_index.csv")
        if pdfs:
            ts, orig = pdfs[len(pdfs) // 2][:2]
            _, _, pb = get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=120)
            p = save("rzgw_wayback_sample.pdf", pb)
            report("RZGW pobranie PDF z Wayback", pb[:4] == b"%PDF", f"{len(pb)} B -> {p} ({orig.rsplit('/', 1)[-1]})")
    except Exception as e:
        report("RZGW archiwum w Wayback (CDX)", False, repr(e))

    # 4c. gov.pl: lista dziennych komunikatów krajowych (tabela zbiorników, wiersz Nysa)
    try:
        _, _, b = get("https://www.gov.pl/web/wody-polskie/sytuacja-hydrologiczna", timeout=120)
        t = b.decode("utf-8", "replace")
        links = re.findall(r'href="(/attachment/[0-9a-f-]{36})"[^>]*>(.*?)</a>', t, flags=re.S)
        dated = []
        for href, txt in links:
            txt = re.sub(r"<[^>]+>|\s+", " ", txt).strip()
            m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", txt)
            if m:
                dated.append((f"{m.group(3)}-{m.group(2)}-{m.group(1)}", "https://www.gov.pl" + href, txt))
        dated.sort()
        with open(os.path.join(OUT, "govpl_komunikaty_index.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "url", "title"])
            w.writerows(dated)
        span = f"{dated[0][0]} .. {dated[-1][0]}" if dated else "-"
        report("gov.pl lista komunikatów krajowych", bool(dated),
               f"{len(dated)} komunikatów z datą, zakres {span} -> {OUT}/govpl_komunikaty_index.csv")
        if dated:
            d, url, _ = dated[-1]
            _, ct, pb = get(url, timeout=120)
            p = save(f"govpl_komunikat_{d}.pdf", pb)
            report("gov.pl pobranie komunikatu", pb[:4] == b"%PDF", f"{ct}, {len(pb)} B -> {p}")
    except Exception as e:
        report("gov.pl lista komunikatów krajowych", False, repr(e))

    # 4d. RZGW Wrocław: komunikat o piętrzeniu zbiornika Nysa w 2025 (znana rzędna 197,84–198,00 m)
    try:
        s, _, b = get("https://www.gov.pl/web/wody-polskie-wroclaw/"
                      "komunikat-wod-polskich-rzgw-we-wroclawiu-dotyczacy-poziomu-pietrzenia-zbiornika-wodnego-nysa")
        t = b.decode("utf-8", "replace")
        report("RZGW komunikat piętrzenie Nysa 2025", "197,84" in t, f"HTTP {s}; zawiera '197,84': {'197,84' in t}")
    except Exception as e:
        report("RZGW komunikat piętrzenie Nysa 2025", False, repr(e))


# ---------------------------------------------------------------------------
# 5. IMGW: archiwum dobowe, stacja NYSA (150170060)
# ---------------------------------------------------------------------------
def imgw():
    base = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/"
    try:
        _, _, b = get(base + "2023/")
        zips = re.findall(r'href="([^"]+\.zip)"', b.decode("utf-8", "replace"))
        report("IMGW katalog dobowe/2023", bool(zips), f"{len(zips)} ZIP: {zips[:4]}…")
        if zips:
            z = next((x for x in zips if "_05" in x), zips[0])
            _, _, zb = get(base + "2023/" + z, timeout=180)
            with zipfile.ZipFile(io.BytesIO(zb)) as zf:
                name = zf.namelist()[0]
                txt = zf.read(name).decode("cp1250", "replace")
            rows = [l for l in txt.splitlines() if "150170060" in l]
            report("IMGW plik dobowy, stacja NYSA 150170060", bool(rows),
                   f"{z}: {len(rows)} wierszy; przykład: {rows[0][:120] if rows else '-'}")
    except Exception as e:
        report("IMGW archiwum dobowe", False, repr(e))


# ---------------------------------------------------------------------------
# 6. OSM: przystanie/slipy ze współrzędnymi + obrys jeziora (kontrola BBOX)
# ---------------------------------------------------------------------------
def osm():
    s, w, n, e = BBOX[1], BBOX[0], BBOX[3], BBOX[2]
    ql = (f'[out:json][timeout:90];('
          f'nwr["leisure"~"marina|slipway"]({s},{w},{n},{e});'
          f'nwr["natural"="water"]["name"~"Nysk",i]({s - 0.1},{w - 0.1},{n + 0.1},{e + 0.1});'
          f');out tags center bb;')
    try:
        _, _, b = get("https://overpass-api.de/api/interpreter", urllib.parse.urlencode({"data": ql}).encode(),
                      timeout=120)
        el = json.loads(b)["elements"]
        save("osm_objects.json", json.dumps(el, ensure_ascii=False, indent=1), "w")
        for x in el:
            c = x.get("center") or {"lat": x.get("lat"), "lon": x.get("lon")}
            print(f"      {x['type']}/{x['id']}: {x.get('tags', {}).get('leisure') or x.get('tags', {}).get('natural')}"
                  f" '{x.get('tags', {}).get('name')}' @ {c.get('lat')},{c.get('lon')}"
                  + (f" bounds={x['bounds']}" if 'bounds' in x else ""))
        lake = [x for x in el if x.get("tags", {}).get("natural") == "water"]
        report("OSM obiekty + obrys jeziora", bool(el),
               f"{len(el)} obiektów; jezioro: {'tak' if lake else 'NIE'} -> {OUT}/osm_objects.json")
    except Exception as e:
        report("OSM Overpass", False, repr(e))


if __name__ == "__main__":
    t0 = time.time()
    for step in (s2_full_list, lidar_dates, ortho, reservoir, imgw, osm):
        print(f"\n--- {step.__name__} ---", flush=True)
        step()
    print(f"\n=== PODSUMOWANIE ({time.time() - t0:.0f} s) ===")
    for n, ok, _ in results:
        print(("OK   " if ok else "BŁĄD ") + n)
    print(f"\nPliki: {OUT}/  — wklej mi CAŁY wypis.")
    sys.exit(0 if all(o for _, o, _ in results) else 1)
