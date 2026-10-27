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
- Random Forest: 100 drzew decyzyjnych uczonych na losowych podpróbach wierszy i cech; klasa to
  głosowanie drzew. Zaleta: radzi sobie z nieliniowością i skorelowanymi pasmami, nie wymaga
  skalowania cech. `class_weight="balanced"` waży rzadszą klasę (ląd) tak, by nie była ignorowana,
  a `min_samples_leaf=2` zabrania liścia z jednym punktem (mniej zapamiętywania szumu).
- Przeciek przestrzenny: sąsiednie piksele i piksele tej samej sceny są niemal identyczne. Losowy
  podział wierszy wrzuciłby „bliźniaki" do uczenia i do testu, a model wyglądałby na świetny,
  bo rozpoznaje znane miejsca, a nie uczy się wody. Dlatego walidujemy po GRUPACH: całe bloki
  500 m (`by_block`, główny wynik — test na miejscach, których model nie widział) albo całe
  sceny (`by_scene` — test na dniach, których model nie widział).
- Dokładność zrównoważona (balanced accuracy, BA): średnia z czułości dla wody i dla lądu,
  (recall_water + recall_land) / 2. Przy 168 punktach wody na 21 lądu zwykła dokładność (OA)
  premiuje ignorowanie lądu: „wszystko woda" ma OA 0,89, ale BA tylko 0,50. BA = 0,50 to
  poziom losowy niezależnie od proporcji klas.
- Kappa Cohena (κ): zgodność ponad zgodność przypadkową; 0 = tyle co losowo, 1 = idealnie.
- Test McNemara: porównuje dwie metody na TYCH SAMYCH punktach, patrząc wyłącznie na punkty,
  na których się różnią: b = RF dobrze a druga źle, c = odwrotnie. Gdyby metody były równie
  dobre, b i c byłyby po połowie; p to dokładne prawdopodobieństwo (dwumianowe) tak skrajnego
  podziału. Małe p = różnica nie jest przypadkiem. Dlatego mała próba lądu daje duże p, nawet
  gdy różnica punktowa wygląda dobrze.
- Przedziały ufności 95%: Wilson dla proporcji (OA, recall); bootstrap warstwowy (2000 losowań
  w obrębie klasy) dla BA, κ i F1_land. Bootstrap po wierszach jest optymistyczny, bo punkty
  leżą w skupiskach (15 bloków), więc prawdziwa niepewność jest nieco większa.
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
from mielizna.s2 import BANDS, cloud_mask, valid_mask

log = logging.getLogger(__name__)
SEED = 42
BLOCK_M = 500
HEADLINE_STRATUM = "shore"
N_BOOT = 2000
METHODS = ("rf", "otsu", "scl", "all_water", "rf_auto")
TABLE_COLUMNS = FEATURES + ["y", "date", "block", "otsu_pred", "scl_pred", "source", "stratum",
                            "id", "otsu_t"]
METHOD_NAMES = {"all_water": "all-water", "otsu": "Otsu", "scl": "SCL==6", "rf": "RF",
                "rf_auto": "RF auto-only"}


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
    """Liczby do nagłówka raportu: wiersze źródło × klasa, bloki i sceny `human`, odrzucone."""
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
    Dlaczego tak: dla małych n (21 punktów lądu) zwykły przedział „p ± 1,96·SE" wychodzi poza [0, 1]
      i jest zbyt wąski przy p bliskim 0 lub 1; Wilson tego nie robi.
    Wejście → wyjście: liczba sukcesów k, liczba prób n → (dolna, górna); n = 0 → (NaN, NaN).
    Jak to obronić: wzór podręcznikowy; 13/21 daje [0,409; 0,792] (sprawdzone ręcznie w teście).
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
      dla małych b + c, co jest naszym przypadkiem.
    Wejście → wyjście: dwa wektory bool „czy trafiła" → {"b", "c", "p"}; b + c = 0 → p = 1.
    Jak to obronić: test sparowany jest właściwy, bo obie metody oceniamy na identycznych punktach;
      hipoteza zerowa: P(b) = P(c).
    """
    a, b_ = np.asarray(correct_a, bool), np.asarray(correct_b, bool)
    b, c = int((a & ~b_).sum()), int((~a & b_).sum())
    p = 1.0 if b + c == 0 else float(binomtest(min(b, c), b + c, 0.5).pvalue)
    return {"b": b, "c": c, "p": p}


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
        out["mcnemar"] = {"vs_otsu": mcnemar_exact(right["rf"], right["otsu"]),
                          "vs_scl": mcnemar_exact(right["rf"], right["scl"])}
    return out


# --- model i walidacja ------------------------------------------------------------------

def make_model(seed: int = SEED) -> RandomForestClassifier:
    """Random Forest o zamrożonych hiperparametrach (100 drzew, min_samples_leaf=2, balanced).

    Co robi: zwraca nieuczony klasyfikator.
    Dlaczego tak: nie strojimy parametrów, bo każda liczba, którą mamy, jest liczbą testową;
      strojenie na niej zawyżyłoby wynik. `balanced` kompensuje mniej licznych punktów lądu.
    Wejście → wyjście: seed → RandomForestClassifier. Jak to obronić: wartości domyślne
      zalecane w literaturze, ustalone przed obejrzeniem wyników.
    """
    return RandomForestClassifier(n_estimators=100, min_samples_leaf=2, class_weight="balanced",
                                  n_jobs=-1, random_state=seed)


def _fit_predict(df: pd.DataFrame, tr: np.ndarray, te: np.ndarray, auto_only: bool) -> np.ndarray:
    train = df.iloc[tr]
    if auto_only:
        train = train[train.source == "auto"]
    m = make_model().fit(train[FEATURES].to_numpy(), train["y"].to_numpy())
    return m.predict(df.iloc[te][FEATURES].to_numpy())


def grouped_cv(df: pd.DataFrame, group_col: str, n_splits: int = 5) -> dict:
    """Walidacja krzyżowa z grupami; miary RF, Otsu, SCL, „wszystko woda" i RF uczony tylko na auto.

    Co robi: dzieli wiersze na `n_splits` foldów tak, by żadna grupa (`date` lub `block`) nie
      występowała jednocześnie w uczeniu i teście; w każdym foldzie uczy RF na reszcie i
      przewiduje fold. Predykcje ze wszystkich foldów (OOF) łączy i liczy miary RAZ na całości.
    Dlaczego tak: (1) po grupach, nie po wierszach, bo sąsiednie piksele i piksele tej samej sceny
      są niemal kopiami: losowy podział przecieka i zawyża wynik. (2) `StratifiedGroupKFold` z
      warstwami klasa × źródło rozprowadza rzadkie punkty „human land" po foldach (zwykły
      GroupKFold dawał fold bez lądu). (3) Miary z połączonych predykcji, bo fold ma 3–6 punktów
      lądu, a średnia z takich foldów byłaby szumem. (4) Trening = wszystkie wiersze poza testem,
      więc punkty `human` są zawsze oceniane poza próbą.
    Wejście → wyjście: tabela z `build_table`, nazwa kolumny grupy → słownik:
      miary dla wszystkich wierszy pod kluczami metod (`rf`, `otsu`, `scl`, `all_water`, `rf_auto`),
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
    oof = {"rf": np.zeros(n, int), "rf_auto": np.zeros(n, int)}
    for tr, te in folds:
        oof["rf"][te] = _fit_predict(df, tr, te, auto_only=False)
        oof["rf_auto"][te] = _fit_predict(df, tr, te, auto_only=True)
    preds = {"rf": oof["rf"], "rf_auto": oof["rf_auto"], "otsu": df["otsu_pred"].to_numpy(),
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
    res.update(folds=folds, oof=oof, group_col=group_col)
    return res


def train_final(df: pd.DataFrame) -> RandomForestClassifier:
    """RF uczony na wszystkich wierszach tabeli (te same hiperparametry co w walidacji)."""
    return make_model().fit(df[FEATURES].to_numpy(), df["y"].to_numpy())


def permutation_importance_table(df: pd.DataFrame, folds: list, seed: int = SEED) -> pd.DataFrame:
    """Ważność cech: spadek BA po przetasowaniu cechy, mierzony na foldach testowych `by_block`.

    Co robi: w każdym foldzie uczy RF na części uczącej, a potem na części testowej tasuje po
      jednej cesze (10 powtórzeń) i mierzy, o ile spada dokładność zrównoważona.
    Dlaczego tak: liczone na danych testowych, bo RF z `min_samples_leaf=2` prawie zapamiętuje
      wiersze uczące, więc ważność liczona na nich jest bez znaczenia.
    Wejście → wyjście: tabela i foldy z `grouped_cv` → DataFrame (feature, mean, std) malejąco
      po `mean`; mean/std po foldach.
    Jak to obronić: pasma i indeksy są skorelowane, więc ważność dzieli się między nie (cecha
      „nieważna" może mieć zastępnik); wniosek dotyczy grup cech, nie pojedynczej kolumny.
    """
    df = df.reset_index(drop=True)
    per_fold = []
    for tr, te in folds:
        m = make_model(seed).fit(df.iloc[tr][FEATURES].to_numpy(), df.iloc[tr]["y"].to_numpy())
        r = permutation_importance(m, df.iloc[te][FEATURES].to_numpy(), df.iloc[te]["y"].to_numpy(),
                                   scoring="balanced_accuracy", n_repeats=10, random_state=seed,
                                   n_jobs=1)
        per_fold.append(r.importances_mean)
    a = np.array(per_fold)
    out = pd.DataFrame({"feature": FEATURES, "mean": a.mean(0), "std": a.std(0)})
    return out.sort_values("mean", ascending=False).reset_index(drop=True)


# --- model na dysku ----------------------------------------------------------------------

def file_sha256(path: Path) -> str:
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
    bundle = {"model": model, "features": FEATURES, "bands": BANDS, "cloud_scl_classes": [3, 8, 9, 10],
              "cloud_dilate_px": 2, "classes": {"0": "land", "1": "water"}, "nodata": 255,
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

    Co robi: `joblib.load`, potem walidacja. Inna kolejność/zestaw cech = ValueError (model
      dawałby cicho błędne wyniki); inna wersja sklearn = ostrzeżenie (model zwykle działa,
      ale nie ma gwarancji).
    Wejście → wyjście: ścieżka → słownik bundle.
    """
    bundle = joblib.load(path)
    if bundle["features"] != FEATURES:
        raise ValueError("features w modelu różnią się od mielizna.features.FEATURES; wytrenuj model ponownie")
    if bundle.get("sklearn_version") != sklearn.__version__:
        warnings.warn(f"Model trenowany w sklearn {bundle.get('sklearn_version')}, "
                      f"zainstalowany {sklearn.__version__}", UserWarning, stacklevel=2)
    return bundle


# --- raport -------------------------------------------------------------------------------

def _f(v: float) -> str:
    return "n/a" if v is None or np.isnan(v) else f"{v:.3f}"


def _p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def _fc(m: dict, key: str) -> str:
    lo, hi = m["ci"][key]
    return f"{_f(m[key])} [{_f(lo)}–{_f(hi)}]"


def _human_table(block: dict, methods=METHODS, label: str | None = None) -> list[str]:
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
    mc = block["mcnemar"]
    return [f"McNemar RF–{n}: b = {mc[k]['b']}, c = {mc[k]['c']}, p {_p(mc[k]['p'])}"
            for k, n in (("vs_otsu", "Otsu"), ("vs_scl", "SCL"))]


def render_report(res: dict, importance: pd.DataFrame, counts: dict) -> str:
    """Raport w markdown: nagłówek z licznościami i tabele A–E (liczby z 3 miejscami, CI w nawiasach).

    Co robi: formatuje wyniki `grouped_cv` (`by_block`, `by_scene`), ważność cech i liczności.
    Dlaczego tak: ten sam tekst idzie na stdout, do `rf_report.md` i do `rf_metrics.json`, więc
      liczby w obronie i w pliku są identyczne. Tabela A (human `shore`, by_block) to wynik główny;
      linia M2 podaje OA wprost, ale razem z poziomem „wszystko woda" i miarami, które coś mówią.
    Wejście → wyjście: {"by_block", "by_scene"} + tabela ważności + `table_counts` → str.
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
            *_human_table(h), "", *_mcnemar_lines(h), "",
            f"Macierz pomyłek RF [[tn, fp], [fn, tp]]: {h['rf']['confusion']}", ""]
    rfm, aw = h["rf"], h["all_water"]
    lo, hi = rfm["ci"]["oa"]
    met = "MET" if rfm["oa"] >= 0.95 else "NOT MET"
    out += [f"M2 (OA ≥ 95 %, human, by_block): RF = {100 * rfm['oa']:.1f} % [{100 * lo:.1f}–{100 * hi:.1f}] → {met}. "
            f"Context: all-water = {100 * aw['oa']:.1f} %, so OA alone is near-trivial; substantive measures "
            f"BA = {_f(rfm['bacc'])}, κ = {_f(rfm['kappa'])}, recall_land = {rfm['confusion'][0][0]}/{rfm['n_land']}.",
            "Punkty `auto` wybrano przez częstość wody z Otsu, więc Otsu jest na nich poprawny z konstrukcji; "
            "porównanie RF z Otsu ma sens tylko na punktach `human`.",
            f"Wskaźnik pomocniczy (nie próg): BA RF {_f(rfm['bacc'])} vs Otsu {_f(h['otsu']['bacc'])}, "
            f"McNemar p {_p(h['mcnemar']['vs_otsu']['p'])}.",
            "Przedziały BA, κ, F1_land to bootstrap po wierszach (optymistyczny: punkty są skupione w blokach).", ""]
    hs = bs["human"]
    out += ["## Tabela B — human `shore`, by_scene", "", _HEAD, *_human_table(hs), "", *_mcnemar_lines(hs), "",
            f"Macierz pomyłek RF [[tn, fp], [fn, tp]]: {hs['rf']['confusion']}", ""]
    if "shore_low" in bb["per_stratum"]:
        out += ["## Tabela C — `shore_low` i human łącznie, by_block", "",
                "| set " + _HEAD.replace("\n|---", "\n|---|---", 1),
                *_human_table(bb["per_stratum"]["shore_low"], label="shore_low"),
                *_human_table(bb["human_pooled"], label="shore ∪ shore_low"), "",
                *[f"McNemar (shore_low) " + s[len("McNemar "):] for s in _mcnemar_lines(bb["per_stratum"]["shore_low"])],
                *[f"McNemar (łącznie) " + s[len("McNemar "):] for s in _mcnemar_lines(bb["human_pooled"])], "",
                "OA na zbiorze łącznym nie jest porównywalne z M2 (inna mieszanka warstw). Każda warstwa jest "
                "próbą losową, więc recall i BA dla klas są interpretowalne.", ""]
    out += ["## Tabela D — wszystkie wiersze (pomocniczo)", "", "| CV | method | OA | κ | F1_water | F1_land |",
            "|---|---|---|---|---|---|"]
    for cv, r in (("by_scene", bs), ("by_block", bb)):
        for k in METHODS:
            m = r[k]
            out.append(f"| {cv} | {METHOD_NAMES[k]} | {_f(m['oa'])} | {_f(m['kappa'])} | {_f(m['f1_water'])} | {_f(m['f1_land'])} |")
    out += ["", "Punkty auto są poprawne dla Otsu z konstrukcji (wybrane przez częstość wody z Otsu), "
            "więc ta tabela zawyża Otsu i SCL.", "",
            "## Tabela E — ważność cech (permutacyjna, by_block OOF, ΔBA)", "", "| feature | mean | std |", "|---|---|---|"]
    out += [f"| {r.feature} | {_f(r['mean'])} | {_f(r['std'])} |" for _, r in importance.iterrows()]
    out += ["", "Pasma i indeksy są skorelowane, więc ważność rozkłada się między nie."]
    return "\n".join(out)
