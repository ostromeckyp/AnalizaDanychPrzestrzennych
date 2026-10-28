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
SCENES  := $(PROC)/scenes.json
BOTTOM  := $(PROC)/model/all/model_meta.json
MIN_HUMAN_LABELS := 150

.PHONY: help all osm nmt s2 labels label-candidates label-ui check-labels rf classify shorelines \
        bulletins lidar-epochs levels bottom test clean-model
.DEFAULT_GOAL := help

help:
	@echo "Cele: osm nmt s2 label-candidates label-ui rf classify shorelines bulletins levels bottom all test clean-model"
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

levels: $(SCENES)
$(SCENES): $(SHORES) $(BULLS)              # 06: poziom wody h_t każdej sceny, krzywa powierzchnia-rzędna
	$(UV) 06_water_levels.py

bottom: $(BOTTOM)
$(BOTTOM): $(SCENES)                       # 07: model dna (okresy all, pre_flood, post_flood)
	$(UV) 07_bottom_model.py

test:
	uv run pytest -q

# usuwa tylko model RF (wymusi retrening i przeliczenie dalszych kroków przy następnym make)
clean-model:
	rm -f $(RFMODEL)
