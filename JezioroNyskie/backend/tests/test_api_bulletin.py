"""Testy `/api/bulletin/latest`: najnowszy komunikat Wód Polskich z TTL, blokadą i awaryjnym powrotem do CSV."""
import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

ROW = {"bulletin_date": date(2026, 10, 27), "v_current": 41.5, "v_npp": 65.7, "v_maxpp": 121.7,
       "reading_utc": "06:00", "url": "https://www.gov.pl/attachment/new", "source": "govpl"}
CSV = ("scene_date,bulletin_date,source,v_current,v_npp,v_maxpp,reading_utc,url\n"
       "2026-10-18,2026-10-19,govpl,39.6,65.7,121.7,06:00,https://www.gov.pl/attachment/a\n"
       "2026-10-26,2026-10-26,govpl,41.0,65.7,121.7,,https://www.gov.pl/attachment/b\n")


class Fetch:
    """Zliczające wywołania `latest_govpl` (podmiana sieci)."""

    def __init__(self, result=ROW, exc=None, delay=0.0):
        self.result, self.exc, self.delay, self.calls = result, exc, delay, 0

    def __call__(self, cache_dir):
        self.calls += 1
        time.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def make(dataset, products, tmp_path):
    def _make(fetch, live=True, csv=True, clock=None, cache=None, bg=False):
        if csv:
            (dataset / "processed" / "bulletins.csv").write_text(CSV, encoding="utf-8")
        s = Settings(data_dir=dataset, live=live, current_dir=cache or tmp_path / "cache")
        return TestClient(create_app(s, products, bulletin_fn=fetch, clock=clock or Clock(),
                                      bulletin_background=bg))
    return _make


def test_live_success(make):
    f = Fetch()
    r = make(f).get("/api/bulletin/latest")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    b = r.json()
    assert (b["bulletin_date"], b["reading_utc"], b["v_current"], b["v_npp"]) == ("2026-10-27", "06:00", 41.5, 65.7)
    assert b["source"] == "govpl" and b["stale"] is False and b["in_table"] is True
    assert b["url"] == ROW["url"] and b["fetched_at"]
    c = make(Fetch()).get("/api/capacity-to-level", params={"v": 41.5}).json()
    assert b["h"] == c["h"] and b["h"] is not None


def test_in_table_false_outside_table(make):
    b = make(Fetch(result=ROW | {"v_current": 150.0})).get("/api/bulletin/latest").json()
    assert b["h"] is None and b["in_table"] is False and b["v_current"] == 150.0


def test_ttl_one_hour(make):
    f, clock = Fetch(), Clock()
    c = make(f, clock=clock)
    c.get("/api/bulletin/latest")
    clock.t += 3599
    c.get("/api/bulletin/latest")
    assert f.calls == 1
    clock.t += 2
    c.get("/api/bulletin/latest")
    assert f.calls == 2


def test_concurrent_requests_fetch_once(make):
    f = Fetch(delay=0.3)
    c = make(f)
    out = []
    ts = [threading.Thread(target=lambda: out.append(c.get("/api/bulletin/latest").status_code)) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == [200] * 5 and f.calls == 1


@pytest.mark.parametrize("fetch", [Fetch(exc=RuntimeError("boom")), Fetch(result=None)])
def test_fallback_to_pipeline_csv(make, fetch):
    r = make(fetch).get("/api/bulletin/latest")
    assert r.status_code == 200
    b = r.json()
    assert b["source"] == "pipeline" and b["stale"] is True
    assert (b["bulletin_date"], b["v_current"], b["reading_utc"]) == ("2026-10-26", 41.0, None)
    assert b["url"] == "https://www.gov.pl/attachment/b" and b["h"] is not None


def test_live_off_never_fetches(make):
    f = Fetch()
    b = make(f, live=False).get("/api/bulletin/latest").json()
    assert f.calls == 0 and b["source"] == "pipeline" and b["stale"] is True


def test_nothing_available_is_404_with_detail(make):
    r = make(Fetch(exc=OSError("x")), csv=False).get("/api/bulletin/latest")
    assert r.status_code == 404 and "komunikat" in r.json()["detail"].lower()


def test_failure_after_success_serves_last_good_as_stale(make):
    f, clock = Fetch(), Clock()
    c = make(f, clock=clock)
    c.get("/api/bulletin/latest")
    f.exc = ConnectionError("down")
    clock.t += 3601
    b = c.get("/api/bulletin/latest").json()
    assert f.calls == 2 and b["source"] == "govpl" and b["stale"] is True and b["bulletin_date"] == "2026-10-27"
    clock.t += 10                                   # po porażce też obowiązuje TTL: bez ponownego pytania sieci
    c.get("/api/bulletin/latest")
    assert f.calls == 2


def test_cache_survives_restart_within_ttl(make, tmp_path):
    clock, cache = Clock(), tmp_path / "shared"
    make(Fetch(), clock=clock, cache=cache).get("/api/bulletin/latest")
    f2 = Fetch()
    clock.t += 600
    b = make(f2, clock=clock, cache=cache).get("/api/bulletin/latest").json()
    assert f2.calls == 0 and b["source"] == "govpl" and b["stale"] is False


def test_corrupt_cache_and_bad_value_never_500(make, tmp_path):
    cache = tmp_path / "bad"
    cache.mkdir()
    (cache / "bulletin_latest.json").write_text("{nie json", encoding="utf-8")
    assert make(Fetch(result=ROW | {"v_current": float("nan")}), cache=cache).get("/api/bulletin/latest").status_code == 200


def test_request_never_blocks_on_hanging_fetch(make):
    started, release = threading.Event(), threading.Event()

    def hang(cache_dir):
        started.set()
        release.wait(10)
        return ROW

    c = make(hang, bg=True)
    t0 = time.monotonic()
    r = c.get("/api/bulletin/latest")                  # pierwsze żądanie też wraca natychmiast (CSV)
    assert time.monotonic() - t0 < 0.5 and r.status_code == 200
    assert r.json()["source"] == "pipeline" and r.json()["stale"] is True and r.json()["refreshing"] is True
    assert started.wait(5)
    t0 = time.monotonic()
    r2 = c.get("/api/bulletin/latest")
    assert time.monotonic() - t0 < 0.5 and r2.json()["refreshing"] is True
    release.set()
    c.app.state.bulletin.join(5)
    b = c.get("/api/bulletin/latest").json()           # stan zaktualizowany w tle
    assert b["source"] == "govpl" and b["bulletin_date"] == "2026-10-27"
    assert b["stale"] is False and b["refreshing"] is False


def test_background_refresh_without_csv_serves_last_good_then_updates(make):
    started, release = threading.Event(), threading.Event()
    calls = []

    def fn(cache_dir):
        calls.append(1)
        if len(calls) == 2:
            started.set()
            release.wait(10)
            return ROW | {"bulletin_date": date(2026, 10, 28)}
        return ROW

    clock = Clock()
    c = make(fn, csv=False, clock=clock, bg=True)
    c.get("/api/bulletin/latest")                                # uruchamia odświeżanie w tle
    c.app.state.bulletin.join(5)
    assert c.get("/api/bulletin/latest").json()["bulletin_date"] == "2026-10-27"
    clock.t += 3601
    b = c.get("/api/bulletin/latest").json()           # w trakcie odświeżania: ostatni dobry, stale
    assert started.wait(5)
    assert b["source"] == "govpl" and b["stale"] is True and b["bulletin_date"] == "2026-10-27"
    release.set()
    c.app.state.bulletin.join(5)
    assert c.get("/api/bulletin/latest").json()["bulletin_date"] == "2026-10-28"


def test_background_exception_releases_lock(make):
    c = make(Fetch(exc=RuntimeError("x")), bg=True)
    c.get("/api/bulletin/latest")
    c.app.state.bulletin.join(5)
    assert c.app.state.bulletin.refreshing() is False


def test_older_bulletin_marked_stale(make):
    b = make(Fetch(result=ROW | {"fallback_older": True})).get("/api/bulletin/latest").json()
    assert b["source"] == "govpl" and b["stale"] is True


def test_non_https_url_rejected(make):
    b = make(Fetch(result=ROW | {"url": "http://evil.example/x.pdf"})).get("/api/bulletin/latest").json()
    assert b["source"] == "pipeline"


def test_csv_non_https_rows_ignored(make, dataset):
    c = make(Fetch(exc=OSError("x")))
    (dataset / "processed" / "bulletins.csv").write_text(
        CSV + "2026-10-28,2026-10-28,govpl,42.0,65.7,121.7,06:00,file:///etc/passwd\n", encoding="utf-8")
    assert c.get("/api/bulletin/latest").json()["bulletin_date"] == "2026-10-26"


def test_prunes_old_raw_pdfs_after_success(make, tmp_path):
    cache = tmp_path / "prune"
    raw = cache / "bulletin_raw" / "govpl"
    raw.mkdir(parents=True)
    for i in range(15):
        p = raw / f"{i:02d}.pdf"
        p.write_bytes(b"%PDF")
        import os
        os.utime(p, (1000 + i, 1000 + i))
    make(Fetch(), cache=cache).get("/api/bulletin/latest")
    left = sorted(p.name for p in raw.iterdir())
    assert len(left) == 10 and "14.pdf" in left and "00.pdf" not in left


@pytest.mark.parametrize("url", ["https://evil.example/x.pdf", "https://www.gov.pl.evil.example/x.pdf",
                                 "https://user@www.gov.pl/x.pdf", "https://web.archive.org/web/2020/https://www.gov.pl/a"])
def test_live_url_outside_allow_list_rendered_as_null(make, url):
    b = make(Fetch(result=ROW | {"url": url})).get("/api/bulletin/latest").json()
    assert b["source"] == "govpl" and b["v_current"] == 41.5 and b["url"] is None


def test_csv_url_outside_allow_list_rendered_as_null(make, dataset):
    c = make(Fetch(exc=OSError("x")))
    (dataset / "processed" / "bulletins.csv").write_text(
        CSV + "2026-10-28,2026-10-28,wayback,42.0,65.7,121.7,06:00,https://web.archive.org/web/1/https://www.gov.pl/x\n",
        encoding="utf-8")
    b = c.get("/api/bulletin/latest").json()
    assert b["bulletin_date"] == "2026-10-28" and b["url"] is None


def test_gov_pl_url_kept(make):
    assert make(Fetch()).get("/api/bulletin/latest").json()["url"] == "https://www.gov.pl/attachment/new"


def test_thread_start_failure_releases_refresh_lock(make, monkeypatch):
    from types import SimpleNamespace

    from app import bulletin as bmod

    class NoStart(threading.Thread):
        def start(self):
            raise RuntimeError("can't start new thread")
    c = make(Fetch(), bg=True)
    monkeypatch.setattr(bmod, "threading", SimpleNamespace(Thread=NoStart, Lock=threading.Lock))
    r = c.get("/api/bulletin/latest")
    assert r.status_code == 200 and r.json()["source"] == "pipeline"      # bieżący stan zamiast 404/500
    assert c.app.state.bulletin.refreshing() is False                      # blokada zwolniona: kolejna próba możliwa
