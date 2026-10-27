"""Klasyfikator wody Random Forest: tabela uczenia, walidacja z grupami, miary i model.

Co robi: z etykiet punktowych (woda/ląd) buduje tabelę cech piksela, ocenia Random Forest (RF)
  walidacją krzyżową z grupami i porównuje go z trzema punktami odniesienia (próg Otsu, SCL == 6,
  „wszystko woda"), po czym trenuje model końcowy i zapisuje go razem z opisem (bundle).
Dlaczego tak: celem jest dobry brzeg jeziora, a nie łatwe środki zbiornika, więc oceniamy głównie
  na punktach ręcznych (`human`), i to na wynikach „poza próbą" (OOF), z podziałem po grupach.
Wejście → wyjście: etykiety (labels.gpkg) + sceny COG → `build_table` → `grouped_cv` (miary, CI,
  McNemar) → `train_final` → `save_model` (rf_model.joblib) i `render_report` (tabele A–E).
Jak to obronić: patrz słowniczek poniżej; wszystkie hiperparametry są zamrożone z góry, więc żadna
  liczba w raporcie nie jest wynikiem strojenia na zbiorze testowym.

Słowniczek (to jest rdzeń obrony ustnej)
- Random Forest: 100 drzew decyzyjnych uczonych na losowych podpróbach wierszy, z cechami losowanymi
  przy każdym podziale (`max_features='sqrt'`); klasa to głosowanie drzew. Zaleta: radzi sobie z nieliniowością i skorelowanymi pasmami, nie wymaga
  skalowania cech. `class_weight="balanced"` waży rzadszą klasę (ląd) tak, by nie była ignorowana,
  a `min_samples_leaf=2` zabrania liścia z jednym punktem (mniej zapamiętywania szumu).
- Próg decyzyjny wody t*: RF zwraca P(woda); domyślnie woda gdy P ≥ 0,5. Produkt używa progu
  JEDNOSTRONNEGO t* ∈ {0,50; 0,55; …; 0,90} (nigdy poniżej 0,5), wybieranego zagnieżdżoną
  walidacją krzyżową (patrz `_choose_threshold_from_curve`; krzywa BA(t) uśredniona z 10 powtórzeń OOF, R22). Wynik główny M2 zostaje przy t = 0,5.
- Przeciek przestrzenny: sąsiednie piksele i piksele tej samej sceny są niemal identyczne. Losowy
  podział wierszy wrzuciłby „bliźniaki" do uczenia i do testu, a model wyglądałby na świetny,
  bo rozpoznaje znane miejsca, a nie uczy się wody. Dlatego walidujemy po GRUPACH: całe bloki
  500 m (`by_block`, główny wynik — test na miejscach, których model nie widział) albo całe
  sceny (`by_scene` — test na dniach, których model nie widział).
- Dokładność zrównoważona (balanced accuracy, BA): średnia z czułości dla wody i dla lądu,
  (recall_water + recall_land) / 2. Gdy punktów wody jest wielokrotnie więcej niż lądu, zwykła
  dokładność (OA) premiuje ignorowanie lądu: „wszystko woda" ma wysokie OA, ale BA tylko 0,50. BA = 0,50 to
  poziom losowy niezależnie od proporcji klas.
- Kappa Cohena (κ): zgodność ponad zgodność przypadkową; 0 = tyle co losowo, 1 = idealnie.
- Test McNemara: porównuje dwie metody na TYCH SAMYCH punktach, patrząc wyłącznie na punkty,
  na których się różnią: b = RF dobrze a druga źle, c = odwrotnie. Porównuje LICZBY BŁĘDÓW
  (czyli zwykłą dokładność), więc dominuje w nim klasa większościowa (woda); to NIE jest test
  różnicy BA. Dlatego b i c podajemy dodatkowo osobno dla punktów wody i lądu. Gdyby metody były
  równie dobre, b i c byłyby po połowie; p to dokładne prawdopodobieństwo (dwumianowe) tak
  skrajnego podziału.
- Przedziały ufności 95%: Wilson dla proporcji (OA, recall); bootstrap warstwowy (2000 losowań
  w obrębie klasy) dla BA, κ i F1_land. Bootstrap po wierszach jest optymistyczny, bo punkty
  leżą w skupiskach (mało bloków), więc prawdziwa niepewność jest nieco większa.
"""
import hashlib
import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
import sklearn
from scipy.stats import binomtest
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import StratifiedGroupKFold

from mielizna import labels as L
from mielizna.features import FEATURES, compute_features
from mielizna.otsu import scene_threshold
from mielizna.s2 import BANDS, cloud_mask, cloud_mask_description, valid_mask

log = logging.getLogger(__name__)
SEED = 42
BLOCK_M = 500
HEADLINE_STRATUM = "shore"
N_BOOT = 2000
THRESHOLD_REPEATS = 10      # R22: liczba powtórzeń OOF (ziarna SEED..SEED+9) uśrednianych w krzywej BA(t)
THRESHOLD_GRID = tuple(float(t) for t in np.round(np.arange(0.50, 0.9001, 0.05), 2))
METHODS = ("rf", "rf_t", "otsu", "scl", "all_water", "rf_auto")
TABLE_ORDER = ("all_water", "otsu", "scl", "rf", "rf_auto")   # kolejność wierszy w raporcie
TABLE_ORDER_T = ("all_water", "otsu", "scl", "rf", "rf_t", "rf_auto")   # tabele A i C (z „RF t*")
TABLE_COLUMNS = FEATURES + ["y", "date", "block", "otsu_pred", "scl_pred", "source", "stratum",
                            "id", "otsu_t"]
METHOD_NAMES = {"all_water": "all-water", "otsu": "Otsu", "scl": "SCL==6", "rf": "RF",
                "rf_auto": "RF auto-only", "rf_t": "RF t*"}


# --- tabela uczenia ---------------------------------------------------------------------

def build_table(labels: gpd.GeoDataFrame, scenes_dir: Path, dates: list[str],
                aoi: np.ndarray) -> pd.DataFrame:
    """Tabela uczenia: jeden wiersz = jeden etykietowany piksel w jednej scenie.

    Co robi: bierze etykiety klasowe (ręczne water/land wg R15 oraz automatyczne water/land),
      dla każdej sceny liczy cechy (`compute_features` z progiem Otsu tej sceny) i odczytuje je
      w punktach. Dodaje etykietę `y` (1 woda, 0 ląd), predykcje punktów odniesienia (`otsu_pred`,
      `scl_pred`), identyfikator bloku 500 m i warstwę (`stratum`).
    Dlaczego tak: cecha `mndwi_minus_otsu` wymaga progu liczonego tak samo w treningu i przy
      predykcji, więc używamy wspólnego `otsu.scene_threshold`. Punkty `skip`/bez etykiety to
      niepewność, nie klasa. Punkt pod chmurą lub bez danych nie ma wiarygodnych cech, a wiersz
      z NaN w cechach RF nie przyjmuje. Daty spoza `dates` (scena wykluczona później) odpadają,
      a lista `dates` pochodzi z `s2.usable_dates`, nie z globowania katalogu.
    Wejście → wyjście: GeoDataFrame etykiet, katalog COG, lista dat użytecznych, maska AOI →
      DataFrame o kolumnach `FEATURES + y, date, block, otsu_pred, scl_pred, source, stratum, id,
      otsu_t`; w `df.attrs["dropped"]` liczby odrzuconych wierszy (unlabelled_or_skip, not_usable,
      not_ok, nan). Brak pliku dla daty z `dates` rzuca błąd (cicho pominięta scena zmieniłaby wyniki).
    Jak to obronić: `scl_pred` to ta sama klasa „woda" (SCL 6), której używa ESA; `otsu_pred` to
      dokładnie `otsu_mask`; blok `(x // 500, y // 500)` jest podstawą podziału bez przecieku.
    """
    is_class = labels["label"].isin(L.CLASS_LABELS)
    keep = (L.human_class_labels(labels).index.union(labels.index[(labels["source"] == "auto") & is_class]))
    n_unlab = int(len(labels) - len(keep))
    lab = labels.loc[keep]
    usable = lab["date"].isin(dates)
    n_unusable = int((~usable).sum())
    if n_unusable:
        log.warning("Pominięto %d etykiet ze scen spoza listy użytecznych: %s", n_unusable,
                    sorted(set(lab.loc[~usable, "date"])))
    lab = lab[usable]
    parts, n_not_ok = [], 0
    for date, g in lab.groupby("date"):
        bands, scl = L.load_scene(date, scenes_dir)
        t = scene_threshold(bands, scl, aoi)
        feats = compute_features(bands, t, pd.Timestamp(date).date())
        ok = valid_mask(bands, scl) & ~cloud_mask(scl)
        r, c = g["row"].to_numpy(), g["col"].to_numpy()
        good = ok[r, c]
        n_not_ok += int((~good).sum())
        g, r, c = g[good], r[good], c[good]
        t_df = pd.DataFrame({k: feats[k][r, c] for k in FEATURES}, index=g.index)
        t_df["y"] = (g["label"] == "water").astype(int).to_numpy()
        t_df["date"] = str(date)
        t_df["block"] = [f"{int(x // BLOCK_M)}_{int(y // BLOCK_M)}" for x, y in zip(g["x"], g["y"])]
        t_df["otsu_pred"] = (t_df["mndwi"] > t).astype(int)
        t_df["scl_pred"] = (scl[r, c] == 6).astype(int)
        t_df["source"] = g["source"].to_numpy()
        t_df["stratum"] = g["stratum"].to_numpy()
        t_df["id"] = g["id"].to_numpy()
        t_df["otsu_t"] = float(t)
        parts.append(t_df)
    if n_not_ok:
        log.warning("Pominięto %d etykiet pod chmurą lub bez danych", n_not_ok)
    df = pd.concat(parts, ignore_index=True)[TABLE_COLUMNS] if parts else pd.DataFrame(columns=TABLE_COLUMNS)
    nan = df[FEATURES].isna().any(axis=1)
    if nan.any():
        log.warning("Odrzucono %d wierszy z NaN w cechach", int(nan.sum()))
    df = df[~nan].reset_index(drop=True)
    df.attrs["dropped"] = {"unlabelled_or_skip": n_unlab, "not_usable": n_unusable,
                           "not_ok": n_not_ok, "nan": int(nan.sum())}
    return df


def table_counts(df: pd.DataFrame) -> dict:
    """Liczby do nagłówka raportu: wiersze źródło × klasa, bloki i sceny `human`, odrzucone.

    Co robi: zlicza wiersze tabeli wg źródła i klasy oraz bloki i sceny punktów `human` (też tylko lądu).
    Dlaczego tak: czytelnik raportu musi wiedzieć, na ilu i jak skupionych punktach stoi wynik.
    Wejście → wyjście: tabela z `build_table` (z `attrs["dropped"]`) → słownik liczb.
    Jak to obronić: to czyste zliczenia z tej samej tabeli, na której liczono miary.
    """
    h = df[df.source == "human"]
    hl = h[h.y == 0]
    by = {s: {"water": int(((df.source == s) & (df.y == 1)).sum()),
              "land": int(((df.source == s) & (df.y == 0)).sum())} for s in sorted(df.source.unique())}
    return {"rows_by_source_class": by, "human_blocks": int(h.block.nunique()),
            "human_scenes": int(h.date.nunique()), "human_land_blocks": int(hl.block.nunique()),
            "human_land_scenes": int(hl.date.nunique()), "n_rows": int(len(df)),
            "dropped": dict(df.attrs.get("dropped", {}))}


# --- miary ------------------------------------------------------------------------------

def _div(a: float, b: float) -> float:
    return a / b if b else float("nan")


def _from_confusion(tn: float, fp: float, fn: float, tp: float) -> dict:
    """Miary z macierzy pomyłek (klasa dodatnia = woda; „land" jest odczytywana symetrycznie)."""
    n = tn + fp + fn + tp
    recall_land, recall_water = _div(tn, tn + fp), _div(tp, fn + tp)
    pe = _div((tn + fp) * (tn + fn) + (fn + tp) * (fp + tp), n * n)
    po = _div(tn + tp, n)
    kappa = 0.0 if pe == 1 else _div(po - pe, 1 - pe)
    f1w = _div(2 * tp, 2 * tp + fp + fn)
    f1l = _div(2 * tn, 2 * tn + fn + fp)
    return {"oa": po, "bacc": (recall_land + recall_water) / 2, "kappa": kappa,
            "recall_water": recall_water, "recall_land": recall_land,
            "f1_water": f1w, "f1_land": f1l}


def metrics_from_labels(y: np.ndarray, p: np.ndarray) -> dict:
    """OA, BA, κ, recall_water, recall_land, F1_water, F1_land i macierz [[tn, fp], [fn, tp]].

    Co robi: liczy miary jakości klasyfikacji binarnej z wektorów prawdy `y` i predykcji `p`.
    Dlaczego tak: pozwala jedną funkcją ocenić RF, Otsu, SCL i „wszystko woda" na tych samych punktach.
    Wejście → wyjście: dwa wektory 0/1 (1 = woda) → słownik; macierz w kolejności etykiet [0, 1].
    Jak to obronić: wartości zgadzają się z `sklearn.metrics` (test), a F1_land to F1 dla klasy „ląd".
    """
    y, p = np.asarray(y).astype(int), np.asarray(p).astype(int)
    tn, fp = int(((y == 0) & (p == 0)).sum()), int(((y == 0) & (p == 1)).sum())
    fn, tp = int(((y == 1) & (p == 0)).sum()), int(((y == 1) & (p == 1)).sum())
    m = _from_confusion(tn, fp, fn, tp)
    m.update(n=int(len(y)), n_land=tn + fp, n_water=fn + tp, confusion=[[tn, fp], [fn, tp]])
    return m


def wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Przedział ufności Wilsona 95% dla proporcji k/n.

    Co robi: daje zakres, w którym z 95% pewnością leży prawdziwa proporcja (np. czułość dla lądu).
    Dlaczego tak: dla małych n (kilkadziesiąt punktów lądu) zwykły przedział „p ± 1,96·SE" wychodzi poza [0, 1]
      i jest zbyt wąski przy p bliskim 0 lub 1; Wilson tego nie robi.
    Wejście → wyjście: liczba sukcesów k, liczba prób n → (dolna, górna); n = 0 → (NaN, NaN).
    Jak to obronić: wzór podręcznikowy; np. 13/21 daje [0,409; 0,792] (sprawdzone ręcznie w teście).
    """
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return float(centre - half), float(centre + half)


def mcnemar_exact(correct_a: np.ndarray, correct_b: np.ndarray) -> dict:
    """Dokładny test McNemara: czy metoda A i B różnią się liczbą błędów na tych samych punktach.

    Co robi: liczy b (A dobrze, B źle) i c (A źle, B dobrze) i dwustronne p z rozkładu
      dwumianowego Bin(b + c, 0,5).
    Dlaczego tak: punkty, na których obie metody zgadzają się (obie dobrze lub obie źle), nic nie
      mówią o różnicy; liczą się tylko rozbieżne. Wersja dokładna (a nie χ²) jest poprawna także
      dla małych b + c, co jest naszym przypadkiem. Test porównuje liczby błędów, czyli zwykłą
      dokładność (OA), w której dominuje klasa większościowa (woda); NIE testuje różnicy BA.
      Dlatego `mcnemar_by_class` rozkłada b i c osobno na punkty wody i lądu.
    Wejście → wyjście: dwa wektory bool „czy trafiła" → {"b", "c", "p"}; b + c = 0 → p = 1.
    Jak to obronić: test sparowany jest właściwy, bo obie metody oceniamy na identycznych punktach;
      hipoteza zerowa: P(b) = P(c).
    """
    a, b_ = np.asarray(correct_a, bool), np.asarray(correct_b, bool)
    b, c = int((a & ~b_).sum()), int((~a & b_).sum())
    p = 1.0 if b + c == 0 else float(binomtest(min(b, c), b + c, 0.5).pvalue)
    return {"b": b, "c": c, "p": p}


def mcnemar_by_class(y: np.ndarray, correct_a: np.ndarray, correct_b: np.ndarray) -> dict:
    """b i c z McNemara osobno dla punktów wody (y = 1) i lądu (y = 0); bez p-wartości.

    Co robi: dzieli rozbieżne pary na te z prawdziwą klasą woda i ląd.
    Dlaczego tak: łączne b, c jest zdominowane przez wodę; ten rozkład pokazuje, na której klasie
      metoda A wygrywa lub przegrywa z B (np. RF zyskuje na lądzie kosztem wody).
    Wejście → wyjście: prawda `y` i dwa wektory bool „czy trafiła" → {"water": {b, c}, "land": {b, c}}.
    Jak to obronić: sumy po obu klasach dają dokładnie b i c z `mcnemar_exact`.
    """
    y = np.asarray(y).astype(int)
    a, b_ = np.asarray(correct_a, bool), np.asarray(correct_b, bool)
    out = {}
    for name, m in (("water", y == 1), ("land", y == 0)):
        out[name] = {"b": int((a & ~b_ & m).sum()), "c": int((~a & b_ & m).sum())}
    return out


def _bootstrap_ci(y: np.ndarray, p: np.ndarray, seed: int = SEED, n_boot: int = N_BOOT) -> dict:
    """Warstwowy bootstrap (losowanie ze zwracaniem w obrębie klasy) dla BA, κ, F1_land."""
    y, p = np.asarray(y).astype(int), np.asarray(p).astype(int)
    c0, c1 = (p[y == 0] == 0), (p[y == 1] == 1)
    out = {k: [float("nan")] * 2 for k in ("bacc", "kappa", "f1_land")}
    if len(c0) == 0 or len(c1) == 0:
        return out
    rng = np.random.default_rng(seed)
    tn = c0[rng.integers(0, len(c0), (n_boot, len(c0)))].sum(1)
    tp = c1[rng.integers(0, len(c1), (n_boot, len(c1)))].sum(1)
    fp, fn = len(c0) - tn, len(c1) - tp
    for k in out:
        vals = np.array([_from_confusion(a, b, c, d)[k] for a, b, c, d in zip(tn, fp, fn, tp)])
        out[k] = [float(v) for v in np.nanpercentile(vals, [2.5, 97.5])]
    return out


def _with_ci(y: np.ndarray, p: np.ndarray) -> dict:
    m = metrics_from_labels(y, p)
    (tn, _), (_, tp) = m["confusion"]
    ci = {"oa": wilson_ci(int(tn + tp), m["n"]), "recall_land": wilson_ci(int(tn), m["n_land"]),
          "recall_water": wilson_ci(int(tp), m["n_water"])}
    ci.update(_bootstrap_ci(y, p))
    m["ci"] = {k: [float(a) for a in v] for k, v in ci.items()}
    return m


def _evaluate(y: np.ndarray, preds: dict[str, np.ndarray], ci: bool) -> dict:
    """Miary każdej metody na jednym podzbiorze (+ CI i McNemar dla RF, gdy `ci`)."""
    fn = _with_ci if ci else metrics_from_labels
    out = {k: fn(y, preds[k]) for k in METHODS}
    if ci:
        right = {k: preds[k] == y for k in ("rf", "otsu", "scl")}
        out["mcnemar"] = {}
        for k, o in (("vs_otsu", "otsu"), ("vs_scl", "scl")):
            out["mcnemar"][k] = mcnemar_exact(right["rf"], right[o])
            out["mcnemar"][k]["by_class"] = mcnemar_by_class(y, right["rf"], right[o])
    return out


# --- model i walidacja ------------------------------------------------------------------

def make_model(seed: int = SEED) -> RandomForestClassifier:
    """Random Forest o zamrożonych hiperparametrach (100 drzew, min_samples_leaf=2, balanced).

    Co robi: zwraca nieuczony klasyfikator.
    Dlaczego tak: nie strojimy parametrów, bo każda liczba, którą mamy, jest liczbą testową;
      strojenie na niej zawyżyłoby wynik. `balanced` kompensuje mniej licznych punktów lądu.
      `min_samples_leaf=2` to świadomy wybór, a nie domyślne 1 z sklearn: liść z jednym punktem
      zapamiętuje pojedynczą (być może błędną) etykietę, a liście o ≥ 2 punktach dają gładsze
      prawdopodobieństwa i mniejsze przeuczenie na szumie etykiet.
    Wejście → wyjście: seed → RandomForestClassifier.
    Jak to obronić: wartości (100 drzew, liść ≥ 2, seed 42) ustalono przed obejrzeniem wyników i
      nigdy ich nie zmieniano pod wynik.
    """
    return RandomForestClassifier(n_estimators=100, min_samples_leaf=2, class_weight="balanced",
                                  n_jobs=-1, random_state=seed)


def _oof_proba(df: pd.DataFrame, n_splits: int = 5, seed: int = SEED) -> np.ndarray:
    """P(woda) poza próbą dla każdego wiersza: StratifiedGroupKFold po blokach, te same warstwy.

    Co robi: dzieli wiersze `df` na `n_splits` foldów po `block` (warstwy klasa × źródło,
      shuffle, ziarno `seed`), w każdym uczy `make_model()` na reszcie i zapisuje P(woda) dla foldu.
    Dlaczego tak: próg wolno wybierać tylko z prawdopodobieństw, których model nie widział w
      uczeniu; w przeciwnym razie RF (prawie zapamiętuje dane) dałby P bliskie 0/1 i próg byłby bez sensu.
    Wejście → wyjście: tabela (z kolumnami y, source, block) → wektor P(woda) w kolejności wierszy.
    Jak to obronić: ten sam podział i ten sam model co w głównej walidacji, tylko na mniejszym zbiorze.
    """
    d = df.reset_index(drop=True)
    strata = d["y"].to_numpy() * 2 + (d["source"] == "human").to_numpy()
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    X, y = d[FEATURES].to_numpy(), d["y"].to_numpy()
    proba = np.zeros(len(d))
    for tr, te in cv.split(d, strata, d["block"]):
        proba[te] = make_model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    return proba


def _ba_curve(proba: np.ndarray, y: np.ndarray, is_human: np.ndarray,
              grid: tuple = THRESHOLD_GRID) -> np.ndarray:
    """Krzywa BA(t) na punktach `human` dla progów z siatki (woda iff P >= t); NaN gdy brak klasy.

    Co robi: dla każdego t z siatki liczy dokładność zrównoważoną (średnia z recall lądu i wody) na
      wierszach `human`. Gdy wśród nich nie ma lądu albo wody, zwraca same NaN (BA nieokreślone).
    Dlaczego tak: krzywa (a nie sam argmax) jest tym, co wolno uśredniać po powtórzeniach OOF (R22).
    Wejście → wyjście: P(woda), prawda 0/1, maska human → wektor długości `len(grid)`.
    Jak to obronić: ta sama definicja BA co w tabelach A i C, tylko liczona dla wielu progów naraz.
    """
    proba, y = np.asarray(proba), np.asarray(y)
    ph, yh = proba[is_human], y[is_human]
    if not ((yh == 0).any() and (yh == 1).any()):
        return np.full(len(grid), np.nan)
    out = np.empty(len(grid))
    for i, t in enumerate(grid):
        pred = (ph >= t).astype(int)
        out[i] = ((pred[yh == 0] == 0).mean() + (pred[yh == 1] == 1).mean()) / 2
    return out


def _choose_threshold_from_curve(curve: np.ndarray, grid: tuple = THRESHOLD_GRID) -> float:
    """Argmax krzywej BA(t); remis (<= 1e-12) → NAJMNIEJSZE t; krzywa NaN (brak klasy) → 0,5.

    Co robi: zwraca t z siatki o największym BA; kolejne t wygrywa tylko przewagą > 1e-12.
    Dlaczego tak: remis → najmniejsze t, żeby bez dowodu nie odchodzić od 0,5; brak lądu lub wody
      wśród punktów `human` → 0,5, czyli bez zmiany względem domyślnego.
    Wejście → wyjście: wektor BA(t) (zwykle średnia z powtórzeń) → jeden float z siatki.
    Jak to obronić: reguła z R18, bez zmian; R22 zmienia tylko to, co jest argmaksowane.
    """
    curve = np.asarray(curve, float)
    if np.isnan(curve).any():
        return 0.5
    best_t, best_ba = grid[0], -1.0
    for t, ba in zip(grid, curve):
        if ba > best_ba + 1e-12:
            best_t, best_ba = t, ba
    return float(best_t)


def _choose_threshold(proba: np.ndarray, y: np.ndarray, is_human: np.ndarray,
                      grid: tuple = THRESHOLD_GRID) -> float:
    """Próg t* ∈ siatce maksymalizujący BA na punktach `human` dla JEDNEGO wektora P (woda iff P ≥ t).

    Co robi: `_choose_threshold_from_curve(_ba_curve(...))`. Produkt używa wersji uśrednionej po
      powtórzeniach (`_mean_threshold_curve`, R22); ta funkcja zostaje jako definicja reguły dla
      jednego OOF i do testów.
    Dlaczego tak: (1) Jednostronnie (t ≥ 0,5), bo błąd „ląd uznany za wodę" jest groźny: mielizna
      wygląda na wodę, obniża się z_max = min h po obserwacjach wody i płytkie miejsca wychodzą
      jako bezpieczne; wyższy próg to błędy w stronę ostrożniejszych stref. (2) BA na `human`,
      bo to trudny brzeg, a punkty `auto` są łatwe z konstrukcji. (3) Remis → najmniejsze t.
    Wejście → wyjście: P(woda) OOF, prawda 0/1, maska human → jeden float z siatki.
    Jak to obronić: siatka (9 wartości) i kryterium są ustalone z góry (R18); krzywa BA jest płaska
      (w obrębie 0,01) na 0,60–0,80, więc pojedynczy argmax jest niestabilny — stąd R22.
    """
    return _choose_threshold_from_curve(_ba_curve(proba, y, is_human, grid), grid)


def _mean_threshold_curve(sub: pd.DataFrame) -> np.ndarray:
    """Średnia krzywa BA(t) z THRESHOLD_REPEATS powtórzeń OOF (ziarna SEED..SEED+9) na punktach `human`.

    Co robi: dla k = 0..9 liczy `_oof_proba(sub, seed=SEED + k)`, z niego `_ba_curve`, i uśrednia.
    Dlaczego tak: zob. `_nested_threshold`; używane identycznie w walidacji zagnieżdżonej i w t* końcowym.
    Wejście → wyjście: tabela (podzbiór) → wektor długości `len(THRESHOLD_GRID)` (NaN gdy brak klasy).
    Jak to obronić: 10 powtórzeń to stała z góry (R22), nie wynik strojenia.
    """
    y, hm = sub["y"].to_numpy(), _human_mask(sub)
    curves = [_ba_curve(_oof_proba(sub, seed=SEED + k), y, hm) for k in range(THRESHOLD_REPEATS)]
    return np.mean(curves, axis=0)


def _human_mask(d: pd.DataFrame) -> np.ndarray:
    strat = d["stratum"].to_numpy() if "stratum" in d else np.full(len(d), HEADLINE_STRATUM)
    return ((d["source"] == "human").to_numpy()) & np.isin(strat, L.HUMAN_STRATA)


def _nested_threshold(df: pd.DataFrame, train_idx: np.ndarray) -> tuple[float, np.ndarray]:
    """t* i średnia krzywa BA dla jednego foldu zewnętrznego, wybrane WYŁĄCZNIE na jego wierszach uczących.

    Co robi: bierze `df.iloc[train_idx]`, uśrednia krzywą BA(t) z 10 powtórzeń wewnętrznego OOF
      (`_mean_threshold_curve`) i wybiera argmax (remis → najmniejsze t; brak lądu human → 0,5).
    Dlaczego tak: wiersze testowe foldu zewnętrznego nie biorą udziału w wyborze progu, więc ocena
      na nich jest uczciwa. Uśrednianie, bo pojedynczy OOF jest zbyt zaszumiony: krzywa BA jest płaska
      (w obrębie 0,01) na 0,60–0,80, a argmax z jednego ziarna wahał się od 0,60 do 0,85 na TYCH
      SAMYCH danych. Nie wybieramy „ostrożnego" końca plateau (największe t), bo powyżej 0,75 całe
      sceny zapadają się w ląd (2020-11-06 przy 0,80: core_water 0,40).
    Wejście → wyjście: tabela i pozycje wierszy uczących → (float, krzywa BA).
    Jak to obronić: test sprawdza, że 10 powtórzeń (ziarna 42..51) widzi tylko indeksy uczące.
    """
    curve = _mean_threshold_curve(df.iloc[train_idx])
    return _choose_threshold_from_curve(curve), curve


def final_threshold(df: pd.DataFrame) -> tuple[float, np.ndarray]:
    """t* modelu końcowego i jego średnia krzywa BA: ta sama reguła na OOF z całej tabeli.

    Co robi: `_mean_threshold_curve` na wszystkich wierszach (10 powtórzeń 5-krotnego OOF po
      blokach) + argmax z tym samym rozstrzyganiem remisów.
    Dlaczego tak: model końcowy widzi wszystkie etykiety, więc próg musi pochodzić z predykcji poza
      próbą. Uśrednianie z tego samego powodu co w walidacji (plateau 0,60–0,80 w obrębie 0,01,
      argmax pojedynczego ziarna 0,60–0,85); nie bierzemy największego t z plateau, bo powyżej 0,75
      sceny zapadają się w ląd (2020-11-06 przy 0,80: core_water 0,40).
    Wejście → wyjście: tabela z `build_table` → (float do `bundle["water_threshold"]`, krzywa BA).
    Jak to obronić: identyczna reguła jak w walidacji zagnieżdżonej, tylko bez zewnętrznego testu.
    """
    curve = _mean_threshold_curve(df)
    return _choose_threshold_from_curve(curve), curve


def predict_water(bundle: dict, X) -> np.ndarray:
    """Maska wody (bool) z progiem modelu: P(woda) ≥ bundle["water_threshold"] (domyślnie 0,5).

    Co robi: `predict_proba` modelu z bundle i porównanie z zapisanym progiem t*.
    Dlaczego tak: produkt ma stosować ten sam jednostronny próg, który wybrała walidacja; `predict`
      ucięłoby na 0,5.
    Wejście → wyjście: bundle z `load_model`, macierz cech (n × len(FEATURES)) → bool[n].
    Jak to obronić: bez progu w bundle wynik jest identyczny z `predict` (0,5).
    """
    X = X.to_numpy() if hasattr(X, "to_numpy") else np.asarray(X)
    return bundle["model"].predict_proba(X)[:, 1] >= bundle.get("water_threshold", 0.5)


def _fit_predict(df: pd.DataFrame, tr: np.ndarray, te: np.ndarray, auto_only: bool) -> np.ndarray:
    """P(woda) dla wierszy `te` z modelu uczonego na `tr` (z `auto_only`: tylko wiersze auto)."""
    train = df.iloc[tr]
    if auto_only:
        train = train[train.source == "auto"]
    m = make_model().fit(train[FEATURES].to_numpy(), train["y"].to_numpy())
    return m.predict_proba(df.iloc[te][FEATURES].to_numpy())[:, 1]


def grouped_cv(df: pd.DataFrame, group_col: str, n_splits: int = 5) -> dict:
    """Walidacja krzyżowa z grupami; miary RF, Otsu, SCL, „wszystko woda" i RF uczony tylko na auto.

    Co robi: dzieli wiersze na `n_splits` foldów tak, by żadna grupa (`date` lub `block`) nie
      występowała jednocześnie w uczeniu i teście; w każdym foldzie uczy RF na reszcie i
      przewiduje fold. Predykcje ze wszystkich foldów (OOF) łączy i liczy miary RAZ na całości.
    Dlaczego tak: (1) po grupach, nie po wierszach, bo sąsiednie piksele i piksele tej samej sceny
      są niemal kopiami: losowy podział przecieka i zawyża wynik. (2) `StratifiedGroupKFold` z
      warstwami klasa × źródło rozprowadza rzadkie punkty „human land" po foldach (zwykły
      GroupKFold dawał fold bez lądu). (3) Miary z połączonych predykcji, bo fold ma tylko kilka
      do kilkunastu punktów lądu `human`, a średnia z takich foldów byłaby szumem. (4) Trening = wszystkie wiersze poza testem,
      więc punkty `human` są zawsze oceniane poza próbą.
    Wejście → wyjście: tabela z `build_table`, nazwa kolumny grupy → słownik:
      miary dla wszystkich wierszy pod kluczami metod (`rf`, `otsu`, `scl`, `all_water`, `rf_auto`),
      `rf_t` (RF z progiem t* wybranym zagnieżdżonie, osobno w każdym foldzie; t* w `thresholds`),
      `human` (warstwa `shore`, wynik główny: z CI i McNemarem), `per_stratum`, `human_pooled`
      (gdy jest `shore_low`), `folds` (lista (train_idx, test_idx)) i `oof` (predykcje).
      Zbyt mało grup albo fold bez lądu `human` rzucają ValueError (cichy zły podział jest gorszy
      niż błąd).
    Jak to obronić: Otsu i SCL nie są uczone, tylko czytane z kolumn, więc porównanie jest uczciwe;
      „all_water" pokazuje, ile wart jest wynik, który nic nie rozpoznaje.
    """
    df = df.reset_index(drop=True)
    n_groups = df[group_col].nunique()
    if n_groups < n_splits:
        raise ValueError(f"grupa {group_col!r}: {n_groups} grup < n_splits={n_splits}")
    human = (df.source == "human").to_numpy()
    strata = df["y"].to_numpy() * 2 + human
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
    folds = list(cv.split(df, strata, df[group_col]))
    for i, (_, te) in enumerate(folds):
        if not (human[te] & (df["y"].to_numpy()[te] == 0)).any():
            raise ValueError(f"fold {i} ({group_col}) nie zawiera lądu human; za mało punktów lub grup")
    n = len(df)
    oof = {"rf": np.zeros(n, int), "rf_auto": np.zeros(n, int), "rf_t": np.zeros(n, int)}
    thresholds, curves = [], []
    for tr, te in folds:
        p = _fit_predict(df, tr, te, auto_only=False)
        t, curve = _nested_threshold(df, tr)
        thresholds.append(t)
        curves.append(curve)
        oof["rf"][te] = p >= 0.5
        oof["rf_t"][te] = p >= t
        oof["rf_auto"][te] = _fit_predict(df, tr, te, auto_only=True) >= 0.5
    preds = {"rf": oof["rf"], "rf_t": oof["rf_t"], "rf_auto": oof["rf_auto"], "otsu": df["otsu_pred"].to_numpy(),
             "scl": df["scl_pred"].to_numpy(), "all_water": np.ones(n, int)}
    y = df["y"].to_numpy()

    def sub(mask: np.ndarray, ci: bool) -> dict:
        return _evaluate(y[mask], {k: v[mask] for k, v in preds.items()}, ci)

    res = _evaluate(y, preds, ci=False)
    strat = df["stratum"].to_numpy() if "stratum" in df else np.full(n, HEADLINE_STRATUM)
    head = human & (strat == HEADLINE_STRATUM)
    if not head.any():
        head = human
    res["human"] = sub(head, True)
    res["per_stratum"] = {s: sub(human & (strat == s), True) for s in sorted(set(strat[human]))}
    if "shore_low" in res["per_stratum"]:
        res["human_pooled"] = sub(human & np.isin(strat, L.HUMAN_STRATA), True)
    res.update(folds=folds, oof=oof, group_col=group_col, thresholds=thresholds, threshold_curves=curves)
    return res


def train_final(df: pd.DataFrame) -> RandomForestClassifier:
    """RF uczony na wszystkich wierszach tabeli (te same hiperparametry co w walidacji).

    Co robi: dopasowuje `make_model()` do całej tabeli (auto + human).
    Dlaczego tak: model końcowy ma widzieć wszystkie etykiety; jego jakość szacujemy z `grouped_cv`
      (modele z foldów), a nie z tego dopasowania, które zna własne dane uczące.
    Wejście → wyjście: tabela z `build_table` → uczony RandomForestClassifier.
    Jak to obronić: te same hiperparametry co w walidacji, więc wynik CV dotyczy tej konfiguracji.
    """
    return make_model().fit(df[FEATURES].to_numpy(), df["y"].to_numpy())


def permutation_importance_table(df: pd.DataFrame, folds: list, seed: int = SEED,
                                 human_only: bool = False) -> pd.DataFrame:
    """Ważność cech: spadek BA po przetasowaniu cechy, mierzony na foldach testowych `by_block`.

    Co robi: w każdym foldzie uczy RF na części uczącej, a potem na części testowej tasuje po
      jednej cesze (10 powtórzeń) i mierzy, o ile spada dokładność zrównoważona. Z `human_only`
      część testowa jest ograniczona do punktów `human` (uczenie bez zmian).
    Dlaczego tak: liczone na danych testowych, bo RF z `min_samples_leaf=2` prawie zapamiętuje
      wiersze uczące, więc ważność liczona na nich jest bez znaczenia. Pełny fold testowy to w
      większości punkty `auto` (łatwe, poprawne dla Otsu z konstrukcji), więc spadki BA są tam
      małe i zaniżone; tabela na samych punktach `human` pokazuje cechy ważne na trudnym brzegu.
    Wejście → wyjście: tabela i foldy z `grouped_cv` → DataFrame (feature, mean, std) malejąco
      po `mean`; mean/std po foldach.
    Jak to obronić: pasma i indeksy są skorelowane, więc ważność dzieli się między nie (cecha
      „nieważna" może mieć zastępnik); wniosek dotyczy grup cech, nie pojedynczej kolumny.
    """
    df = df.reset_index(drop=True)
    per_fold = []
    for tr, te in folds:
        m = make_model(seed).fit(df.iloc[tr][FEATURES].to_numpy(), df.iloc[tr]["y"].to_numpy())
        if human_only:
            te = te[(df.iloc[te]["source"] == "human").to_numpy()]
        r = permutation_importance(m, df.iloc[te][FEATURES].to_numpy(), df.iloc[te]["y"].to_numpy(),
                                   scoring="balanced_accuracy", n_repeats=10, random_state=seed,
                                   n_jobs=1)
        per_fold.append(r.importances_mean)
    a = np.array(per_fold)
    out = pd.DataFrame({"feature": FEATURES, "mean": a.mean(0), "std": a.std(0)})
    return out.sort_values("mean", ascending=False).reset_index(drop=True)


# --- model na dysku ----------------------------------------------------------------------

def file_sha256(path: Path) -> str:
    """Suma SHA-256 zawartości pliku (hex).

    Co robi: czyta bajty pliku i liczy skrót.
    Dlaczego tak: zapisana w bundle suma etykiet i configu pozwala stwierdzić, z jakich danych jest model.
    Wejście → wyjście: ścieżka → 64-znakowy ciąg hex.
    Jak to obronić: standardowy `hashlib.sha256`; ta sama zawartość daje ten sam skrót.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_model(model: RandomForestClassifier, path: Path, meta: dict | None = None) -> None:
    """Zapisuje model razem z opisem potrzebnym do poprawnej predykcji (bundle, atomowo).

    Co robi: tworzy słownik {model, features, bands, parametry masek chmur, klasy, nodata, opis Otsu,
      wersja sklearn, czas} + `meta` (siatka, sumy kontrolne etykiet i configu, liczności, wynik CV).
    Dlaczego tak: predykcja musi użyć DOKŁADNIE tej kolejności cech i tych reguł masek co trening;
      bundle je niesie, więc kod predykcji nie zgaduje. Próg Otsu NIE jest zapisany, bo jest
      liczony dla każdej sceny (`otsu.scene_threshold`) przy predykcji.
    Wejście → wyjście: model, ścieżka, opcjonalny słownik meta → plik joblib.
    Jak to obronić: sumy SHA etykiet i configu pozwalają stwierdzić, z jakich danych jest model.
    """
    bundle = {"model": model, "features": FEATURES, "bands": BANDS, "cloud_mask": cloud_mask_description(), "classes": {"0": "land", "1": "water"}, "nodata": 255,
              "otsu": {"per_scene": True, "helper": "mielizna.otsu.scene_threshold",
                       "mask": "aoi & valid & ~cloud"},
              "sklearn_version": sklearn.__version__,
              "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    bundle.update(meta or {})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    joblib.dump(bundle, tmp)
    tmp.replace(path)


def load_model(path: Path) -> dict:
    """Wczytuje bundle; sprawdza zgodność cech i ostrzega o innej wersji sklearn.

    Co robi: `joblib.load`, potem walidacja. Inna kolejność/zestaw cech lub opis maski chmur = ValueError (model
      dawałby cicho błędne wyniki); inna wersja sklearn = ostrzeżenie (model zwykle działa,
      ale nie ma gwarancji).
    Dlaczego tak: model z innymi cechami dałby cicho błędne mapy, więc to błąd, a nie ostrzeżenie.
      Tak samo opis maski chmur (bundle["cloud_mask"]): inna reguła chmur niż w treningu zmienia, które
      piksele model w ogóle widzi.
    Wejście → wyjście: ścieżka → słownik bundle.
    Jak to obronić: kolejność cech jest jedyną rzeczą, której RF nie sprawdzi sam; test pokrywa
      obie ścieżki (ValueError i ostrzeżenie).
    """
    bundle = joblib.load(path)
    if bundle["features"] != FEATURES:
        raise ValueError("features w modelu różnią się od mielizna.features.FEATURES; wytrenuj model ponownie")
    if bundle.get("sklearn_version") != sklearn.__version__:
        warnings.warn(f"Model trenowany w sklearn {bundle.get('sklearn_version')}, "
                      f"zainstalowany {sklearn.__version__}", UserWarning, stacklevel=2)
    if bundle.get("cloud_mask") != cloud_mask_description():
        raise ValueError("cloud_mask w modelu różni się od mielizna.s2.cloud_mask_description(); wytrenuj model ponownie")
    bundle.setdefault("water_threshold", 0.5)
    return bundle


# --- raport -------------------------------------------------------------------------------

def _f(v: float) -> str:
    return "n/a" if v is None or np.isnan(v) else f"{v:.3f}"


def _p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def _fc(m: dict, key: str) -> str:
    lo, hi = m["ci"][key]
    return f"{_f(m[key])} [{_f(lo)}–{_f(hi)}]"


def _human_table(block: dict, methods=TABLE_ORDER, label: str | None = None) -> list[str]:
    pre = f"| {label} " if label else ""
    rows = []
    for k in methods:
        m = block[k]
        k_land = m["confusion"][0][0]
        rows.append(f"{pre}| {METHOD_NAMES[k]} | {m['n']} | {_fc(m, 'oa')} | {_fc(m, 'bacc')} | "
                    f"{_fc(m, 'kappa')} | {k_land}/{m['n_land']} {_fc(m, 'recall_land')} | "
                    f"{_fc(m, 'recall_water')} | {_fc(m, 'f1_land')} |")
    return rows


_HEAD = ("| method | n | OA [CI] | BA [CI] | κ [CI] | recall_land k/n [CI] | recall_water [CI] "
         "| F1_land [CI] |\n|---|---|---|---|---|---|---|---|")


def _mcnemar_lines(block: dict) -> list[str]:
    """McNemar liczy błędy (OA), nie BA; b/c podane też osobno dla wody i lądu."""
    mc = block["mcnemar"]
    out = []
    for k, n in (("vs_otsu", "Otsu"), ("vs_scl", "SCL")):
        bc = mc[k]["by_class"]
        out.append(f"McNemar RF–{n} (liczby błędów, czyli dokładność; dominuje woda): b = {mc[k]['b']}, "
                   f"c = {mc[k]['c']}, p {_p(mc[k]['p'])}; wiersze wody b = {bc['water']['b']}, "
                   f"c = {bc['water']['c']}; wiersze lądu b = {bc['land']['b']}, c = {bc['land']['c']}")
    return out


def render_report(res: dict, importance: pd.DataFrame, counts: dict,
                  importance_human: pd.DataFrame | None = None, final_curve: np.ndarray | None = None) -> str:
    """Raport w markdown: nagłówek z licznościami i tabele A–E (liczby z 3 miejscami, CI w nawiasach).

    Co robi: formatuje wyniki `grouped_cv` (`by_block`, `by_scene`), ważność cech i liczności.
    Dlaczego tak: ten sam tekst idzie na stdout, do `rf_report.md` i do `rf_metrics.json`, więc
      liczby w obronie i w pliku są identyczne. Tabela A (human `shore`, by_block) to wynik główny;
      linia M2 podaje OA wprost, ale razem z poziomem „wszystko woda" i miarami, które coś mówią.
    Wejście → wyjście: {"by_block", "by_scene"} + tabela ważności (pełne foldy testowe) +
      `table_counts` + opcjonalnie tabela ważności na punktach `human` (Tabela E2) → str.
    Jak to obronić: nic tu nie jest wybierane pod wynik; kryterium M2 jest raportowane jako
      MET/NOT MET bez strojenia.
    """
    bb, bs = res["by_block"], res["by_scene"]
    src = counts["rows_by_source_class"]
    d = counts["dropped"]
    out = ["# Raport Random Forest (woda / ląd)", "",
           "Wiersze (źródło × klasa): " + "; ".join(f"{s}: woda {v['water']}, ląd {v['land']}" for s, v in src.items())
           + f". Punkty human: {counts['human_blocks']} bloków 500 m, {counts['human_scenes']} scen "
           f"(ląd: {counts['human_land_blocks']} bloków, {counts['human_land_scenes']} scen).",
           f"Odrzucone: skip/bez etykiety {d.get('unlabelled_or_skip', 0)}, scena niedozwolona "
           f"{d.get('not_usable', 0)}, chmura/brak danych {d.get('not_ok', 0)}, NaN {d.get('nan', 0)}.", ""]
    h = bb["human"]
    out += ["## Tabela A — human `shore`, by_block (wynik główny)", "", _HEAD,
            *_human_table(h, TABLE_ORDER_T), "", *_mcnemar_lines(h), "",
            f"RF t*: próg jednostronny (woda iff P ≥ t*), wybrany zagnieżdżonym CV w każdym foldzie; t* po foldach "
            f"(by_block): {bb['thresholds']}. Wynik główny M2 poniżej zostaje przy RF @ 0,5.", "",
            *([f"Średnia krzywa BA(t) końcowa (10 powtórzeń OOF, siatka {THRESHOLD_GRID[0]}–{THRESHOLD_GRID[-1]}): "
               + ", ".join(f"{t:.2f}={b:.3f}" for t, b in zip(THRESHOLD_GRID, final_curve))
               + f"; t* końcowy = {_choose_threshold_from_curve(final_curve):.2f}.", ""]
              if final_curve is not None else []),
            f"Macierz pomyłek RF [[tn, fp], [fn, tp]]: {h['rf']['confusion']}", ""]
    rfm, aw = h["rf"], h["all_water"]
    lo, hi = rfm["ci"]["oa"]
    met = "MET" if rfm["oa"] >= 0.95 else "NOT MET"
    out += [f"M2 (OA ≥ 95 %, human, by_block): RF = {100 * rfm['oa']:.1f} % [{100 * lo:.1f}–{100 * hi:.1f}] → {met}. "
            f"Context: all-water = {100 * aw['oa']:.1f} %, so OA alone is near-trivial; substantive measures "
            f"BA = {_f(rfm['bacc'])}, κ = {_f(rfm['kappa'])}, recall_land = {rfm['confusion'][0][0]}/{rfm['n_land']}.",
            "Punkty `auto` wybrano przez częstość wody z Otsu, więc Otsu jest na nich poprawny z konstrukcji; "
            "porównanie RF z Otsu ma sens tylko na punktach `human`.",
            f"Wskaźnik pomocniczy (nie próg): BA RF {_f(rfm['bacc'])} vs Otsu {_f(h['otsu']['bacc'])}. "
            f"McNemar porównuje liczby błędów (dokładność), a nie BA, i dominuje w nim woda, więc jego p "
            f"{_p(h['mcnemar']['vs_otsu']['p'])} nie mówi, czy BA jest istotnie lepsze; "
            f"o lądzie mówią wiersze lądu b/c powyżej.",
            "Przedziały BA, κ, F1_land to bootstrap po wierszach (optymistyczny: punkty są skupione w blokach).", ""]
    hs = bs["human"]
    out += ["## Tabela B — human `shore`, by_scene", "", _HEAD, *_human_table(hs), "", *_mcnemar_lines(hs), "",
            f"Macierz pomyłek RF [[tn, fp], [fn, tp]]: {hs['rf']['confusion']}", ""]
    if "shore_low" in bb["per_stratum"]:
        out += ["## Tabela C — `shore_low` i human łącznie, by_block", "",
                "| set " + _HEAD.replace("\n|---", "\n|---|---", 1),
                *_human_table(bb["per_stratum"]["shore_low"], TABLE_ORDER_T, label="shore_low"),
                *_human_table(bb["human_pooled"], TABLE_ORDER_T, label="shore ∪ shore_low"), "",
                *[f"McNemar (shore_low) " + s[len("McNemar "):] for s in _mcnemar_lines(bb["per_stratum"]["shore_low"])],
                *[f"McNemar (łącznie) " + s[len("McNemar "):] for s in _mcnemar_lines(bb["human_pooled"])], "",
                "OA na zbiorze łącznym nie jest porównywalne z M2 (inna mieszanka warstw). Każda warstwa jest "
                "próbą losową, więc recall i BA dla klas są interpretowalne.", ""]
    out += ["## Tabela D — wszystkie wiersze (pomocniczo)", "", "| CV | method | OA | κ | F1_water | F1_land |",
            "|---|---|---|---|---|---|"]
    for cv, r in (("by_scene", bs), ("by_block", bb)):
        for k in TABLE_ORDER:
            m = r[k]
            out.append(f"| {cv} | {METHOD_NAMES[k]} | {_f(m['oa'])} | {_f(m['kappa'])} | {_f(m['f1_water'])} | {_f(m['f1_land'])} |")
    out += ["", "Punkty auto są poprawne dla Otsu z konstrukcji (wybrane przez częstość wody z Otsu), "
            "więc ta tabela zawyża Otsu i SCL.", "",
            "## Tabela E — ważność cech (permutacyjna, by_block OOF, ΔBA)", "", "| feature | mean | std |", "|---|---|---|"]
    out += [f"| {r.feature} | {_f(r['mean'])} | {_f(r['std'])} |" for _, r in importance.iterrows()]
    out += ["", "Pasma i indeksy są skorelowane, więc ważność rozkłada się między nie. Tabela E liczona na "
            "pełnych foldach testowych, w większości punktach `auto` (łatwych), więc ΔBA jest mały i zaniżony."]
    if importance_human is not None:
        out += ["", "## Tabela E2 — ważność cech na punktach human foldów testowych (by_block, ΔBA, 10 powtórzeń)",
                "", "| feature | mean | std |", "|---|---|---|"]
        out += [f"| {r.feature} | {_f(r['mean'])} | {_f(r['std'])} |" for _, r in importance_human.iterrows()]
    out += [""]
    return "\n".join(out)
