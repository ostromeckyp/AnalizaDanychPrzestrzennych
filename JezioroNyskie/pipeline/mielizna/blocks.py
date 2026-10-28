"""Szachownica bloków 500 m: podział siatki modelu na bloki „calib” i „valid”.

Co robi: przypisuje punktom (x, y) rolę bloku: „calib” (wolno z nich kalibrować poziom wody,
  wariant A) albo „valid” (zarezerwowane do walidacji dna względem NMT).
Dlaczego tak: gdyby poziom wody był liczony z tych samych miejsc NMT, z którymi później porównujemy
  dno, walidacja byłaby krążąca (przeciek). Szachownica bloków wyrównana do siatki modelu daje
  rozłączne zbiory i prostą regułę, którą łatwo sprawdzić okiem.
Wejście → wyjście: tablice x, y [m, EPSG:2180], Grid, rozmiar bloku → tablica „calib”/„valid”;
  i, j = indeksy bloku liczone od lewego dolnego narożnika siatki (xmin, ymin); „calib” gdy (i + j) % 2 == 0.
  Punkty poza siatką też dostają rolę (indeksy ujemne lub duże; parzystość działa dalej).
Jak to obronić: reguła jest deterministyczna i niezależna od danych; blok 500 m = 50 pikseli modelu,
  więc granice bloków pokrywają się z granicami pikseli.
"""
import numpy as np

from mielizna.grid import Grid


def block_role(x: np.ndarray, y: np.ndarray, grid: Grid, size_m: float = 500) -> np.ndarray:
    xmin, ymin, _, _ = grid.bounds()
    i = np.floor((np.asarray(x, float) - xmin) / size_m).astype(int)
    j = np.floor((np.asarray(y, float) - ymin) / size_m).astype(int)
    return np.where((i + j) % 2 == 0, "calib", "valid")
