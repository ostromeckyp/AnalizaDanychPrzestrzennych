"""Model dna: przedziały zalania [z_min, z_max] każdego piksela z serii scen Sentinel-2.

Metoda w skrócie (linia wodna): każda scena mówi, czy piksel był wodą czy lądem przy znanym poziomie
jeziora h_t. Jeśli piksel był wodą przy poziomie h, to dno leży poniżej h; jeśli był lądem, to dno leży
powyżej h. Zbierając wiele scen o różnych poziomach dostajemy dla piksela dwie liczby:
  z_max = najniższy poziom, przy którym piksel jeszcze widziano jako wodę (dno jest co najwyżej tak wysoko),
  z_min = najwyższy poziom, przy którym piksel widziano jako ląd (dno jest co najmniej tak wysoko).
Klasyfikacja bywa błędna, więc obserwacje się czasem wykluczają (woda na poziomie niższym niż ląd);
wtedy wybieramy próg dna, który tłumaczy jak najwięcej scen (najmniej błędów).
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import rasterio.shutil

from mielizna.grid import Grid
from mielizna.levels import EXTRAP_TOKEN

FLAG_ALWAYS_WATER = 1
FLAG_ALWAYS_LAND = 2
FLAG_CONFLICT = 4
FLAG_C_WATER_IGNORED = 8
FLAG_UNRESOLVED = 16
FLAG_OUTSIDE = 255

FLAG_MEANING = {
    "1": "ALWAYS_WATER: brak spójnego lądu, z_min=NaN (=-inf), z_max skończone",
    "2": "ALWAYS_LAND: brak spójnej wody, z_max=NaN (=+inf), z_min skończone",
    "4": "CONFLICT: n_conflict > 0 (część scen sprzeczna z progiem dna)",
    "8": "C_WATER_IGNORED: piksel miał obserwacje wody ze scen wariantu C, które pominięto (R24: woda C = nieznane)",
    "16": ("UNRESOLVED: obserwowany, ale obie granice puste: remis przy równych poziomach ALBO obserwacje sprzeczne "
           "na różnych poziomach (np. woda przy 193 m i ląd przy 197 m: CONFLICT+UNRESOLVED, obie granice NaN)"),
    "255": "poza obszarem modelu (AOI)",
}
NAN_SEMANTICS = ("W obszarze modelu (obs_count > 0): NaN w z_min znaczy -inf (brak dolnego ograniczenia dna), "
                 "NaN w z_max znaczy +inf (piksel nigdy nie był spójnie wodą). obs_count == 0 lub flags == 255 "
                 "znaczy: poza obszarem modelu.")
EVIDENCE = "rf_and_otsu_water; land = rf0 or otsu0; 255 in either = unknown"
ZMAX_RULE = "R24: water observations of C scenes are unknown (255) for threshold and z_max; C land kept; flag 8 = C water ignored"
NODATA_U16 = 65535
_MAX_STRIP_ELEMENTS = 8_000_000


def combine_evidence(rf: np.ndarray, otsu: np.ndarray) -> np.ndarray:
    """Łączy maski RF i Otsu jednej sceny w jedną obserwację {1 woda, 0 ląd, 255 nieznane}.

    Co robi: woda tylko tam, gdzie RF i Otsu obie mówią „woda"; ląd wszędzie indziej, gdzie obie znają
      klasę (wystarczy, że jedna z nich mówi „ląd"); 255 w którejkolwiek masce daje 255.
    Dlaczego tak: decyzja U1 (ostrożniej). RF bywa fałszywie „woda" na jasnym mule przy brzegu, co
      zaniżałoby z_max (niebezpieczny kierunek). Wymóg zgody obu metod usuwa ten błąd; ląd z jednej
      metody dokłada obserwacji lądu, które tylko podnoszą próg dna (dowód: dodanie lądu nie zmniejsza
      z_max). Pod chmurą lądu nie zmyślamy - tam zostaje 255.
    Wejście → wyjście: dwie tablice uint8 {0,1,255} dowolnego kształtu → uint8 tego samego kształtu.
      Uwaga (R24): wodę ze scen wariantu C zamienia na 255 dopiero `compute_bounds` (ma is_c), nie ta funkcja.
    Jak to obronić: RF∧Otsu ma na etykietach ręcznych recall lądu 47/50 wobec 36/50 samego RF; koszt
      to niższy recall wody (0.61), czyli konserwatywne, nie niebezpieczne przesunięcie granic.
    """
    rf = np.asarray(rf)
    otsu = np.asarray(otsu)
    out = np.zeros(rf.shape, np.uint8)
    out[(rf == 1) & (otsu == 1)] = 1
    out[(rf == 255) | (otsu == 255)] = 255
    return out


def select_scenes(scenes: list[dict], start: str, end: str) -> pd.DataFrame:
    """Wybiera sceny wchodzące do modelu w okresie [start, end] (włącznie, daty ISO).

    Co robi: bierze sceny z qc_ok == True, skończonym h_t i datą w okresie; sortuje po dacie.
    Dlaczego tak: kontrakt T8/T10 - sceny odrzucone przez QC albo bez poziomu nie mogą dawać obserwacji
      (ich maski nie są otwierane). Okres daje wersje modelu: all / pre_flood / post_flood.
    Wejście → wyjście: lista słowników z scenes.json → DataFrame date, h_t, h_sigma, h_method,
      extrapolated (z h_source, znacznik `levels.EXTRAP_TOKEN`), h_source. Brak h_sigma → ValueError.
    Jak to obronić: filtr jest jawny i testowany; nic nie jest po cichu pomijane, a brak niepewności
      poziomu (która poszerza przedział) jest błędem, nie zerem. `extrapolated` pochodzi z tekstu
      h_source (scenes.json nie ma osobnego pola), ale znacznik jest stałą wspólną z levels.py.
    """
    rows = []
    for s in scenes:
        h = s.get("h_t")
        if s.get("qc_ok") is not True or h is None or not np.isfinite(h):
            continue
        if not (start <= s["date"] <= end):
            continue
        sig = s.get("h_sigma")
        if sig is None or not np.isfinite(sig):
            raise ValueError(f"scena {s['date']}: brak h_sigma (niepewność poziomu jest wymagana)")
        rows.append({"date": s["date"], "h_t": float(h), "h_sigma": float(sig),
                     "h_method": s.get("h_method"),
                     "extrapolated": EXTRAP_TOKEN.strip(", ") in str(s.get("h_source") or ""),
                     "h_source": s.get("h_source") or ""})
    cols = ["date", "h_t", "h_sigma", "h_method", "extrapolated", "h_source"]
    return pd.DataFrame(rows, columns=cols).sort_values("date").reset_index(drop=True)


def _bounds_strip(m: np.ndarray, h: np.ndarray, sg: np.ndarray, isc: np.ndarray, k_sigma: float) -> dict:
    """Przedziały dla paska wierszy; sceny już posortowane po h (patrz `compute_bounds`)."""
    c_water = (m == 1) & isc[:, None, None]       # R24: woda ze sceny C = nieznane
    water = (m == 1) & ~isc[:, None, None]
    land = m == 0
    lev = np.unique(h, return_inverse=True)[1]
    U = int(lev[-1]) + 1
    starts = np.r_[0, np.flatnonzero(np.diff(lev)) + 1]
    # liczba obserwacji wody/lądu na każdym unikalnym poziomie -> sumy skumulowane po poziomach
    Wj = np.add.reduceat(water, starts, axis=0, dtype=np.int16)
    Lj = np.add.reduceat(land, starts, axis=0, dtype=np.int16)
    zeros = np.zeros((1,) + Wj.shape[1:], np.int16)
    cumW = np.concatenate([zeros, np.cumsum(Wj, axis=0, dtype=np.int16)])
    cumL = np.concatenate([zeros, np.cumsum(Lj, axis=0, dtype=np.int16)])
    errors = cumW + (cumL[-1] - cumL)            # próg k: woda poniżej k + ląd od k wzwyż
    n_conf = errors.min(axis=0)
    is_min = errors == n_conf
    k_min = is_min.argmax(axis=0)
    k_max = U - is_min[::-1].argmax(axis=0)
    levc = lev[:, None, None]
    c_land = land & (levc < k_min)               # ląd spójny z każdym minimalnym progiem
    cons_water = water & (levc >= k_max)          # woda spójna z każdym minimalnym progiem
    hh = h[:, None, None]
    ss = k_sigma * sg[:, None, None]
    nan = np.nan

    def reduce(sel, val, fn):
        out = fn(np.where(sel, val, np.inf if fn is np.min else -np.inf), axis=0)
        return np.where(np.isfinite(out), out, nan)

    z_min_raw = reduce(c_land, hh, np.max)
    z_min = reduce(c_land, hh - ss, np.max)
    z_max_raw = reduce(cons_water, hh, np.min)
    z_max = reduce(cons_water, hh + ss, np.min)
    obs = (m != 255).sum(axis=0)                  # ważne obserwacje, także pominięta woda C
    c_ignored = c_water.any(axis=0)
    fin_min, fin_max = np.isfinite(z_min_raw), np.isfinite(z_max_raw)
    both = fin_min & fin_max
    flags = np.zeros(obs.shape, np.uint8)
    flags[(obs > 0) & ~fin_min & fin_max] |= FLAG_ALWAYS_WATER
    flags[(obs > 0) & fin_min & ~fin_max] |= FLAG_ALWAYS_LAND
    flags[n_conf > 0] |= FLAG_CONFLICT
    flags[c_ignored] |= FLAG_C_WATER_IGNORED
    flags[(obs > 0) & ~fin_min & ~fin_max] |= FLAG_UNRESOLVED
    return {"z_min": z_min, "z_max": z_max, "z_min_raw": z_min_raw, "z_max_raw": z_max_raw,
            "z": np.where(both, (z_min_raw + z_max_raw) / 2, nan),
            "unc": np.where(both, (z_max - z_min) / 2, nan),
            "obs_count": obs.astype(np.int32), "n_conflict": n_conf.astype(np.int32), "flags": flags}


def compute_bounds(masks: np.ndarray, h: np.ndarray, h_sigma: np.ndarray, is_c: np.ndarray | None = None,
                   k_sigma: float = 1.0, strip_rows: int | None = None) -> dict[str, np.ndarray]:
    """Przedział zalania [z_min, z_max] dla każdego piksela (wektorowo po całej siatce).

    Co robi: dla każdego piksela układa obserwacje (poziom h_t, woda/ląd; 255 pomijamy) wg poziomu i
      szuka progu dna θ między kolejnymi RÓŻNYMI poziomami. Próg θ „tłumaczy" obserwacje: woda poniżej
      θ i ląd powyżej θ są zgodne; reszta to błędy. Wybieramy próg o najmniejszej liczbie błędów
      (n_conflict = ta liczba). Gdy kilka progów ma ten sam minimalny błąd, bierzemy OBWIEDNIĘ wszystkich
      (od najniższego do najwyższego minimalizatora). Z_max = najniższy poziom wody spójnej z progiem,
      z_min = najwyższy poziom lądu spójnego z progiem; obie granice poszerzamy o k_sigma·σ sceny.
      Dwie sceny o tym samym h nie mają progu między sobą (remis → UNRESOLVED, flaga 16). Flaga 16
      oznacza też obserwacje sprzeczne na RÓŻNYCH poziomach: woda przy 193 m i ląd przy 197 m dają
      CONFLICT+UNRESOLVED, obie granice NaN (żaden próg nie jest spójny z którąkolwiek obserwacją).
      Reguła C (R24): obserwacje WODY ze scen wariantu C (is_c) traktujemy jak 255 (nieznane) i w progu,
      i w z_max; obserwacje LĄDU z C zostają. Flaga 8 = piksel miał wodę z C, którą pominięto.
    Dlaczego tak: (1) najmniej błędów jest odporne na pojedyncze pomyłki klasyfikatora, a liczy się
      zwykłe zliczanie (bez wag 1/σ², bo błąd klasyfikacji nie zależy od σ poziomu). (2) Obwiednia przy
      remisie jest ostrożna: lądu uznajemy mniej (tylko poniżej każdego minimalnego progu), wody też mniej
      (tylko powyżej każdego), więc przedział się poszerza, nigdy nie zawęża. (3) Poziom C (krzywa
      powierzchnia-rzędna) ma błędy skorelowane w obrębie roku i w paśmie 195-198 m jest zaniżony o
      0.1-0.4 m, więc scena C zawyża, że woda była już przy niższym h: to niebezpieczny kierunek (z_max
      za nisko = strefa „bezpieczna" tam, gdzie jeszcze nie jest). Dowód R24, że pominięcie wody C jest
      zachowawcze: usunięcie obserwacji wody usuwa z errors(k) składnik [woda poniżej progu k], który
      nie maleje ze wzrostem k; więc największy minimalizator k_max może tylko wzrosnąć, zbiór wody
      spójnej (poziom ≥ k_max) tylko się kurczy, a minimum po mniejszym zbiorze nie może spaść: z_max
      tylko rośnie lub staje się NaN (=+∞). Dowód nie zakłada nic o σ_C vs σ_nonC. Dane z recenzji:
      stara reguła („C nie wyznacza z_max, o ile jest woda nie-C") zmieniała tylko 67 px, a C nadal
      obniżało z_max o ponad 5 cm na 38.6% pikseli przedziałowych w paśmie 195-196 m (p1 −0.63 m).
      Koszt, jeśli się mylimy: piksele, gdzie wodę widziały tylko sceny C z lat 2017-19, tracą górną
      granicę i są pokazywane jako niebezpieczne (konserwatywnie). (4) Poszerzenie: każda obserwacja
      wody sama jest ważną górną granicą h+σ, więc bierzemy minimum z h+σ, a nie σ sceny, która
      akurat ma najniższe h.
    Wejście → wyjście: masks uint8 (T,H,W) {0,1,255} (wynik `combine_evidence`), h i h_sigma (T,), is_c
      bool (T,) lub None; kolejność scen dowolna. Zwraca słownik tablic (H,W), liczby zmiennoprzecinkowe
      jako float64: z_min, z_max (poszerzone), z_min_raw, z_max_raw, z (środek surowych granic), unc
      (połowa szerokości poszerzonego przedziału), obs_count (ważne obserwacje, także pominięta woda C),
      n_conflict, flags. NaN: brak spójnego lądu → z_min = NaN (−∞), brak spójnej wody → z_max = NaN (+∞).
      Niezmiennik: z_min ≤ z_min_raw < z_max_raw ≤ z_max, więc z_min > z_max nie może zajść;
      sprzeczność obserwacji mierzy n_conflict.
    Jak to obronić: przypadki brzegowe pokrywa test porównujący z pętlą po pikselach; testy własności na
      losowych danych (σ_C ≥ σ_nonC): dodanie wody C nie zmienia z_max, dodanie lądu go nie obniża.
      Wyłączenie reguły C: is_c=None.
    """
    masks = np.asarray(masks)
    h = np.asarray(h, float)
    sg = np.asarray(h_sigma, float)
    T = masks.shape[0]
    isc = np.zeros(T, bool) if is_c is None else np.asarray(is_c, bool)
    if not (h.shape == sg.shape == isc.shape == (T,)):
        raise ValueError("h, h_sigma i is_c muszą mieć długość równą liczbie scen")
    if T == 0:
        raise ValueError("brak scen")
    if T > 32000:
        raise ValueError("za dużo scen dla liczników int16")
    order = np.argsort(h, kind="stable")
    m, hs, ss, cs = masks[order], h[order], sg[order], isc[order]
    Hh, Ww = m.shape[1:]
    rows = strip_rows or max(1, _MAX_STRIP_ELEMENTS // max(1, T * Ww))
    parts = [_bounds_strip(m[:, r:r + rows], hs, ss, cs, k_sigma) for r in range(0, Hh, rows)]
    return {k: np.concatenate([p[k] for p in parts], axis=0) for k in parts[0]}


def model_version(scenes_bytes: bytes, dates: list[str]) -> str:
    """Skrót wersji modelu: sha256 z scenes.json i nazw plików masek wybranych dat (12 znaków).

    Co robi: skleja bajty scenes.json z posortowaną listą nazw `masks/{d}.tif` i `masks_otsu/{d}.tif`
      i bierze 12 pierwszych znaków sha256.
    Dlaczego tak: wersja ma się zmieniać, gdy zmienia się zestaw scen, ich poziomy (scenes.json) albo
      maski; backend używa jej do unieważniania cache. Nazwy zamiast zawartości masek: tanio, a zmiana
      masek zmienia model klasyfikatora (rf_model_sha w meta).
    Wejście → wyjście: bajty scenes.json, lista dat ISO → ciąg 12 znaków hex (nie zależy od kolejności dat).
    Jak to obronić: test sprawdza determinizm i wrażliwość na oba wejścia.
    """
    names = sorted([f"masks/{d}.tif" for d in dates] + [f"masks_otsu/{d}.tif" for d in dates])
    return hashlib.sha256(scenes_bytes + "\n".join(names).encode()).hexdigest()[:12]


_RASTERS = {  # klucz wyniku -> (plik, dtype, nodata poza AOI)
    "z_min": ("bottom_zmin", "float32", np.nan), "z_max": ("bottom_zmax", "float32", np.nan),
    "z": ("bottom_z", "float32", np.nan), "unc": ("bottom_unc", "float32", np.nan),
    "obs_count": ("obs_count", "uint16", NODATA_U16), "n_conflict": ("conflict_count", "uint16", NODATA_U16),
    "flags": ("bottom_flags", "uint8", FLAG_OUTSIDE),
}


def _write_cog(path: Path, arr: np.ndarray, grid: Grid, nodata) -> None:
    tmp = path.with_name(path.stem + ".tmp.tif")
    with rasterio.open(tmp, "w", driver="GTiff", width=grid.width, height=grid.height, count=1,
                       dtype=arr.dtype, crs=grid.crs, transform=grid.transform, nodata=nodata) as ds:
        ds.write(arr, 1)
    rasterio.shutil.copy(tmp, path, driver="COG", compress="deflate")
    tmp.unlink()


def write_model(result: dict, grid: Grid, out_dir: Path, meta: dict, aoi: np.ndarray) -> None:
    """Zapisuje rastery modelu (COG, EPSG:2180) i model_meta.json do `out_dir`.

    Co robi: float32 z NaN (z_min, z_max - poszerzone o σ, z, unc), uint16 (obs_count, conflict_count) i
      uint8 (bottom_flags); poza AOI wszędzie wartość nodata (NaN / 65535 / 255).
    Dlaczego tak: backend stosuje regułę stref wprost na rastrach, więc granice są już poszerzone, a
      znaczenie NaN opisuje `model_meta.json["nan_semantics"]`.
    Wejście → wyjście: wynik `compute_bounds`, siatka, katalog, słownik meta, maska AOI → pliki.
    Jak to obronić: test round-trip sprawdza typy, nodata poza AOI i NaN po odczycie.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, (name, dtype, nodata) in _RASTERS.items():
        arr = np.asarray(result[key])
        if dtype == "float32":
            arr = arr.astype(np.float32)
            arr[~aoi] = np.nan
        else:
            arr = np.clip(arr, 0, nodata if dtype == "uint16" else 254).astype(dtype)
            arr[~aoi] = nodata
        _write_cog(out_dir / f"{name}.tif", arr, grid, nodata)
    (out_dir / "model_meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")


def read_model(model_dir: Path) -> tuple[dict[str, np.ndarray], dict]:
    """Czyta model z dysku: tablice rastrów i model_meta.json.

    Co robi: otwiera 7 rastrów z `model_dir` i wczytuje metadane.
    Dlaczego tak: backend (strefy §6.4) ma jedno miejsce czytania modelu, zgodne z `write_model`.
    Wejście → wyjście: katalog modelu → (słownik tablic (H,W), meta). Klucze: z_min, z_max, z, unc
      (float32, NaN zachowane), obs_count i n_conflict (uint16, nodata 65535 poza AOI), flags (uint8,
      nodata 255 poza AOI). Nodata NIE jest podmieniane na NaN: backend sam maskuje piksele
      `obs_count == 0 | flags == 255` jako „poza modelem". Reguła dla backendu wewnątrz modelu:
      NaN w z_min → −inf, NaN w z_max → +inf, np.where(isnan(z_min), -np.inf, z_min) itd. (patrz
      meta["nan_semantics"]); dopiero po tej zamianie liczy się D_lo = h − z_max, D_hi = h − z_min.
    Jak to obronić: test round-trip sprawdza typy, nodata i zachowanie NaN.
    """
    model_dir = Path(model_dir)
    arrays = {}
    for key, (name, _, _) in _RASTERS.items():
        with rasterio.open(model_dir / f"{name}.tif") as ds:
            arrays[key] = ds.read(1)
    meta = json.loads((model_dir / "model_meta.json").read_text(encoding="utf-8"))
    return arrays, meta


def build_meta(period: str, span: tuple[str, str], sel: pd.DataFrame, result: dict, aoi: np.ndarray,
               version: str, k_sigma: float, rf_model_sha: str, water_threshold: float | None) -> dict:
    """Buduje słownik metadanych `model_meta.json` jednego okresu.

    Co robi: zbiera opis okresu i scen (liczba, metody, udział ekstrapolowanych C, zakres poziomów),
      opis metody (dowody, reguła C/R24, flagi, semantyka NaN, k_sigma, sha klasyfikatora, próg wody)
      oraz liczniki pikseli w AOI (obserwowane, przedział, zawsze woda/ląd, UNRESOLVED, woda C
      pominięta, sprzeczne).
    Dlaczego tak: model musi się sam opisywać (spec §6a, obrona): backend i raport czytają stąd, jak
      interpretować NaN i flagi i z jakich scen powstał.
    Wejście → wyjście: okres, [start, koniec], DataFrame scen z `select_scenes`, wynik `compute_bounds`,
      maska AOI, wersja, k_sigma, rf_model_sha, próg wody lub None → słownik gotowy do JSON.
    Jak to obronić: liczniki wynikają wprost z rastrów zapisanych obok; `created_at` to jedyne pole
      niedeterministyczne (UTC).
    """
    obs = result["obs_count"]
    fl = result["flags"]
    inside = aoi
    c = sel[sel.h_method == "C"]
    meta = {
        "period": period, "period_dates": list(span), "n_scenes": int(len(sel)),
        "n_scenes_by_method": {k: int(v) for k, v in sel.h_method.value_counts().items()},
        "share_c_extrapolated": float(c.extrapolated.mean()) if len(c) else 0.0,
        "h_min_obs": float(sel.h_t.min()), "h_max_obs": float(sel.h_t.max()),
        "n_conflict_px": int(((result["n_conflict"] > 0) & inside).sum()),
        "bounds_include_h_sigma": True, "k_sigma": k_sigma, "evidence": EVIDENCE, "zmax_rule": ZMAX_RULE,
        "flags": FLAG_MEANING, "nan_semantics": NAN_SEMANTICS, "rf_model_sha": rf_model_sha,
        "counts": {
            "aoi_px": int(inside.sum()), "observed_px": int(((obs > 0) & inside).sum()),
            "interval_px": int((np.isfinite(result["z_min"]) & np.isfinite(result["z_max"]) & inside).sum()),
            "always_water_px": int(((fl & FLAG_ALWAYS_WATER > 0) & inside).sum()),
            "always_land_px": int(((fl & FLAG_ALWAYS_LAND > 0) & inside).sum()),
            "unresolved_px": int(((fl & FLAG_UNRESOLVED > 0) & inside).sum()),
            "c_water_ignored_px": int(((fl & FLAG_C_WATER_IGNORED > 0) & inside).sum()),
            "conflict_px": int(((result["n_conflict"] > 0) & inside).sum()),
        },
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "version": version,
    }
    if water_threshold is not None:
        meta["water_threshold"] = float(water_threshold)
    return meta
