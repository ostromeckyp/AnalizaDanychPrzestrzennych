"""Rzędna zwierciadła wody `h_t` dla każdej sceny: warianty R, B i C oraz zapis scenes.json.

Co robi: przypisuje scenie rzędną z najlepszego dostępnego źródła, w kolejności A > R > B > C:
  A - pomiar z modelu terenu (plan 4, na razie brak), R - znany pomiar wodowskazowy z
  `known_levels.csv`, B - pojemność z komunikatu RZGW zamieniona tabelą KŻ na rzędną,
  C - rzędna odczytana z krzywej powierzchnia -> rzędna dopasowanej do scen B/R.
Dlaczego tak: komunikaty istnieją tylko od 2019-11, a pojemność z tabeli jest bezpośrednim
  (choć niedokładnym) pomiarem poziomu; sceny bez komunikatu dostają poziom pośrednio z
  powierzchni jeziora, z uczciwie większą niepewnością. Sceny odrzucone przez kontrolę jakości
  (qc_ok False) NIE zasilają krzywej i nie dostają wariantu C (ich powierzchnia jest zła).
Wejście → wyjście: bulletins.csv + known_levels.csv + powierzchnie scen → DataFrame ze kolumnami
  date, h_t, h_method, h_source, h_sigma, h_datum, ...; krzywa jako JSON (backend
  `/api/current-level`) i scenes.json.
Jak to obronić: krzywa jest monotoniczna z konstrukcji (regresja izotoniczna + PCHIP), a jej błąd
  jest mierzony metodą leave-one-out, czyli na scenach, których krzywa nie widziała.
"""
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator
from sklearn.isotonic import IsotonicRegression

from mielizna.capacity import capacity_to_level, level_to_capacity

B_SIGMA = 0.15  # [m] założenie robocze: interpelacja-tabela ~0,13 m, zmiana krzywej 2021->2024 ~0,04 m, dzień +-1
C_EXTRAP_EXTRA = 0.1  # [m] dodatek do niepewności przy ekstrapolacji krzywej
BIN_WIDTH_KM2 = 0.5  # szerokość przedziału powierzchni, w którym bierzemy medianę h
MIN_OBS = 3  # minimum scen do dopasowania krzywej (LOO wymaga >= 2 punktów po usunięciu jednej)
H_DATUM = "unknown (RZGW, prawdopodobnie KRON86)"
PRECEDENCE = {"A": 0, "R": 1, "B": 2, "C": 3}
AREA_SOURCE = "area_otsu_km2 (Otsu, classify_stats.csv)"
log = logging.getLogger(__name__)


@dataclass
class AreaLevelCurve:
    """Krzywa powierzchnia jeziora [km2] -> rzędna [m n.p.m.].

    Co robi: trzyma węzły (area_km2, h) monotonicznej krzywej i liczy h dla zadanej powierzchni.
    Dlaczego tak: PCHIP daje gładką krzywą bez przeregulowań, ale zachowuje monotoniczność tylko
      wtedy, gdy węzły już są monotoniczne - dlatego wcześniej robimy regresję izotoniczną.
    Wejście → wyjście: `curve(a)` -> (h, extrapolated); poza [area_min, area_max] prosta przez
      ostatnie 3 węzły (nachylenie >= 0), extrapolated=True.
    Jak to obronić: rmse to błąd leave-one-out, nie błąd dopasowania; `sigma` to błąd
      leave-one-year-out (uczciwszy dla scen C, które są całymi latami bez komunikatów).
    """
    area_km2: np.ndarray
    h: np.ndarray
    rmse: float
    n_obs: int = 0
    rmse_loyo: float = float("nan")

    def __post_init__(self):
        self.area_km2 = np.asarray(self.area_km2, dtype=float)
        self.h = np.asarray(self.h, dtype=float)
        self._pchip = PchipInterpolator(self.area_km2, self.h)

    @property
    def sigma(self) -> float:
        """Niepewność wariantu C: rmse_loyo, a gdy go brak (bez grup) rmse_loo."""
        return self.rmse_loyo if np.isfinite(self.rmse_loyo) else self.rmse

    @property
    def area_min(self) -> float:
        return float(self.area_km2[0])

    @property
    def area_max(self) -> float:
        return float(self.area_km2[-1])

    def __call__(self, a: float) -> tuple[float, bool]:
        a = float(a)
        if self.area_min <= a <= self.area_max:
            return float(self._pchip(a)), False
        x, y = (self.area_km2[-3:], self.h[-3:]) if a > self.area_max else (self.area_km2[:3], self.h[:3])
        slope = max(float(np.polyfit(x, y, 1)[0]), 0.0)
        edge = self.area_km2[-1] if a > self.area_max else self.area_km2[0]
        edge_h = self.h[-1] if a > self.area_max else self.h[0]
        return float(edge_h + slope * (a - edge)), True


def _fit_knots(area: np.ndarray, h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Węzły krzywej: mediana h w przedziałach powierzchni, potem regresja izotoniczna.

    Co robi: dzieli scenę na przedziały powierzchni o szerokości BIN_WIDTH_KM2, w każdym bierze
      średnią powierzchnię i medianę rzędnej, a następnie wygładza je regresją izotoniczną.
    Dlaczego tak: mediana tłumi pojedyncze błędne scena; regresja izotoniczna (ważona liczbą
      scen w przedziale) znajduje najbliższy niemalejący ciąg wartości, więc większa
      powierzchnia nigdy nie daje niższej rzędnej.
    Wejście → wyjście: tablice area, h -> (x rosnące, y niemalejące).
    Jak to obronić: izotoniczna = „najlepsza niemalejąca aproksymacja", bez wolnych parametrów.
    """
    idx = np.floor((area - area.min()) / BIN_WIDTH_KM2).astype(int)
    xs, ys, ws = [], [], []
    for b in np.unique(idx):
        m = idx == b
        xs.append(area[m].mean())
        ys.append(np.median(h[m]))
        ws.append(m.sum())
    if len(xs) < 2:
        raise ValueError("Za mało różnych powierzchni do dopasowania krzywej (potrzeba >= 2 przedziałów)")
    y = IsotonicRegression(increasing=True).fit_transform(xs, ys, sample_weight=ws)
    return np.asarray(xs), np.asarray(y)


def _cv_rmse(area: np.ndarray, h: np.ndarray, folds: list[np.ndarray]) -> tuple[float, int]:
    """RMSE walidacji krzyżowej: dla każdego zbioru indeksów `fold` dopasuj bez niego i zmierz błąd."""
    errs, skipped = [], 0
    for fold in folds:
        keep = np.ones(area.size, bool)
        keep[fold] = False
        try:
            xi, yi = _fit_knots(area[keep], h[keep])
        except ValueError:
            skipped += 1
            continue
        curve = AreaLevelCurve(xi, yi, np.nan)
        errs.extend(curve(area[i])[0] - h[i] for i in fold)
    rmse = float(np.sqrt(np.mean(np.square(errs)))) if errs else float("nan")
    return rmse, skipped


def fit_area_level(area_km2: np.ndarray, h: np.ndarray, groups: np.ndarray | None = None) -> AreaLevelCurve:
    """Dopasowuje monotoniczną krzywą powierzchnia -> rzędna z oceną błędu LOO i (opcjonalnie) LOYO.

    Co robi: węzły z `_fit_knots` łączy interpolatorem PCHIP; liczy RMSE metodą leave-one-out
      (`rmse`) oraz, gdy podano `groups` (np. rok sceny), metodą leave-one-group-out (`rmse_loyo`).
    Dlaczego tak: leave-one-out = po kolei usuwamy jedną scenę, dopasowujemy krzywą do reszty i
      sprawdzamy, jak trafia w usuniętą. Sceny C to całe lata bez komunikatów, a błędy sceny
      z tego samego roku są skorelowane (ten sam stan roślinności, ten sam poziom), więc
      LOO jest zbyt optymistyczne; leave-one-year-out usuwa cały rok naraz i lepiej odtwarza
      sytuację „rok, którego krzywa nie widziała". Predyktorem jest powierzchnia Otsu, nie RF:
      RF uznaje odsłonięty muł za wodę, więc jego powierzchnia nasyca się (~12,9 km2 poniżej
      ~194 m) i LOO wynosi 0,66 m wobec 0,47 m dla Otsu.
    Wejście → wyjście: area_km2[], h[] (sceny B/R, qc_ok, lake_nodata_pct <= 1), groups[] lub None
      -> AreaLevelCurve (rmse_loyo = NaN bez groups). Ograniczenia (D3): latem 2020 powierzchnia
      jest systematycznie mniejsza przy tym samym poziomie (efekt powierzchni: roślinność,
      zakwit); zmiana krzywej pojemności wpływa najwyżej na 0,05 m; regresja do średniej
      spłaszcza skrajności, więc dolny koniec jest zawyżony, czyli po bezpiecznej stronie.
    Jak to obronić: PCHIP nie przeregulowuje, izotoniczna gwarantuje monotoniczność, a błąd jest
      liczony poza próbą - także poza próbą roku.
    """
    area, h = np.asarray(area_km2, float), np.asarray(h, float)
    if area.size < MIN_OBS:
        raise ValueError(f"Za mało scen do krzywej: {area.size} < {MIN_OBS}")
    x, y = _fit_knots(area, h)
    rmse, skipped = _cv_rmse(area, h, [np.array([i]) for i in range(area.size)])
    if skipped:
        log.info("LOO: pominięto %d z %d foldów (za mało przedziałów)", skipped, area.size)
    rmse_loyo = float("nan")
    if groups is not None:
        g = np.asarray(groups)
        folds = [np.flatnonzero(g == v) for v in np.unique(g)]
        rmse_loyo, skipped = _cv_rmse(area, h, folds)
        if skipped:
            log.info("LOYO: pominięto %d z %d foldów (za mało przedziałów)", skipped, len(folds))
    return AreaLevelCurve(x, y, rmse, int(area.size), rmse_loyo)


def curve_areas(classify_stats: pd.DataFrame, dates: list[date]) -> dict[date, float]:
    """Powierzchnie Otsu scen (`area_otsu_km2`) do dopasowania i użycia krzywej.

    Co robi: z tabeli classify_stats.csv wybiera `area_otsu_km2` dla podanych dat.
    Dlaczego tak: predyktorem krzywej jest powierzchnia Otsu, bo RF zalicza odsłonięty muł do
      wody i jego powierzchnia nasyca się poniżej ~194 m (LOO 0,66 -> 0,47 m po zamianie na Otsu).
    Wejście → wyjście: DataFrame z kolumnami date (tekst ISO), area_otsu_km2 + lista dat
      -> {data: km2}; ValueError, gdy którejś daty brak.
    Jak to obronić: brak daty to błąd, nigdy cichy zamiennik powierzchnią RF.
    """
    by = dict(zip(pd.to_datetime(classify_stats["date"]).dt.date, classify_stats["area_otsu_km2"]))
    missing = [d for d in dates if d not in by]
    if missing:
        raise ValueError(f"Brak area_otsu_km2 w classify_stats dla {len(missing)} dat, np. {missing[:3]}")
    return {d: float(by[d]) for d in dates}


def save_area_level_curve(curve: AreaLevelCurve, path: Path) -> None:
    """Zapisuje krzywą do JSON (czyta ją backend `/api/current-level`)."""
    d = {"area_km2": [round(float(v), 4) for v in curve.area_km2], "h": [round(float(v), 4) for v in curve.h],
         "area_min": curve.area_min, "area_max": curve.area_max, "method": "isotonic+pchip",
         "extrapolation": "linear_last3", "n_points": int(len(curve.area_km2)), "n_obs": curve.n_obs,
         "rmse_loo": curve.rmse, "rmse_loyo": curve.rmse_loyo, "area_source": AREA_SOURCE}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=1), encoding="utf-8")


def load_area_level_curve(path: Path) -> AreaLevelCurve:
    """Wczytuje krzywą zapisaną przez `save_area_level_curve`."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return AreaLevelCurve(d["area_km2"], d["h"], d["rmse_loo"], d.get("n_obs", 0),
                          d.get("rmse_loyo", float("nan")) if d.get("rmse_loyo") is not None else float("nan"))


def load_overrides(path: Path) -> pd.DataFrame:
    """Wczytuje znane rzędne (start,end,h,sigma,method,source); plan 4 dopisze wiersze A."""
    df = pd.read_csv(path, dtype={"method": str})
    df["start"] = pd.to_datetime(df["start"]).dt.date
    df["end"] = pd.to_datetime(df["end"]).dt.date
    return df


def variant_b(bulletins: pd.DataFrame) -> pd.DataFrame:
    """Wariant B: rzędna z pojemności w komunikacie RZGW przez tabelę KŻ.

    Co robi: `h_t = capacity_to_level(v_current)`, niepewność stała B_SIGMA = 0,15 m.
    Dlaczego tak: 0,15 m to założenie robocze - rozbieżność interpelacja-tabela ~0,13 m, zmiana
      krzywej pojemności 2021->2024 ~0,04 m, dzień komunikatu +-1. Tabela KŻ 2023 jest jedną
      krzywą V<->h, a komunikaty przełączają v_npp z 66,3 na 65,7 (reżim zapisany w notatce).
    Wejście → wyjście: bulletins (scene_date, bulletin_date, source, v_current, v_npp, reading_utc)
      -> scene_date, h_t, h_sigma, h_method, h_source, capacity_curve_note; pojemność poza
      tabelą daje NaN i takie wiersze są pomijane.
    Jak to obronić: stała niepewność jest jawnie zapisana jako założenie, nie wyliczona.
    """
    b = bulletins.copy()
    assert b["scene_date"].is_unique, "variant_b: zdublowane scene_date w komunikatach"
    b["h_t"] = capacity_to_level(b["v_current"].to_numpy(float))
    b = b[b.h_t.notna()].copy()
    b["h_sigma"] = B_SIGMA
    b["h_method"] = "B"
    b["h_source"] = [f"RZGW komunikat {r.bulletin_date} {r.reading_utc} UTC ({r.source}), V={r.v_current} mln m3"
                     for r in b.itertuples()]
    b["capacity_curve_note"] = [f"v_npp={r.v_npp:g} ({'instrukcja do 2021' if r.v_npp >= 66 else 'instrukcja od 2022'})"
                                for r in b.itertuples()]
    b["scene_date"] = pd.to_datetime(b["scene_date"]).dt.date
    return b[["scene_date", "h_t", "h_sigma", "h_method", "h_source", "capacity_curve_note"]].reset_index(drop=True)


def variant_c(scenes: pd.DataFrame, curve: AreaLevelCurve) -> pd.DataFrame:
    """Wariant C: rzędna z krzywej powierzchnia -> rzędna dla scen bez A/R/B.

    Co robi: dla każdej sceny (kolumny date, area_km2, lake_nodata_pct) liczy h z krzywej;
      h_sigma = curve.sigma = rmse_loyo (+0,1 m przy ekstrapolacji); scena z lake_nodata_pct > 1 dostaje flagę
      `area_biased` (część jeziora niewidoczna, więc powierzchnia jest zaniżona).
    Dlaczego tak: poziom wnioskowany pośrednio musi mieć większą niepewność niż pomiar; sceny C
      to całe lata bez komunikatów, więc używamy błędu leave-one-year-out (skorelowane błędy w
      roku). `area_km2` to powierzchnia Otsu, a nie RF (RF nasyca się na odsłoniętym mule).
    Wejście → wyjście: DataFrame scen (date, area_km2 = Otsu, lake_nodata_pct) + krzywa -> date, h_t, h_sigma, h_method="C", h_source,
      extrapolated, area_biased.
    Jak to obronić: niepewność pochodzi z walidacji poza próbą (rok), a nie z dopasowania; dolny
      koniec krzywej jest zawyżony (regresja do średniej), czyli po bezpiecznej stronie.
    """
    rows = []
    for r in scenes.itertuples():
        h, extrap = curve(r.area_km2)
        biased = bool(r.lake_nodata_pct > 1)
        note = f"krzywa powierzchnia-rzędna, A_otsu={r.area_km2:.2f} km2" + (", ekstrapolacja" if extrap else "") + (", area_biased" if biased else "")
        rows.append({"date": r.date, "h_t": h, "h_sigma": curve.sigma + (C_EXTRAP_EXTRA if extrap else 0.0),
                     "h_method": "C", "h_source": note, "extrapolated": extrap, "area_biased": biased})
    return pd.DataFrame(rows, columns=["date", "h_t", "h_sigma", "h_method", "h_source", "extrapolated",
                                       "area_biased"])


def assign_levels(scene_dates: list[date], bulletins: pd.DataFrame, overrides: pd.DataFrame,
                  areas: dict[date, float] | None = None, qc_ok: dict[date, bool] | None = None,
                  nodata_pct: dict[date, float] | None = None, max_nodata_pct: float = 1.0) -> pd.DataFrame:
    """Przypisuje rzędną każdej scenie: overrides (A > R), potem B, potem C.

    Co robi: dla każdej daty bierze najlepsze źródło. Gdy podano `areas`, dopasowuje krzywą na
      scenach B/R z qc_ok i lake_nodata_pct <= max_nodata_pct (grupy LOYO = rok sceny; `areas` to
      powierzchnie Otsu, patrz `curve_areas`) i uzupełnia resztę wariantem C
      (krzywa w `df.attrs["curve"]`). Scena z qc_ok False bez A/R/B dostaje h_t = NaN i
      h_method "qc_excluded" (nigdy C).
    Dlaczego tak: scena odrzucona przez QC ma niewiarygodną powierzchnię, więc nie może ani
      kalibrować krzywej, ani z niej korzystać (kontrakt z Taskiem 8 i 11).
    Wejście → wyjście: daty, bulletins, overrides, opcjonalnie słowniki areas/qc_ok/nodata_pct
      -> DataFrame (date, h_t, h_method, h_source, h_sigma, h_datum, capacity_curve_note,
      extrapolated, area_biased) posortowany po dacie.
    Jak to obronić: kolejność źródeł i wykluczenia są jawne i pokryte testami.
    """
    b = variant_b(bulletins).set_index("scene_date") if len(bulletins) else pd.DataFrame()
    rows = []
    for d in sorted(scene_dates):
        row = {"date": d, "h_t": np.nan, "h_method": None, "h_source": "", "h_sigma": np.nan,
               "capacity_curve_note": "", "extrapolated": False, "area_biased": False}
        hit = overrides[(overrides.start <= d) & (overrides.end >= d)]
        if len(hit):
            o = hit.assign(rank=hit.method.map(PRECEDENCE)).sort_values("rank").iloc[0]
            row.update(h_t=float(o.h), h_method=o.method, h_source=str(o.source), h_sigma=float(o.sigma))
        elif d in b.index:
            r = b.loc[d]
            row.update(h_t=float(r.h_t), h_method="B", h_source=r.h_source, h_sigma=float(r.h_sigma),
                       capacity_curve_note=r.capacity_curve_note)
        rows.append(row)
    df = pd.DataFrame(rows)
    ok = pd.Series([bool(qc_ok.get(d, True)) if qc_ok else True for d in df.date], index=df.index)
    if areas is not None:
        ar = pd.Series([areas[d] for d in df.date], index=df.index)
        yr = np.array([d.year for d in df.date])
        nd = pd.Series([(nodata_pct or {}).get(d, 0.0) for d in df.date], index=df.index)
        fit = df.h_method.isin(["B", "R", "A"]) & ok & (nd <= max_nodata_pct)
        curve = fit_area_level(ar[fit].to_numpy(), df.h_t[fit].to_numpy(), groups=yr[fit.to_numpy()])
        df.attrs["curve"] = curve
        todo = df.h_method.isna() & ok
        if todo.any():
            c = variant_c(pd.DataFrame({"date": df.date[todo], "area_km2": ar[todo], "lake_nodata_pct": nd[todo]}),
                          curve)
            for col in ("h_t", "h_sigma", "h_method", "h_source", "extrapolated", "area_biased"):
                df.loc[todo, col] = c[col].to_numpy()
    excl = df.h_method.isna() & ~ok if areas is not None else pd.Series(False, index=df.index)
    df.loc[excl, "h_method"] = "qc_excluded"
    df["h_datum"] = np.where(df.h_t.notna(), H_DATUM, None)
    return df


def write_scenes_json(df: pd.DataFrame, path: Path) -> None:
    """Zapisuje scenes.json: posortowana lista obiektów (zaokrąglenia: 0,01 m, 0,001 km2).

    Co robi: wybiera pola kontraktu, NaN zamienia na null, liczy `capacity_mln_m3` z h_t
      (null gdy brak rzędnej) i dodaje qc_ok oraz qc_reason (kontrakt z Taskiem 8).
    Dlaczego tak: frontend i backend czytają ten plik, więc schemat jest sztywny i bez NaN.
    Wejście → wyjście: DataFrame (date, tiles, h_t, h_method, h_source, h_sigma, h_datum, area_km2,
      lake_nodata_pct, otsu_threshold, local_cloud_pct, qc_ok, qc_reason) -> plik JSON.
    Jak to obronić: test sprawdza dokładny zbiór kluczy.
    """
    def num(v, nd):
        return None if v is None or pd.isna(v) else round(float(v), nd)

    out = []
    for r in df.sort_values("date").itertuples():
        h = num(r.h_t, 2)
        cap = num(level_to_capacity(r.h_t), 2) if h is not None else None
        out.append({"date": str(r.date), "tiles": r.tiles, "h_t": h, "h_method": r.h_method,
                    "h_source": r.h_source, "h_sigma": num(r.h_sigma, 2),
                    "h_datum": None if h is None else r.h_datum, "area_km2": num(r.area_km2, 3),
                    "lake_nodata_pct": num(r.lake_nodata_pct, 3), "otsu_threshold": num(r.otsu_threshold, 3),
                    "local_cloud_pct": num(r.local_cloud_pct, 3), "capacity_mln_m3": cap,
                    "qc_ok": bool(r.qc_ok), "qc_reason": r.qc_reason})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
