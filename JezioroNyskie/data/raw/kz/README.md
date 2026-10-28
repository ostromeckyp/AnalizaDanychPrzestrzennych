# data/raw/kz

Mapa KŻ „Jezioro Nyskie (amatorska mapka dla wodniaków)”, W. Wróblewski (KŻ Nysa), aktualizacja 23.05.2023.

- Źródło: `docs/JN_2023_05_23__KZ.pdf` (jedna strona, jeden obraz 9867 x 4791 px).
- `kz_full.png` (poza gitem) powstaje z PDF przez `cd pipeline && uv run python 09_kz_digitize.py georef`
  (albo `make kz-georef`); nie wgrywać go do repozytorium.
- Warunki użycia i licencja: `data/reference/KZ_ZRODLO_I_WARUNKI.md` (nieodpłatnie, bez celów komercyjnych;
  każda kopia musi zawierać te warunki).
- OCR rzędnych (`make kz-spots`, `09_kz_digitize.py spots`) wykonano programem **tesseract 5.5.2** (leptonica 1.87.0;
  `tesseract --version`). Inna wersja może rozpoznać inne punkty i zmienić numery `id`; kontrola ręczna
  (`data/reference/kz_spot_qc.csv`) jest dopasowywana po kotwicy, a niedopasowane wiersze są zgłaszane jako WARNING.
