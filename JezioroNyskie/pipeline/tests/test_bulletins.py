"""Testy komunikatów RZGW / Wód Polskich (wariant B h_t): parsery, lista gov.pl, wybór dnia."""
from datetime import date
from pathlib import Path

import pytest

import logging

from mielizna import bulletins
from mielizna.bulletins import (choose_bulletin, fetch_for_dates, list_govpl, parse_govpl_text,
                                parse_pl_number, parse_rzgw_text, pick_reading, reading_utc,
                                text_date, wayback_index)

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_pl_number():
    assert parse_pl_number("32,668") == 32.668 and parse_pl_number("1 234,5") == 1234.5


def test_parse_rzgw_row():  # fixture: prawdziwy wycinek PDF z 27.12.2021
    r = parse_rzgw_text(read("rzgw_row.txt"))
    assert r == {"v_current": 32.668, "v_npp": 66.3, "v_maxpp": 122.1}


def test_rzgw_does_not_match_otmuchow_or_slup():
    assert parse_rzgw_text("Otmuchów \nNysa Kłodzka  7,00 11,87 26,037 59,0 129,5") is None
    assert parse_rzgw_text("Słup \nNysa Szalona  0,58 0,87 15,914 23,6 38,1") is None


def test_rzgw_does_not_match_nysa_kłodzka_header_line():
    # linia „Nysa Kłodzka” (rzeka) bez osobnej linii „Nysa” nie jest zbiornikiem
    assert parse_rzgw_text("Topola \nNysa Kłodzka  10,00 7,20 16,073 16,5 21,7") is None


@pytest.mark.parametrize("name, expected", [
    ("govpl_2026-10-22.txt", {"v_current": 40.2, "v_npp": 65.7, "v_maxpp": 121.7}),
    ("govpl_2024-03-12.txt", {"v_current": 61.23, "v_npp": 65.7, "v_maxpp": 121.7}),
    ("govpl_2024-09-29_short.txt", {"v_current": 55.71, "v_npp": 65.69, "v_maxpp": 121.7}),
])
def test_parse_govpl_row(name, expected):
    # wiersz 43 „Nysa”; nie wolno pomylić z 42 „Otmuchów (Nysa Kłodzka)” ani 46 „Słup (Nysa Szalona)”
    assert parse_govpl_text(read(name)) == expected


def test_govpl_missing_or_nodata_row_is_none():
    assert parse_govpl_text("42 Otmuchów  (Nysa Kłodzka) 5,0 6,4 34,0 58,4 129,2") is None
    assert parse_govpl_text("43 Nysa  (Nysa Kłodzka) b.d. b.d. b.d. 65,7 121,7 56,0 b.d. b.d.") is None


def test_list_govpl_nonempty():
    items = list_govpl(read("govpl_list.html"))
    dates = [d for d, _ in items]
    # raport lodowy i tytuł z literówką „21.102.2024” odpadają, duplikat załącznika 30.04.2025 scalony
    assert dates == [date(2024, 3, 1), date(2024, 3, 12), date(2024, 9, 29), date(2025, 4, 30),
                     date(2026, 10, 22), date(2026, 10, 26)]
    assert all(u.startswith("https://www.gov.pl/attachment/") for _, u in items)


def test_wayback_index_dates_and_variants(tmp_path):
    csv = tmp_path / "idx.csv"
    csv.write_text(
        "timestamp,original,status,mime\n"
        "20201026071531,https://x/Raporty/2020-04/Komunikat_o_sytuacji_w_regionie_z_dn_1-04-2020.pdf,200,application/pdf\n"
        "20201028201621,https://x/Raporty/2022-08/Komunikat_o_sytuacji_w_regionie_z_dn_24-08-2022_1.pdf,200,application/pdf\n"
        "20201028201308,https://x/Raporty/2021-05/Informacja_%C5%BBeglugowa_w_dn_31-05-2021_1.pdf,200,application/pdf\n",
        encoding="utf-8")
    idx = wayback_index(csv)
    assert sorted(idx) == [date(2020, 4, 1), date(2022, 8, 24)]   # żeglugowa pominięta
    assert idx[date(2020, 4, 1)][0][0] == "20201026071531"


def test_same_day_preferred_over_neighbour():
    pick = choose_bulletin(date(2021, 5, 10), {date(2021, 5, 9): "a", date(2021, 5, 10): "b"})
    assert pick == date(2021, 5, 10)


def test_neighbour_tie_prefers_earlier_and_none_when_far():
    both = {date(2021, 5, 9): "a", date(2021, 5, 11): "b"}
    assert choose_bulletin(date(2021, 5, 10), both) == date(2021, 5, 9)
    assert choose_bulletin(date(2021, 5, 10), {date(2021, 5, 11): "b"}) == date(2021, 5, 11)
    assert choose_bulletin(date(2021, 5, 10), {date(2021, 5, 12): "b"}) is None
    assert choose_bulletin(date(2021, 5, 10), {}) is None


def test_reading_utc_formats():
    d = date(2024, 9, 18)
    assert reading_utc("... na godzinę 6:00 UTC (8:00 CEST). ", d) == "06:00"
    assert reading_utc("Sytuacja na dzień 20.03.2025 r. na godz. 600 (UTC)  \nZbiorniki", d) == "06:00"
    assert reading_utc("Sytuacja na dzień 11.09.2025 r. na godz. 1200 (UTC)", d) == "12:00"
    assert reading_utc("z dnia 18 września 2024 r. na godzinę 16:00 (14:00 UTC) ", d) == "14:00"
    assert reading_utc("brak godziny", d) is None


def test_reading_utc_local_only_converted_from_warsaw():
    assert reading_utc("z dnia 21 września 2024 r. na godzinę 16:00 ", date(2024, 9, 21)) == "14:00"  # CEST
    assert reading_utc("z dnia 5 grudnia 2021 r. na godzinę 8:00 ", date(2021, 12, 5)) == "07:00"    # CET


def _row(hour, v):
    return {"v_current": v, "reading_utc": hour, "source": "govpl", "url": f"u{hour}"}


def test_pick_reading_nearest_overpass():
    assert pick_reading([_row("06:00", 1.0), _row("12:00", 2.0)])["v_current"] == 2.0
    assert pick_reading([_row("12:00", 2.0), _row("06:00", 1.0)])["v_current"] == 2.0
    assert pick_reading([_row("08:00", 1.0), _row("12:00", 2.0)])["v_current"] == 1.0  # tie 2h/2h -> earlier


def test_pick_reading_unparseable_never_preferred():
    assert pick_reading([_row(None, 9.0), _row("06:00", 1.0)])["v_current"] == 1.0
    assert pick_reading([_row("06:00", 1.0), _row(None, 9.0)])["v_current"] == 1.0
    assert pick_reading([_row(None, 9.0)])["v_current"] == 9.0


def test_fetch_for_dates_same_day_picks_12_utc(monkeypatch):
    rows = {"a": _row("06:00", 1.0), "b": _row("12:00", 2.0)}
    monkeypatch.setattr(bulletins, "_load", lambda d, e, c: rows[e["file"]] | {"source": e["source"]})
    govpl = [(date(2024, 9, 18), "https://www.gov.pl/attachment/a"), ]
    cand = {date(2024, 9, 18): [{"source": "govpl", "url": "ua", "file": "a"},
                                {"source": "govpl", "url": "ub", "file": "b"}]}
    monkeypatch.setattr(bulletins, "_candidates", lambda w, g: cand)
    df = fetch_for_dates([date(2024, 9, 18)], wayback={}, govpl=govpl, cache_dir=Path("."))
    assert df.v_current.tolist() == [2.0] and df.reading_utc.tolist() == ["12:00"]


def test_text_date_missing_space_before_year():
    assert text_date("z dnia 4 października2021 r.") == date(2021, 10, 4)
    assert text_date("z dnia 27 grudnia 2021 r.") == date(2021, 12, 27)


def test_load_warns_when_pdf_has_no_date(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(bulletins, "_download", lambda url, dest: True)
    monkeypatch.setattr(bulletins, "_pdf_text", lambda p: read("govpl_2024-03-12.txt"))
    with caplog.at_level(logging.WARNING, logger="bulletins"):
        row = bulletins._load(date(2024, 3, 12), {"source": "govpl", "url": "u", "file": "x.pdf"}, tmp_path)
    assert row is not None and any("brak daty" in r.message for r in caplog.records)


def test_list_govpl_recovers_typo_year():
    html = ('<a href="https://www.gov.pl/attachment/11111111-1111-1111-1111-111111111111">'
            'Komunikat z dnia 15.11.20204</a>'
            '<a href="https://www.gov.pl/attachment/22222222-2222-2222-2222-222222222222">'
            'Komunikat z dnia 15.11.20259</a>')
    assert [d for d, _ in list_govpl(html)] == [date(2024, 11, 15)]   # 20259 nie pasuje do 2020X - pominięte


# --- latest_govpl: najnowszy komunikat z odświeżaniem listy (przycisk w aplikacji) ---------------

URL_1026 = "https://www.gov.pl/attachment/f2aa91d1-d9e3-4a73-92ba-73d936d5da8d"
URL_1022 = "https://www.gov.pl/attachment/7c1bef52-5471-411c-840f-2eb94cb0be82"


class FakeResp:
    def __init__(self, text="", content=b"", status=200):
        self.text, self.content, self.status_code = text, content or text.encode(), status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise bulletins.requests.HTTPError(str(self.status_code))


def make_fetch(calls, list_html=None, bad=()):
    def fetch(url, **kw):
        calls.append(url)
        if url == bulletins.GOVPL_LIST_URL:
            return FakeResp(text=list_html if list_html is not None else read("govpl_list.html"))
        return FakeResp(content=b"%PDF-1.4 fake", status=404 if url in bad else 200)
    return fetch


@pytest.fixture
def pdf_text(monkeypatch):
    """Tekst „PDF" zależny od nazwy pliku: 26.10 i 22.10 → fixture z 22.10 (v 40,2), inne → 12.03 (v 61,23)."""
    def fake(path):
        return read("govpl_2026-10-22.txt") if path.stem in (URL_1026[-36:], URL_1022[-36:]) \
            else read("govpl_2024-03-12.txt")
    monkeypatch.setattr(bulletins, "_pdf_text", fake)


def test_latest_govpl_returns_newest(tmp_path, pdf_text):
    calls = []
    r = bulletins.latest_govpl(tmp_path, fetch=make_fetch(calls))
    assert r["bulletin_date"] == date(2026, 10, 26) and r["url"] == URL_1026
    assert (r["v_current"], r["v_npp"], r["v_maxpp"]) == (40.2, 65.7, 121.7)
    assert r["source"] == "govpl" and "reading_utc" in r
    assert calls == [bulletins.GOVPL_LIST_URL, URL_1026] and r["fallback_older"] is False


def test_latest_govpl_list_cache_ttl(tmp_path, pdf_text):
    calls = []
    f = make_fetch(calls)
    bulletins.latest_govpl(tmp_path, fetch=f)
    bulletins.latest_govpl(tmp_path, fetch=f, max_age_s=3600)          # świeża lista i PDF z cache: zero sieci
    assert calls.count(bulletins.GOVPL_LIST_URL) == 1 and calls.count(URL_1026) == 1
    old = tmp_path / "govpl_list.html"
    import os
    os.utime(old, (1, 1))                                               # lista starsza niż TTL → odświeżenie
    bulletins.latest_govpl(tmp_path, fetch=f, max_age_s=3600)
    assert calls.count(bulletins.GOVPL_LIST_URL) == 2


def test_latest_govpl_refresh_picks_up_new_entry(tmp_path, pdf_text):
    f1 = make_fetch([])
    bulletins.latest_govpl(tmp_path, fetch=f1)
    new = "9d1b0c3e-0000-4000-8000-000000000001"
    html = read("govpl_list.html") + (f'<a href="https://www.gov.pl/attachment/{new}">'
                                       'Komunikat z dnia 27.10.2026</a>')
    import os
    os.utime(tmp_path / "govpl_list.html", (1, 1))
    r = bulletins.latest_govpl(tmp_path, fetch=make_fetch([], list_html=html))
    assert r["bulletin_date"] == date(2026, 10, 27)


def test_latest_govpl_falls_back_to_previous_when_unreadable(tmp_path, pdf_text):
    calls = []
    r = bulletins.latest_govpl(tmp_path, fetch=make_fetch(calls, bad={URL_1026}))   # 404 na najnowszym
    assert r["bulletin_date"] == date(2026, 10, 22) and r["url"] == URL_1022 and r["fallback_older"] is True


def test_latest_govpl_tries_at_most_three(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(bulletins, "_pdf_text", lambda p: "brak tabeli")
    assert bulletins.latest_govpl(tmp_path, fetch=make_fetch(calls)) is None
    assert len([c for c in calls if c != bulletins.GOVPL_LIST_URL]) == 3


def test_latest_govpl_network_error_on_list_raises(tmp_path):
    def boom(url, **kw):
        raise bulletins.requests.ConnectionError("down")
    with pytest.raises(bulletins.requests.RequestException):
        bulletins.latest_govpl(tmp_path, fetch=boom)
    assert not (tmp_path / "govpl_list.html").exists()


def test_latest_govpl_pdf_network_error_raises_without_long_backoff(tmp_path):
    def f(url, **kw):
        if url == bulletins.GOVPL_LIST_URL:
            return FakeResp(text=read("govpl_list.html"))
        raise bulletins.requests.ConnectionError("down")
    import time
    t = time.monotonic()
    with pytest.raises(bulletins.DownloadError):
        bulletins.latest_govpl(tmp_path, fetch=f)
    assert time.monotonic() - t < 5


def test_fetch_govpl_list_still_never_refreshes(tmp_path, monkeypatch):
    (tmp_path / "govpl_list.html").write_text(read("govpl_list.html"), encoding="utf-8")
    monkeypatch.setattr(bulletins.requests, "get", lambda *a, **k: pytest.fail("sieć"))
    assert len(bulletins.fetch_govpl_list(tmp_path)) == 6


class StreamResp(FakeResp):
    def __init__(self, total, status=200):
        super().__init__(content=b"%PDF" + b"x" * total, status=status)
        self.read = 0

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            self.read += chunk_size
            yield self.content[i:i + chunk_size]


def test_download_caps_size_while_streaming(tmp_path):
    big = StreamResp(500_000)
    assert bulletins._download("u", tmp_path / "a.pdf", retries=1, backoff_s=0, fetch=lambda *a, **k: big,
                               max_bytes=100_000) is False
    assert big.read < 300_000 and not (tmp_path / "a.pdf").exists()
    ok = StreamResp(1000)
    assert bulletins._download("u", tmp_path / "b.pdf", retries=1, backoff_s=0, fetch=lambda *a, **k: ok,
                               max_bytes=100_000) is True


def test_latest_govpl_oversized_list_raises(tmp_path):
    big = StreamResp(bulletins.LIST_MAX_BYTES + 10)
    with pytest.raises(ValueError):
        bulletins.latest_govpl(tmp_path, fetch=lambda *a, **k: big)


def test_latest_govpl_deadline_and_timeouts(tmp_path, pdf_text):
    seen = []

    def f(url, **kw):
        seen.append(kw["timeout"])
        return make_fetch([])(url, **kw)
    bulletins.latest_govpl(tmp_path, fetch=f, deadline_s=40)
    assert all(t[0] == 5 and t[1] <= 15 for t in seen)
    with pytest.raises(TimeoutError):
        bulletins.latest_govpl(tmp_path / "x", fetch=make_fetch([]), deadline_s=0)


def test_read_capped_enforces_deadline_while_streaming():
    t = [0.0]

    class Drip(FakeResp):
        def iter_content(self, chunk_size=1):
            for _ in range(100):
                t[0] += 14.0                      # bajt co 14 s: poniżej timeoutu odczytu
                yield b"x"

    with pytest.raises(TimeoutError):
        bulletins._read_capped(Drip(), 10_000_000, deadline_at=40.0, clock=lambda: t[0])
    assert t[0] <= 56.0                           # przerwane tuż po przekroczeniu budżetu


def test_latest_govpl_slow_drip_pdf_hits_deadline(tmp_path):
    t = [0.0]

    class Drip(FakeResp):
        def iter_content(self, chunk_size=1):
            yield b"%PDF"
            while True:
                t[0] += 14.0
                yield b"x"

    def f(url, **kw):
        return FakeResp(text=read("govpl_list.html")) if url == bulletins.GOVPL_LIST_URL else Drip()
    with pytest.raises(TimeoutError):
        bulletins.latest_govpl(tmp_path, fetch=f, deadline_s=40, clock=lambda: t[0])


def test_connect_timeout_shrinks_with_remaining_budget(tmp_path, pdf_text):
    t, seen = [0.0], []

    def f(url, **kw):
        seen.append(kw["timeout"])
        t[0] += 38.0
        return make_fetch([])(url, **kw)
    with pytest.raises(TimeoutError):               # po liście zostaje 2 s, po PDF-ie nic
        bulletins.latest_govpl(tmp_path, fetch=f, deadline_s=40, clock=lambda: t[0])
    assert seen[0] == (5, 15) and seen[1] == (2.0, 2.0)
