"""Klasyfikacja sceny: Random Forest na pikselach, maska 0/1/255 i wybór komponentu jeziora.

Co robi: dla jednej sceny liczy cechy, stosuje model RF (z progiem t* z bundle), oznacza chmury,
  cienie i brak danych jako 255, a z wody zostawia tylko jezioro (łączność z jego rdzeniem).
Dlaczego tak: chmura i cień nie są lądem, więc nie mogą wejść do maski jako 0 (zaniżyłyby
  poziom wody), a staw obok jeziora nie jest jeziorem. Maska 255 = „nie wiemy".
Wejście → wyjście: pasma + SCL + data + bundle + AOI + rdzeń jeziora → uint8 (H, W) {0, 1, 255},
  próg Otsu sceny i powierzchnia wody w km². Wspólny kod dla skryptu 04 i backendu.
Jak to obronić: reguły chmur to `s2.cloud_mask` (te same stałe co w treningu), próg wody to
  ta sama reguła co `rf.predict_water` (p ≥ t*, zastosowana tu inline w jednym przebiegu), Otsu to
  `otsu.scene_threshold`; pozostałych reguł nie powielamy.
"""
import datetime as dt

import numpy as np
from scipy import ndimage

from mielizna.features import compute_features, indices, stack
from mielizna.otsu import otsu_mask, scene_threshold
from mielizna.s2 import check_radiometry, cloud_mask, scene_quality, valid_mask

NODATA = 255
PIXEL_KM2 = 100e-6          # piksel 10 m x 10 m w km2
CORE_ERODE_PX = 20          # rdzeń jeziora = jezioro zerodowane o 200 m
MIN_COMPONENT_PX = 5
PROBA_SCALE = 254
QC_MIN_CORE_WATER = 0.95    # rdzeń jeziora musi być >= 95% wodą (z pikseli znanych)
QC_MIN_RF_OTSU = 0.90       # RF nie może mieć < 90% powierzchni wody Otsu
QC_MIN_CORE_USABLE = 0.5    # >= 50% rdzenia musi mieć znaną klasę


def lake_core(lake: np.ndarray, px: int = CORE_ERODE_PX) -> np.ndarray:
    """Rdzeń jeziora: maska jeziora zerodowana o `px` pikseli.

    Co robi: erozja binarna (element krzyżowy, `px` iteracji).
    Dlaczego tak: rdzeń leży z dala od brzegu, więc woda tam jest pewna; służy jako „kotwica", z którą
      musi się łączyć woda, żeby uznać ją za jezioro.
    Wejście → wyjście: bool (H, W) → bool (H, W).
    Jak to obronić: 200 m od brzegu to daleko poza strefą mielizn i błędów klasyfikacji brzegu.
    """
    return ndimage.binary_erosion(lake, iterations=px)


def _usable(bands: dict, scl: np.ndarray) -> np.ndarray:
    """Piksele ważne i bez chmur/cieni (te same reguły co przy uczeniu)."""
    return valid_mask(bands, scl) & ~cloud_mask(scl)


def predict_scene_with_proba(bands: dict, scl: np.ndarray, bundle: dict, date,
                             otsu_t: float) -> tuple[np.ndarray, np.ndarray]:
    """Maska wody RF i mapa P(woda) jako uint8 (255 = brak danych w obu).

    Co robi: liczy cechy, bierze piksele ważne, bez chmur i z kompletnymi cechami, przewiduje P(woda)
      i próg t* (ta sama reguła p ≥ t* co `rf.predict_water`, jedno wywołanie modelu);
      reszta dostaje 255. P(woda) jest skalowane do 0-254.
    Dlaczego tak: predykcja tylko na pikselach z pełnymi cechami (RF nie przyjmuje NaN); chmura,
      cień i NaN to „nieznane". Mapa P(woda) potrzebna jest do późniejszego wyznaczenia linii wody.
    Wejście → wyjście: pasma, SCL, bundle, data (date lub 'YYYY-MM-DD'), próg Otsu → (maska, proba).
    Jak to obronić: ten sam próg i te same cechy co w walidacji; test sprawdza chmury, NaN i próg.
    """
    d = date if hasattr(date, "timetuple") else dt.date.fromisoformat(str(date))
    X = stack(compute_features(bands, otsu_t, d))
    ok = _usable(bands, scl) & np.isfinite(X).all(axis=-1)
    mask = np.full(scl.shape, NODATA, np.uint8)
    proba = np.full(scl.shape, NODATA, np.uint8)
    if ok.any():
        p = bundle["model"].predict_proba(X[ok])[:, 1]
        mask[ok] = (p >= bundle.get("water_threshold", 0.5)).astype(np.uint8)   # jak rf.predict_water
        proba[ok] = np.rint(p * PROBA_SCALE).astype(np.uint8)
    return mask, proba


def predict_scene(bands: dict, scl: np.ndarray, bundle: dict, date, otsu_t: float) -> np.ndarray:
    """Maska wody RF: 1 woda, 0 ląd, 255 chmura / cień / brak danych / NaN w cechach.

    Co robi: to samo co `predict_scene_with_proba`, bez mapy prawdopodobieństwa.
    Dlaczego tak: chmura ≠ ląd (patrz moduł).
    Wejście → wyjście: pasma, SCL, bundle, data, próg Otsu → uint8 (H, W).
    Jak to obronić: patrz `predict_scene_with_proba`.
    """
    return predict_scene_with_proba(bands, scl, bundle, date, otsu_t)[0]


def keep_lake_component(mask: np.ndarray, lake_core: np.ndarray, aoi: np.ndarray,
                        min_px: int = MIN_COMPONENT_PX) -> np.ndarray:
    """Zostawia wodę połączoną z rdzeniem jeziora; resztę czyści lub oznacza jako nieznaną.

    Co robi: etykietuje składowe wody (8-sąsiedztwo). Składowa przecinająca rdzeń (powiększony
      o 1 px) zostaje. Pozostałe: < `min_px` pikseli → 0 (szum), ≥ `min_px` → 255 (np. odcięta
      zatoka, której nie umiemy rozstrzygnąć). Poza AOI → 255; 255 na wejściu bez zmian.
    Dlaczego tak: izolowany staw nie jest jeziorem, ale duża odcięta zatoka może nim być, więc
      nie wolno jej cicho zamienić w ląd.
    Wejście → wyjście: maska uint8 {0, 1, 255}, rdzeń bool, AOI bool, min_px → nowa maska uint8.
    Jak to obronić: cztery testy (staw, zatoka, 255/AOI, łączność po przekątnej).
    """
    out = mask.copy()
    labels, n = ndimage.label(mask == 1, structure=np.ones((3, 3), bool))
    if n:
        anchor = ndimage.binary_dilation(lake_core, structure=np.ones((3, 3), bool))
        sizes = np.bincount(labels.ravel(), minlength=n + 1)
        linked = np.zeros(n + 1, bool)
        linked[np.unique(labels[anchor])] = True
        linked[0] = True                      # tło nie jest składową
        small = ~linked & (sizes < min_px)
        unknown = ~linked & ~small
        small[0] = unknown[0] = False
        out[small[labels]] = 0
        out[unknown[labels]] = NODATA
    out[~aoi] = NODATA
    return out


def classify_scene_full(bands: dict, scl: np.ndarray, date, bundle: dict, aoi: np.ndarray,
                        core: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Klasyfikacja sceny z mapą P(woda): (maska RF po filtrze jeziora, proba uint8, próg Otsu).

    Co robi: próg Otsu z `aoi & valid & ~cloud` (`otsu.scene_threshold`), predykcja RF z P(woda),
      filtr komponentów jeziora. Mapa P(woda) nie jest filtrowana (255 tam, gdzie maska przed filtrem).
    Dlaczego tak: skrypt 04 potrzebuje maski i prawdopodobieństwa z jednej predykcji.
    Wejście → wyjście: pasma, SCL, data, bundle, AOI, rdzeń → (uint8, uint8, float).
    Jak to obronić: tylko składa przetestowane części.
    """
    t = scene_threshold(bands, scl, aoi)
    raw, proba = predict_scene_with_proba(bands, scl, bundle, date, t)
    return keep_lake_component(raw, core, aoi), proba, t


def classify_scene(bands: dict, scl: np.ndarray, date, bundle: dict, aoi: np.ndarray,
                   core: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Cała klasyfikacja jednej sceny: (maska RF po filtrze jeziora, próg Otsu, powierzchnia km²).

    Co robi: `classify_scene_full` bez mapy P(woda); powierzchnia = liczba pikseli == 1 × 100 m².
    Dlaczego tak: interfejs dla backendu - jedna funkcja pakietu, wynik identyczny ze skryptem 04.
    Wejście → wyjście: pasma, SCL, data, bundle, AOI, rdzeń → (uint8 (H, W), float, float).
    Uwaga dla backendu (kolejność i pułapki):
      (a) przed klasyfikacją wywołać `s2.check_radiometry(bands, valid_mask(bands, scl) & aoi, date)`;
      (b) wejściem krzywej powierzchnia-rzędna jest powierzchnia OTSU:
          `(otsu_scene_mask(...) == 1).sum() * PIXEL_KM2`, NIGDY powierzchnia RF zwracana tutaj (RF przy
          niskiej wodzie nasyca się na mule, więc h wyszłoby za wysokie, czyli w niebezpiecznym kierunku);
      (c) krzywa jest dopasowana na scenach z lake_nodata_pct <= 1: scena bardziej zachmurzona ma dostać
          area_biased, jak w `levels.variant_c`;
      (d) po wywołaniu trzeba wywołać `scene_qc` (z maską Otsu z `otsu_scene_mask`) i NIE publikować
          powierzchni ani linii brzegowej, gdy `qc_ok` jest False.
    Jak to obronić: patrz `classify_scene_full`.
    """
    mask, _, t = classify_scene_full(bands, scl, date, bundle, aoi, core)
    return mask, t, float((mask == 1).sum() * PIXEL_KM2)


def otsu_scene_mask(bands: dict, scl: np.ndarray, aoi: np.ndarray, core: np.ndarray,
                    otsu_t: float) -> np.ndarray:
    """Maska wody metodą Otsu, po tych samych regułach co RF (chmury → 255, filtr jeziora).

    Co robi: `otsu_mask` na MNDWI, chmury/cienie/brak danych → 255, `keep_lake_component`.
    Dlaczego tak: porównanie RF z Otsu ma sens tylko przy identycznym traktowaniu chmur i stawów.
    Wejście → wyjście: pasma, SCL, AOI, rdzeń, próg Otsu → uint8 (H, W) {0, 1, 255}.
    Jak to obronić: jedyna różnica względem RF to reguła piksela (MNDWI > próg).
    """
    m = otsu_mask(indices(bands)["mndwi"], otsu_t)
    m[~_usable(bands, scl)] = NODATA
    return keep_lake_component(m, core, aoi)


def scene_qc(mask: np.ndarray, mask_otsu: np.ndarray, core: np.ndarray) -> dict:
    """Kontrola jakości sceny bez etykiet: rdzeń jeziora i zgodność RF z Otsu.

    Co robi: liczy core_usable_frac (piksele rdzenia != 255 / rdzeń), core_water_frac (woda w rdzeniu
      / znane piksele rdzenia), rf_otsu_ratio (woda RF / woda Otsu; NaN gdy Otsu ma 0) oraz
      qc_ok = usable >= 0,5 & water >= 0,95 & ratio >= 0,90 (NaN nie przechodzi). qc_reason to
      przyczyny oddzielone ';' (`core_nodata`, `core_water<0.95`, `rf/otsu<0.90`, `rf/otsu=nan`),
      pusty gdy qc_ok.
    Dlaczego tak: rdzeń (jezioro zerodowane o 200 m) jest zawsze wodą, więc ląd w rdzeniu to błąd
      klasyfikacji (chmura, rozbłysk, uszkodzony produkt), a RF dużo poniżej Otsu to niewykryta woda.
      Brak górnej granicy ilorazu, bo RF > Otsu jest poprawne przy niskim stanie wody (2018-10,
      2021-10); brak reguły na otsu_t < 0 (7 z 10 takich scen jest dobrych); brak zastępowania RF
      przez Otsu - scena z qc_ok False jest wykluczana, nie naprawiana.
    Wejście → wyjście: maska RF i maska Otsu (uint8 {0, 1, 255}, po filtrze jeziora), rdzeń bool
      → słownik z 5 polami wyżej.
    Jak to obronić: progi są stałymi `QC_*` ustalonymi bez użycia etykiet; liczbę oflagowanych
      scen raportuje 04 (zob. R21/R22), a każdą z nich da się obejrzeć na obrazku qc/flagged/.
    """
    n_core = int(core.sum())
    known = core & (mask != NODATA)
    usable = known.sum() / n_core if n_core else 0.0
    water = (core & (mask == 1)).sum() / known.sum() if known.any() else 0.0
    n_otsu = int((mask_otsu == 1).sum())
    ratio = float((mask == 1).sum() / n_otsu) if n_otsu else float("nan")
    reasons = []
    if usable < QC_MIN_CORE_USABLE:
        reasons.append("core_nodata")
    if water < QC_MIN_CORE_WATER:
        reasons.append("core_water<0.95")
    if np.isnan(ratio):
        reasons.append("rf/otsu=nan")
    elif ratio < QC_MIN_RF_OTSU:
        reasons.append("rf/otsu<0.90")
    return {"core_usable_frac": float(usable), "core_water_frac": float(water),
            "rf_otsu_ratio": ratio, "qc_ok": not reasons, "qc_reason": ";".join(reasons)}


def analyze_scene(bands: dict, scl: np.ndarray, date, bundle: dict, aoi: np.ndarray,
                  lake: np.ndarray, core: np.ndarray) -> dict:
    """Pełna analiza jednej sceny: maski RF i Otsu, mapa P(woda), powierzchnie i QC.

    Co robi: `check_radiometry` (ValueError przy uszkodzonej scenie przechodzi dalej), potem
      `classify_scene_full`, `otsu_scene_mask`, `scene_quality` i `scene_qc`. Zwraca słownik:
      `mask`, `mask_otsu`, `proba` (uint8 H×W), `otsu_threshold`, `area_km2` (RF), `area_otsu_km2`,
      `lake_nodata_pct` (% jeziora z maską 255), `local_cloud_pct` oraz 5 kluczy `scene_qc`.
    Dlaczego tak: skrypt 04 i backend muszą liczyć scenę identycznie; jedna funkcja wyklucza rozjazd.
      Do krzywej powierzchnia-rzędna idzie `area_otsu_km2`, nie `area_km2` (zob. `classify_scene`).
    Wejście → wyjście: pasma, SCL, data, bundle, AOI, jezioro, rdzeń jeziora → słownik wyżej.
    Jak to obronić: tylko składa przetestowane części, a test porównuje wynik z ich osobnym wywołaniem;
      na prawdziwych scenach wynik jest identyczny z plikami zapisanymi przez 04.
    """
    check_radiometry(bands, valid_mask(bands, scl) & aoi, str(date))
    mask, proba, t = classify_scene_full(bands, scl, date, bundle, aoi, core)
    m_otsu = otsu_scene_mask(bands, scl, aoi, core, t)
    q = scene_quality(date, scl, valid_mask(bands, scl), aoi, lake)
    return {"mask": mask, "mask_otsu": m_otsu, "proba": proba, "otsu_threshold": t,
            "area_km2": (mask == 1).sum() * PIXEL_KM2,
            "area_otsu_km2": (m_otsu == 1).sum() * PIXEL_KM2,
            "lake_nodata_pct": 100 * float(((mask == 255) & lake).sum() / lake.sum()),
            "local_cloud_pct": q["local_cloud_pct"], **scene_qc(mask, m_otsu, core)}
