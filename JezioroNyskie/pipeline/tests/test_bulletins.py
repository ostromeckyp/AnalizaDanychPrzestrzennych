"""Testy komunikatów RZGW / Wód Polskich (wariant B h_t): parsery, lista gov.pl, wybór dnia."""
from datetime import date
from pathlib import Path

import pytest

from mielizna.bulletins import (choose_bulletin, list_govpl, parse_govpl_text, parse_pl_number,
                                parse_rzgw_text, wayback_index)

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
