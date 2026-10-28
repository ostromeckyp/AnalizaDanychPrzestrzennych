"""Najnowszy komunikat Wód Polskich (RZGW) o pojemności zbiornika Nysa - stan „na dziś” dla przycisku w aplikacji.

Co robi: `BulletinService.get()` zwraca najnowszy czytelny komunikat z listy gov.pl (przez
  `mielizna.bulletins.latest_govpl`) albo, gdy sieć zawiedzie, ostatni dobry wynik z cache albo ostatni
  wiersz `processed/bulletins.csv` z pipeline'u. Wynik sieci jest zapisywany w `cache_dir`
  (`bulletin_latest.json`, atomowo: tmp + replace), razem z czasem ostatniej próby.
Dlaczego tak: serwer Wód Polskich nie może dostawać zapytań przy każdym kliknięciu, więc sieć jest
  pytana najwyżej raz na `ttl_s` (1 h) - także po porażce (inaczej awaria serwera zamieniłaby się w serię
  zapytań). Jedna blokada obejmuje całe odświeżenie, więc równoległe żądania czekają na wynik pierwszego
  zamiast pobierać drugi raz. Pobranie z sieci tylko przy `live`; bez niego i przy błędzie wynik jest
  oznaczony `stale` (i `source="pipeline"` dla CSV). Żaden wyjątek nie wychodzi z `get()` (API nie daje 500).
Wejście → wyjście: `fetch_fn(cache_dir) -> dict | None` (wstrzykiwane, testy bez sieci), `clock()` →
  `get()` = słownik {bulletin_date, reading_utc, v_current, v_npp, url, fetched_at, stale, source} albo None.
Jak to obronić: parsowanie i walidacja daty PDF to kod wariantu B z pipeline'u; rzędna z pojemności
  liczona jest dopiero w endpoincie tabelą KŻ, tą samą co `/api/capacity-to-level`.
"""
import csv
import json
import logging
import math
import os
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

TTL_S = 3600
CACHE_FILE = "bulletin_latest.json"
RAW_SUBDIR = "bulletin_raw"          # lista gov.pl i PDF-y (zapisywalny katalog, nie dane tylko do odczytu)
MAX_V = 200.0                        # jak limit `/api/capacity-to-level`


def default_fetch(cache_dir: Path) -> dict | None:
    """`latest_govpl` z importem w środku (backend nie wymaga pypdf do importu modułu)."""
    from mielizna import bulletins
    return bulletins.latest_govpl(Path(cache_dir) / RAW_SUBDIR, max_age_s=TTL_S)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _valid(row) -> bool:
    try:
        v = float(row["v_current"])
        date.fromisoformat(str(row["bulletin_date"]))
        return math.isfinite(v) and 0 < v < MAX_V and isinstance(row["url"], str)
    except (TypeError, ValueError, KeyError):
        return False


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class BulletinService:
    def __init__(self, cache_dir: Path, data_dir: Path, live: bool, fetch_fn=default_fetch,
                 clock=time.time, ttl_s: float = TTL_S):
        self.cache_dir, self.data_dir, self.live = Path(cache_dir), Path(data_dir), live
        self.fetch_fn, self.clock, self.ttl_s = fetch_fn, clock, ttl_s
        self._lock = threading.Lock()
        self._state = self._read_state()      # {"bulletin", "fetched_at", "attempt_at", "ok"} albo {}

    def _read_state(self) -> dict:
        try:
            st = json.loads((self.cache_dir / CACHE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        ok = isinstance(st, dict) and _valid(st.get("bulletin") or {}) and isinstance(st.get("attempt_at"), (int, float))
        return st if ok else {}

    def _write_state(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self.cache_dir / CACHE_FILE
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(self._state, allow_nan=False), encoding="utf-8")
            os.replace(tmp, path)
        except (OSError, ValueError) as e:       # brak zapisu nie psuje odpowiedzi
            log.warning("bulletin cache write failed: %s", e)

    def _attempt(self, now: float) -> None:
        """Jedna próba pobrania; zawsze zapisuje czas próby (TTL obowiązuje też po porażce)."""
        row, ok = None, False
        try:
            row = self.fetch_fn(self.cache_dir)
            ok = row is not None and _valid(row)
            if row is not None and not ok:
                log.warning("bulletin: odrzucono niepoprawny wynik %r", row)
        except Exception as e:  # noqa: BLE001 - sieć/parsowanie nie może wywrócić API
            log.warning("bulletin fetch failed: %s: %s", type(e).__name__, e)
        st = {"attempt_at": now, "ok": ok, "bulletin": self._state.get("bulletin"),
              "fetched_at": self._state.get("fetched_at")}
        if ok:
            st["bulletin"] = {"bulletin_date": str(row["bulletin_date"]), "v_current": float(row["v_current"]),
                              "v_npp": _num(row.get("v_npp")), "reading_utc": row.get("reading_utc") or None,
                              "url": row["url"]}
            st["fetched_at"] = now
        self._state = st
        self._write_state()

    def _from_csv(self) -> dict | None:
        path = self.data_dir / "processed" / "bulletins.csv"
        try:
            with path.open(encoding="utf-8", newline="") as f:
                rows = [r for r in csv.DictReader(f) if _valid({**r, "url": r.get("url") or ""})]
            if not rows:
                return None
            r = max(rows, key=lambda r: r["bulletin_date"])
            mtime = path.stat().st_mtime
        except (OSError, ValueError, KeyError, csv.Error):
            return None
        return {"bulletin_date": r["bulletin_date"], "reading_utc": (r.get("reading_utc") or "").strip() or None,
                "v_current": float(r["v_current"]), "v_npp": _num(r.get("v_npp")), "url": r["url"],
                "fetched_at": _iso(mtime), "stale": True, "source": "pipeline"}

    def get(self) -> dict | None:
        try:
            with self._lock:
                now = self.clock()
                if self.live and now - self._state.get("attempt_at", -math.inf) >= self.ttl_s:
                    self._attempt(now)
                st = self._state
                if self.live and st.get("bulletin"):
                    return {**st["bulletin"], "fetched_at": _iso(st["fetched_at"] or st["attempt_at"]),
                            "stale": not st.get("ok", False), "source": "govpl"}
            return self._from_csv()
        except Exception:  # noqa: BLE001 - ostatnia zapora: nigdy 500
            log.exception("bulletin service failed")
            return None
