"""Linia brzegowa z maski wody.

Co robi: z maski 0/1/255 buduje linię brzegową największego zbiornika i liczy powierzchnię wody.
Dlaczego tak: linia służy do rysunku i kontroli; powierzchnia z pikseli jest dokładna, a
  uproszczona geometria już nie, więc liczymy ją z maski.
Wejście → wyjście: maska uint8 + transformacja afiniczna → (geometria linii, km²).
Jak to obronić: maski zostają na dysku, a dalsze kroki (mapa mielizn) korzystają z pikseli
  brzegu, nie z uproszczonej linii.
"""
import numpy as np
from rasterio import features
from shapely.geometry import LineString, shape

SIMPLIFY_M = 5.0


def mask_to_shoreline(mask: np.ndarray, transform) -> tuple:
    """Linia brzegowa największego poligonu wody i powierzchnia wody w km².

    Co robi: wektoryzuje piksele == 1 (8-łączność), wybiera największy poligon, bierze jego
      granicę (z wyspami) jako (Multi)LineString i upraszcza o 5 m. Powierzchnia = liczba pikseli
      == 1 × |a·e| (255 pominięte), liczona z maski, nie z geometrii po uproszczeniu.
    Dlaczego tak: 5 m to pół piksela, więc uproszczenie nie zmienia linii w skali danych.
    Wejście → wyjście: maska uint8 (H, W), Affine → (BaseGeometry, float km²); brak wody →
      (pusty LineString, 0.0).
    Jak to obronić: test kwadratu 10×10 px (0,01 km², obwód 400 m).
    """
    water = mask == 1
    n = int(water.sum())
    area = n * abs(transform.a * transform.e) / 1e6
    if n == 0:
        return LineString(), 0.0
    polys = [shape(g) for g, v in features.shapes(water.astype(np.uint8), mask=water,
                                                   transform=transform, connectivity=8)]
    biggest = max(polys, key=lambda p: p.area)
    return biggest.boundary.simplify(SIMPLIFY_M), float(area)
