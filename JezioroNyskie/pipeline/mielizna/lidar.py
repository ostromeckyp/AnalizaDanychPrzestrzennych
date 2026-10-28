"""Epoki LiDAR: data nalotu z czasu GPS oraz klasa i poziom wody z chmury punktów.

Co robi: z plików LAZ GUGiK (a) odczytuje daty nalotu z pola `gps_time`, (b) wyznacza klasę
  punktów wody (najliczniejsza w rdzeniu jeziora, bez klasy 2) i (c) liczy poziom wody jako
  medianę z tych punktów (+ IQR i liczność).
Dlaczego tak: poziom wody w dniu nalotu to najlepsze (wariant A) źródło rzędnej `h_t`, ale
  tylko jeśli wiemy KIEDY był nalot i W JAKIM układzie wysokości. Czas GPS bywa dwojaki:
  "adjusted standard" (bit 0 global_encoding = 1: sekundy od 1980-01-06 minus 10^9) daje datę,
  "GPS week time" (bit 0 = 0: sekundy w tygodniu) NIE daje daty wiarygodnie, więc zwracamy [] i
  ostrzegamy, zamiast zgadywać. Rdzeń jeziora (obrys - 200 m) omija brzeg z trzcinami i
  falowaniem. Klasę wody ustalają dane (ASPRS: 9), nie założenie z briefu (8).
Wejście → wyjście: ścieżka (lub lista ścieżek) LAZ + wielokąt rdzenia w EPSG:2180 → lista dat,
  numer klasy, (mediana z, IQR, n). Pliki czytane porcjami (`chunk_iterator`), nigdy w całości.
Jak to obronić: data = 1980-01-06 + (t + 1e9 - 18) s (18 s = GPS-UTC od 2017; dla 2011 było 15 s,
  co dla nalotów w ciągu dnia nie zmienia daty); mediana jest odporna na pojedyncze odbicia, a IQR
  i n pokazują rozrzut i liczność próby.
"""
import logging
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import laspy
import numpy as np
from laspy.header import GpsTimeType
from shapely import contains_xy

GPS_EPOCH = date(1980, 1, 6)
GPS_UTC_LEAP_S = 18
ADJUSTED_OFFSET_S = 1e9
CHUNK = 2_000_000
log = logging.getLogger(__name__)


def _paths(paths) -> list[Path]:
    return [Path(paths)] if isinstance(paths, (str, Path)) else [Path(p) for p in paths]


def flight_dates(path: Path) -> list[date]:
    """Unikalne, posortowane daty (UTC) nalotu z `gps_time`; [] dla GPS week time (z ostrzeżeniem)."""
    days: set[int] = set()
    with laspy.open(str(path)) as r:
        if r.header.global_encoding.gps_time_type != GpsTimeType.STANDARD:
            log.warning("%s: GPS week time (global_encoding bit 0 = 0) - daty nalotu nie da się odczytać", Path(path).name)
            return []
        for ch in r.chunk_iterator(CHUNK):
            t = np.asarray(ch.gps_time, dtype=float) + ADJUSTED_OFFSET_S - GPS_UTC_LEAP_S
            days.update(np.unique(np.floor(t / 86400.0)).astype(np.int64).tolist())
    return sorted(GPS_EPOCH + timedelta(days=int(d)) for d in days)


def _core_points(path: Path, lake_core):
    """Generator (klasa, z) tylko dla punktów w rdzeniu jeziora, porcjami."""
    minx, miny, maxx, maxy = lake_core.bounds
    with laspy.open(str(path)) as r:
        for ch in r.chunk_iterator(CHUNK):
            x, y = np.asarray(ch.x), np.asarray(ch.y)
            box_m = (x >= minx) & (x <= maxx) & (y >= miny) & (y <= maxy)
            if not box_m.any():
                continue
            m = np.zeros(len(x), bool)
            m[box_m] = contains_xy(lake_core, x[box_m], y[box_m])
            if m.any():
                yield np.asarray(ch.classification)[m], np.asarray(ch.z)[m]


def water_class(paths, lake_core) -> int:
    """Klasa o największej liczbie punktów w rdzeniu jeziora, bez klasy 2 (grunt)."""
    cnt: Counter = Counter()
    for p in _paths(paths):
        for c, _ in _core_points(p, lake_core):
            for k, n in zip(*np.unique(c, return_counts=True)):
                cnt[int(k)] += int(n)
    cnt.pop(2, None)
    if not cnt:
        raise ValueError("brak punktów (poza klasą 2) w rdzeniu jeziora")
    return cnt.most_common(1)[0][0]


def water_level(paths, lake_core, cls: int) -> tuple[float, float, int]:
    """(mediana z, IQR, n) punktów klasy `cls` w rdzeniu jeziora; (nan, nan, 0) gdy brak."""
    zs = [z[c == cls] for p in _paths(paths) for c, z in _core_points(p, lake_core)]
    z = np.concatenate(zs) if zs else np.array([])
    if z.size == 0:
        return float("nan"), float("nan"), 0
    q1, med, q3 = np.percentile(z, [25, 50, 75])
    return float(med), float(q3 - q1), int(z.size)
