# Pipeline Mielizna (Jezioro Nyskie): od OSM i Sentinel-2 do modelu dna.
# Uruchamiaj z katalogu pipeline/.  `make help` wypisuje cele.
#
# Cel = plik wynikowy + nazwa "ludzka" (phony). Make porównuje daty plików, więc `make bottom`
# na gotowych danych NIE trenuje RF i NIE pobiera Sentinel-2 ponownie. Wymuszenie kroku:
#   make -W ../data/reference/labels.gpkg rf   (uznaj etykiety za zmienione -> retrening RF; `make -B rf` NIE
#                                               działa: 04a odmawia nadpisania etykiet)
#   make clean-model rf                         (usuń model RF i wytrenuj od nowa)
#   make -W <plik> ...                          (uznaj dowolny plik za zmieniony)
# Po zmianie config.yaml (np. exclude_dates) `make s2` ponownie uruchamia 01 (config.yaml jest zależnością
# CSV scen), a dalsze kroki kaskadowo; sam RF nie jest od CSV zależny (retrening tylko po zmianie etykiet).
# Skrypty same są też wznawialne (01: CSV + COG; 04: pomija gotowe sceny; 06a: cache PDF).

UV      ?= uv run python
PROC    := ../data/processed
REF     := ../data/reference
LABELS  := $(REF)/labels.gpkg
LAKE    := $(PROC)/lake.gpkg
S2CSV   := $(PROC)/scenes_candidates.csv
INVENT  := $(PROC)/lidar/inventory.csv
EPOCHS  := $(PROC)/lidar/epochs.csv
RFMODEL := $(PROC)/model/rf_model.joblib
STATS   := $(PROC)/classify_stats.csv
SHORES  := $(PROC)/shorelines.gpkg
BULLS   := $(PROC)/bulletins.csv
LEVELSA := $(PROC)/levels_a.csv
SCENES  := $(PROC)/scenes.json
BOTTOM  := $(PROC)/model/all/model_meta.json
KZMETA  := $(PROC)/kz/kz_meta.json
KZSPOTS := $(PROC)/kz/kz_spot_ocr.gpkg
KZCONT  := $(PROC)/kz/kz_contours.gpkg
ZWIR    := $(REF)/zwirownia.gpkg
MIN_HUMAN_LABELS := 150

.PHONY: help all osm nmt s2 labels label-candidates label-ui check-labels rf classify shorelines \
        bulletins lidar-epochs levels-a levels bottom kz-georef kz-spots kz-qc-ui kz-contours kz-gravel test clean-model
.DEFAULT_GOAL := help

help:
	@echo "Cele: osm nmt s2 label-candidates label-ui rf classify shorelines bulletins lidar-epochs levels-a levels bottom kz-georef all test clean-model"
	@echo "Kolejność: osm -> s2 -> label-candidates -> (ręczne etykiety: label-ui) -> rf -> classify"
	@echo "           -> shorelines -> bulletins -> levels -> bottom"

# `all` zatrzymuje się przed rf, jeśli jest < $(MIN_HUMAN_LABELS) ręcznych etykiet klas (R4/R15).
all:
	$(MAKE) osm s2 label-candidates
	$(MAKE) check-labels
	$(MAKE) rf classify shorelines bulletins levels bottom

osm: $(LAKE)
$(LAKE):                                   # 03: obrys jeziora, AOI, przystanie (Overpass, cache)
	$(UV) 03_fetch_osm.py

nmt: $(INVENT)
$(INVENT): config.yaml | $(LAKE)          # 02: skorowidze GUGiK, NMT (pierścień brzegowy) i LAZ (wznawialne; --dry-run: plan)
	$(UV) 02_fetch_nmt.py

s2: $(S2CSV)
$(S2CSV): config.yaml | $(LAKE)            # 01: wyszukiwanie STAC, scenes_candidates.csv, s2/*.tif (wznawialne)
	$(UV) 01_fetch_s2.py

labels: label-candidates                   # alias (R4): `labels` tylko generuje kandydatów
label-candidates: $(LABELS)
$(LABELS): | $(S2CSV)                      # 04a: losuje punkty; nie nadpisuje etykiet human (bez --force)
	$(UV) 04a_label_candidates.py

label-ui: $(LABELS)                        # ręczne etykietowanie: http://localhost:8765
	$(UV) tools/label_server.py

check-labels: $(LABELS)
	@$(UV) -c "from mielizna import labels as L; n=len(L.human_class_labels(L.load('$(LABELS)'))); \
	print(f'ręcznych etykiet klas: {n} (wymagane >= $(MIN_HUMAN_LABELS))'); raise SystemExit(0 if n >= $(MIN_HUMAN_LABELS) else 1)" \
	|| { echo "ZA MAŁO ETYKIET: uruchom 'make label-ui', oznacz punkty, potem 'make all'."; exit 1; }

rf: $(RFMODEL)
$(RFMODEL): $(LABELS)                      # 04b: trening i ocena RF (długi: ok. 550 dopasowań)
	$(MAKE) check-labels
	$(UV) 04b_train_rf.py

classify: $(STATS)
$(STATS): $(RFMODEL) $(S2CSV) $(LAKE)      # 04: maski RF/Otsu, P(woda), statystyki i QC scen
	$(UV) 04_classify.py

shorelines: $(SHORES)
$(SHORES): $(STATS)                        # 05: linie brzegowe + obrazki QC
	$(UV) 05_shorelines.py

lidar-epochs: $(EPOCHS)
$(EPOCHS): $(INVENT) | $(LAKE)             # 06b: data nalotu, poziom wody i poprawka KRON86->EVRF2007 (wymaga siatek PROJ GUGiK)
	$(UV) 06b_lidar_levels.py --epochs-only

bulletins: $(BULLS)
$(BULLS): $(S2CSV)                         # 06a: komunikaty RZGW/Wód Polskich (cache PDF)
	$(UV) 06a_fetch_bulletins.py

# levels-a: wariant A (poziom wody z NMT wzdłuż brzegu sceny). Zależy od STATS, nie od SHORES: 06 nadpisuje
# shorelines.gpkg (h_t), więc zależność od SHORES wymuszałaby przeliczanie w kółko.
levels-a: $(LEVELSA)
$(LEVELSA): $(STATS) $(BULLS) $(EPOCHS) | $(LAKE)   # 06b --scenes-only: levels_a.csv + levels_a_detail.csv
	$(UV) 06b_lidar_levels.py --scenes-only

# levels: A jest opcjonalny - zależność tylko gdy LiDAR został pobrany (inventory.csv istnieje przy czytaniu Makefile)
LEVELS_DEPS := $(SHORES) $(BULLS)
ifneq ($(wildcard $(INVENT)),)
LEVELS_DEPS += $(LEVELSA)
endif
levels: $(SCENES)
$(SCENES): $(LEVELS_DEPS)                  # 06: poziom wody h_t każdej sceny (A/R/B/C), krzywa powierzchnia-rzędna
	$(UV) 06_water_levels.py

bottom: $(BOTTOM)
$(BOTTOM): $(SCENES)                       # 07: model dna (okresy all, pre_flood, post_flood)
	$(UV) 07_bottom_model.py

# Kod georef (kz.py) celowo NIE jest zależnością (rzadko się zmienia); wymuszenie: rm $(KZMETA) && make kz-georef
# (`make -B kz-georef` odpytałoby też Overpass dla lake.gpkg).
kz-georef: $(KZMETA)
$(KZMETA): ../docs/JN_2023_05_23__KZ.pdf $(REF)/kz_gcp.csv $(LAKE)      # 09 georef: mapa KŻ -> EPSG:2180, RMSE na punktach wstrzymanych, werdykt
	$(UV) 09_kz_digitize.py georef

kz-spots: $(KZSPOTS)
# Kod OCR (kz.py) celowo NIE jest zależnością: ponowny OCR zmienia numery `id`, a QC trzyma się kotwic (px, py);
# wymuszenie: rm $(KZSPOTS) && make kz-spots
$(KZSPOTS): $(KZMETA)                      # 09 spots: OCR rzędnych (tesseract, 2 przebiegi) -> kz_spot_ocr.gpkg (ok. 2 min)
	$(UV) 09_kz_digitize.py spots

kz-qc-ui: $(KZSPOTS)                       # ręczna kontrola min(200, liczba punktów): http://localhost:8765/kz -> data/reference/kz_spot_qc.csv
	$(UV) tools/label_server.py --kz

kz-contours: $(KZCONT)
# Kod (kz.py, config kz.*) celowo NIE jest zależnością; po zmianie config: rm $(KZCONT) && make kz-contours (ok. 1 min)
$(KZCONT): $(KZMETA) $(LAKE)                       # 09 contours: poziomice 192,5 i 195,0 m z mapy KŻ + qc_contours.png
	$(UV) 09_kz_digitize.py contours

kz-gravel: $(ZWIR)
$(ZWIR): $(KZMETA) $(LAKE) $(REF)/zwirownia_vertices.csv   # 09 gravel: obrys rejonu eksploatacji kruszywa (wierzchołki ręczne) -> zwirownia.gpkg
	$(UV) 09_kz_digitize.py gravel

test:
	uv run pytest -q

# usuwa tylko model RF (wymusi retrening i przeliczenie dalszych kroków przy następnym make)
clean-model:
	rm -f $(RFMODEL)
