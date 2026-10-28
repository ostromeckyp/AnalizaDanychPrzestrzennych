# data/raw/nmt - NMT z GUGiK (pierścień brzegowy jeziora)

Źródło: Numeryczny Model Terenu, arkusze z `opendata.geoportal.gov.pl`, wybrane przez skorowidze WFS
(`NumerycznyModelTerenuEVRF2007` i `...KRON86`, warstwy `gugik:SkorowidzNMT<rok>`; adresy w `pipeline/config.yaml`, sekcja `lidar`).
Pobiera: `cd pipeline && make nmt` (`02_fetch_nmt.py`; `--dry-run` tylko plan i rozmiary). Wznawialne.

Układ: `<rok>/<godlo>.<ext>` (surowy ASC / XYZ.zip) oraz `<rok>/<godlo>.tif` (GeoTIFF EPSG:2180, tag `uklad_h`).
Epoki: 2011, 2017 (PL-KRON86-NH), 2022, 2024 (PL-EVRF2007-NH). Tylko arkusze z LiDAR-u (błąd śr. wys. <= 0,2 m);
NMT ze zdjęć lotniczych odrzucany. Obszar: `lake.boundary.buffer(shore_band_m)`.
Plik nie jest w gicie (`.gitignore`). Spis: `data/processed/lidar/inventory.csv`.
