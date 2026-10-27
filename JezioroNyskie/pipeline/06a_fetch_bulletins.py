"""06a - komunikaty o pojemności zbiornika Nysa dla scen użytecznych (wejście wariantu B `h_t`).

Co robi: bierze listę scen z `s2.usable_dates(cfg)`, dla każdej szuka komunikatu RZGW/Wód
  Polskich z tego samego dnia albo ±1 dzień (Wayback 2019-2024 + lista gov.pl od 02.2024),
  zapisuje tabelę pojemności i wypisuje pokrycie (rok, źródło, ten sam dzień vs ±1) oraz
  głębokość listy gov.pl.
Dlaczego tak: scen jest ~220, więc pobieramy tylko potrzebne PDF-y (1 zapytanie/s, cache);
  lista scen pochodzi z jednej wspólnej funkcji (R14), a nie z shorelines.gpkg, którego jeszcze nie ma.
Wejście → wyjście: scenes_candidates.csv, data/raw/check/rzgw_wayback_index.csv, strona gov.pl →
  data/processed/bulletins.csv, data/raw/rzgw/ (cache), data/processed/logs/06a_fetch_bulletins.log.
  Skrypt jest wznawialny: gotowe PDF-y nie są pobierane ponownie.
Jak to obronić: brak komunikatu = brak wiersza, bez interpolacji; zmiana `v_npp` jest wypisywana.
"""
import logging
import sys
from datetime import date

import pandas as pd

from mielizna import bulletins, s2
from mielizna.config import data_path, load_config


def main() -> int:
    log_dir = data_path("processed", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(log_dir / "06a_fetch_bulletins.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    log = logging.getLogger("06a")
    cfg = load_config()
    scenes = [date.fromisoformat(d) for d in s2.usable_dates(cfg)]
    log.info("sceny użyteczne: %d", len(scenes))

    govpl = bulletins.fetch_govpl_list()
    if not govpl:
        log.error("lista gov.pl jest pusta (zmieniony układ strony? usuń data/raw/rzgw/govpl_list.html)")
        return 1
    log.info("lista gov.pl: %d komunikatów z datą, zakres %s .. %s", len(govpl), govpl[0][0], govpl[-1][0])
    wayback = bulletins.wayback_index()
    log.info("indeks Wayback: %d dat, zakres %s .. %s", len(wayback), min(wayback), max(wayback))

    df = bulletins.fetch_for_dates(scenes, wayback=wayback, govpl=govpl)
    df["offset_days"] = [(b - s).days for s, b in zip(df.scene_date, df.bulletin_date)]
    out = data_path("processed", "bulletins.csv")
    df.drop(columns="offset_days").to_csv(out, index=False)
    log.info("zapisano %s (%d wierszy)", out, len(df))

    years = pd.Series([s.year for s in scenes]).value_counts().sort_index()
    got = df.groupby(pd.to_datetime(df.scene_date).dt.year).size()
    log.info("pokrycie: %d / %d scen", len(df), len(scenes))
    for y, n in years.items():
        log.info("  %d: %d / %d", y, got.get(y, 0), n)
    log.info("źródło: %s", df.source.value_counts().to_dict())
    log.info("ten sam dzień: %d, ±1: %d", (df.offset_days == 0).sum(), (df.offset_days != 0).sum())
    log.info("godzina odczytu (UTC): %s", df.reading_utc.fillna("brak").value_counts().sort_index().to_dict())
    log.info("v_npp (grupy po zaokrągleniu do 0,1): %s", df.assign(v_npp=df.v_npp.round(1)).groupby("v_npp").scene_date.agg(["min", "max", "count"]).to_dict("index"))
    log.info("v_maxpp: %s", df.v_maxpp.round(2).value_counts().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
