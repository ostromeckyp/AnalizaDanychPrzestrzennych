# data/raw/lidar - chmury punktów LAZ z GUGiK

Źródło: skorowidze WFS `DanePomiaroweLidarEVRF2007` i `...KRON86` (warstwy `gugik:SkorowidzDanychPomiarowychLIDAR<rok>`),
pliki z `opendata.geoportal.gov.pl`. Pobiera: `cd pipeline && make nmt` (`02_fetch_nmt.py`).

Układ: `<rok>/<godlo>.laz`. Na epokę tylko `laz_sheets_per_epoch` arkuszy (największy udział wody jeziora, po jednym na
ćwiartkę obrysu). LAZ służy do daty nalotu (GPS time) i poziomu wody (klasa 8). Pliki poza gitem.

Pokrycie epok nad jeziorem: patrz `data/processed/lidar/plan.csv` i sekcja poniżej (uzupełniana po pobraniu).

## Pokrycie (pobranie 2026-10-28)
Każda z czterech epok (2011, 2017, 2022, 2024) ma arkusze LiDAR nad jeziorem; wybrano 4 arkusze LAZ na epokę (po jednym na ćwiartkę).
NMT w pierścieniu 300 m: 2011 - 10 arkuszy, 2017 - 2, 2022 - 2, 2024 - 10 (2017 i 2022 pokrywają tylko część brzegu).
Arkusze LAZ (moduł 1:1250) są małe (ok. 4-26 MB), NMT 1:5000 ok. 17-43 MB (ASC/XYZ). Serwer ignoruje `Range`, a na HEAD/GET odpowiada po ok. 40 s.
