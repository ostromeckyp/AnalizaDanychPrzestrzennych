"""Siatka wzorcowa (EPSG:2180, 10 m) wspólna dla wszystkich warstw."""
import math
from dataclasses import dataclass

from affine import Affine

from mielizna.config import load_config


@dataclass(frozen=True)
class Grid:
    crs: str
    transform: Affine
    width: int
    height: int

    def bounds(self) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax)."""
        t = self.transform
        xmax = t.c + self.width * t.a
        ymin = t.f + self.height * t.e
        return (t.c, ymin, xmax, t.f)

    def xy(self, row: int, col: int) -> tuple[float, float]:
        """Współrzędne środka piksela."""
        x, y = self.transform @ (col + 0.5, row + 0.5)
        return (x, y)

    def rowcol(self, x: float, y: float) -> tuple[int, int]:
        """Wiersz i kolumna piksela zawierającego punkt (x, y)."""
        col, row = ~self.transform @ (x, y)
        return (math.floor(row), math.floor(col))


def reference_grid(cfg: dict | None = None) -> Grid:
    """Buduje siatkę wzorcową z sekcji `grid` konfiguracji."""
    g = (cfg or load_config())["grid"]
    res = g["res"]
    width = round((g["xmax"] - g["xmin"]) / res)
    height = round((g["ymax"] - g["ymin"]) / res)
    return Grid(
        crs=g["crs"],
        transform=Affine(res, 0, g["xmin"], 0, -res, g["ymax"]),
        width=width,
        height=height,
    )
