"""Najnowszy komunikat Wód Polskich (RZGW) o pojemności zbiornika Nysa - stan „na dziś” dla przycisku w aplikacji.

Co robi: `BulletinService.get()` zwraca najnowszy czytelny komunikat z listy gov.pl (przez
  `mielizna.bulletins.latest_govpl`) albo, gdy sieć zawiedzie, ostatni dobry wynik z cache albo ostatni
  wiersz `processed/bulletins.csv` z pipeline'u. Wynik sieci jest zapisywany w `cache_dir`
  (`bulletin_latest.json`, atomowo: tmp + replace), razem z czasem ostatniej próby.
Dlaczego tak: serwer Wód Polskich nie może dostawać zapytań przy każdym kliknięciu, więc sieć jest
  pytana najwyżej raz na `ttl_s` (1 h) - także po porażce (inaczej awaria serwera zamieniłaby się w serię
  zapytań). Odświeżenie nigdy nie działa na wątku żądania: żądanie, które wygra jednorazową blokadę
  (`_refresh_lock`, bez czekania), uruchamia wątek-demon (single-flight) i od razu zwraca bieżący stan
  (ostatni dobry z `stale`, inaczej CSV, inaczej 404) z `refreshing=true`; nikt nie zajmuje puli wątków
  współdzielonej z /api/zones ani nie przekracza 60 s nginx. Wątek ma budżet `DEADLINE_S` = 40 s
  (sprawdzany też w trakcie strumieniowania; parsowanie PDF-a jest ograniczone tylko limitem rozmiaru,
  ale działa w tle). UX: pierwsze kliknięcie może pokazać wynik zapasowy z adnotacją „trwa pobieranie”,
  kolejne kliknięcie (po kilku sekundach) dostaje świeży komunikat. Dane z sieci są zdalnym wejściem: pobierania mają limity
  rozmiaru (lista 2 MB, PDF 10 MB) i krótkie timeouty, URL musi być `https://`, a `pypdf` parsuje
  nieufny PDF (ryzyko zasobowe ograniczone limitem rozmiaru i odpornością na wyjątki).
  Gdy użyto starszego komunikatu niż najnowszy z listy (`fallback_older`), wynik ma `stale=true`.
  Po udanym odświeżeniu w `bulletin_raw/govpl` zostaje 10 najnowszych PDF-ów. Pobranie z sieci tylko przy `live`; bez niego i przy błędzie wynik jest
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
DEADLINE_S = 40.0                    # łączny budżet czasu odświeżenia (lista + PDF-y)
KEEP_PDFS = 10
MAX_V = 200.0                        # jak limit `/api/capacity-to-level`


def default_fetch(cache_dir: Path) -> dict | None:
    """`latest_govpl` z importem w środku (backend nie wymaga pypdf do importu modułu)."""
    from mielizna import bulletins
    return bulletins.latest_govpl(Path(cache_dir) / RAW_SUBDIR, max_age_s=TTL_S, deadline_s=DEADLINE_S)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _valid(row) -> bool:
    try:
        v = float(row["v_current"])
        date.fromisoformat(str(row["bulletin_date"]))
        return (math.isfinite(v) and 0 < v < MAX_V and isinstance(row["url"], str)
                and row["url"].startswith("https://"))
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
                 clock=time.time, ttl_s: float = TTL_S, background: bool = True):
        self.cache_dir, self.data_dir, self.live = Path(cache_dir), Path(data_dir), live
        self.fetch_fn, self.clock, self.ttl_s, self.background = fetch_fn, clock, ttl_s, background
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()            # krótka: stan w pamięci
        self._refresh_lock = threading.Lock()    # długa: tylko jedno odświeżenie naraz, nigdy nie czekamy
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
                              "url": row["url"], "older": bool(row.get("fallback_older"))}
            st["fetched_at"] = now
            self._prune()
        with self._lock:
            self._state = st
            self._write_state()

    def _prune(self) -> None:
        """Zostawia KEEP_PDFS najnowszych PDF-ów w cache (wg czasu modyfikacji)."""
        try:
            pdfs = sorted((self.cache_dir / RAW_SUBDIR / "govpl").glob("*.pdf"), key=lambda p: p.stat().st_mtime)
            for p in pdfs[:-KEEP_PDFS]:
                p.unlink(missing_ok=True)
        except OSError as e:
            log.warning("bulletin prune failed: %s", e)

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

    def _current(self) -> dict | None:
        """Bieżący stan bez sieci: ostatni dobry wynik (live) albo ostatni wiersz CSV."""
        with self._lock:
            st = self._state
            if self.live and st.get("bulletin"):
                b = {k: v for k, v in st["bulletin"].items() if k != "older"}
                return {**b, "fetched_at": _iso(st["fetched_at"] or st["attempt_at"]),
                        "stale": (not st.get("ok", False)) or bool(st["bulletin"].get("older"))
                         or self._refresh_lock.locked(), "source": "govpl"}
        return self._from_csv()

    def _run_refresh(self) -> None:
        """Ciało odświeżenia (wątek tła albo inline w testach); zawsze zwalnia blokadę."""
        try:
            now = self.clock()
            with self._lock:
                still_due = now - self._state.get("attempt_at", -math.inf) >= self.ttl_s
            if still_due:
                self._attempt(now)
        except Exception:  # noqa: BLE001
            log.exception("bulletin refresh failed")
        finally:
            self._refresh_lock.release()

    def join(self, timeout: float | None = None) -> None:
        """Czeka na wątek odświeżenia (testy)."""
        t = self._thread
        if t is not None:
            t.join(timeout)

    def refreshing(self) -> bool:
        return self._refresh_lock.locked()

    def get(self) -> dict | None:
        try:
            with self._lock:
                due = self.live and self.clock() - self._state.get("attempt_at", -math.inf) >= self.ttl_s
            if due and self._refresh_lock.acquire(blocking=False):
                if self.background:
                    self._thread = threading.Thread(target=self._run_refresh, name="bulletin-refresh", daemon=True)
                    self._thread.start()
                else:
                    self._run_refresh()
            return self._current()
        except Exception:  # noqa: BLE001 - ostatnia zapora: nigdy 500
            log.exception("bulletin service failed")
            return None
