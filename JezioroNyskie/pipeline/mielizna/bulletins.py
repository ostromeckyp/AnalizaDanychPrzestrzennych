"""Komunikaty o pojemności zbiornika Nysa (RZGW Wrocław / Wody Polskie) - wejście wariantu B `h_t`.

Co robi: parsuje wiersz zbiornika Nysa z dwóch formatów PDF (archiwum RZGW w Wayback Machine
  2019-2024 i komunikaty krajowe gov.pl od 02.2024), wybiera dla każdej daty sceny komunikat
  z tego samego dnia albo z ±1 dnia i zwraca tabelę pojemności (aktualna, przy NPP, przy Max PP).
Dlaczego tak: komunikat jest jedynym dziennym źródłem objętości, a `h_t` liczymy z tabeli
  pojemność ↔ rzędna. Pojemność przy NPP zmieniła się (66,3 → 65,7 mln m³), więc `v_npp`
  zostaje przy każdej scenie, a nie jest stałą. Wiersz Nysa łatwo pomylić z Otmuchowem
  („Nysa Kłodzka” to nazwa rzeki) i Słupem („Nysa Szalona”), dlatego parsery wymagają dokładnej
  postaci wiersza. Data wewnątrz PDF jest porównywana z datą z nazwy/tytułu (plik pod złą datą
  zepsułby h_t po cichu).
Wejście → wyjście: tekst PDF / HTML listy / lista dat scen → słownik {v_current, v_npp, v_maxpp},
  lista (data, url), DataFrame scene_date, bulletin_date, source, v_current, v_npp, v_maxpp, url.
Gdy jednego dnia są dwa komunikaty (06 i 12 UTC), wybieramy ten o godzinie odczytu najbliższej
  przelotu Sentinel-2 (10:00 UTC); godzina trafia do kolumny `reading_utc`. Uwaga: w logu 06a
  `v_npp` jest grupowane po zaokrągleniu do 0,1 (65,69 to zapis 65,7 z dwoma miejscami), a CSV ma
  wartości surowe.
Jak to obronić: reguła wyboru dnia jest jawna i testowana (ten sam dzień przed sąsiadem), brak
  komunikatu daje brak wiersza (nie interpolację), a wszystkie PDF-y są w cache `data/raw/rzgw/`.
"""
import html as html_lib
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from pypdf import PdfReader

from .config import data_path

log = logging.getLogger("bulletins")

WAYBACK_CSV = "rzgw_wayback_index.csv"
GOVPL_LIST_URL = "https://www.gov.pl/web/wody-polskie/sytuacja-hydrologiczna"
USER_AGENT = "mielizna-research/0.1 (studencki projekt analizy danych przestrzennych)"
MIN_INTERVAL_S = 1.0          # <= 1 zapytanie/s do Wayback i gov.pl
MAX_V = 200.0                 # sanity: pojemność Nysy nie przekracza ~125 mln m3
MONTHS = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
          "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11,
          "grudnia": 12}
OVERPASS_MIN = 10 * 60        # przelot Sentinel-2 nad Nysą ok. 10:00 UTC
_last_request = [0.0]


def parse_pl_number(s: str) -> float:
    """„32,668” → 32.668, „1 234,5” → 1234.5.

    Co robi: zamienia liczbę zapisaną po polsku (przecinek dziesiętny, spacja tysięcy) na float.
    Dlaczego tak: PDF-y RZGW używają przecinka, a spacje tysięcy mogą być twarde (U+00A0).
    Wejście → wyjście: str → float; ValueError dla tekstu nieliczbowego (np. „b.d.”).
    Jak to obronić: jedna, testowana konwersja zamiast rozsianych replace().
    """
    return float(re.sub(r"[\s ]", "", s).replace(",", "."))


def _numbers(tokens: list[str]) -> list[float] | None:
    """Pierwsze 5 tokenów jako liczby albo None, gdy któryś to „b.d.”/tekst."""
    if len(tokens) < 5:
        return None
    try:
        vals = [parse_pl_number(t) for t in tokens[:5]]
    except ValueError:
        return None
    return vals


def _row(vals: list[float] | None) -> dict | None:
    # kolumny: odpływ, dopływ, pojemność aktualna, poj. przy NPP, poj. przy Max PP
    if vals is None:
        return None
    cur, npp, maxpp = vals[2], vals[3], vals[4]
    if not (0 < cur < MAX_V and 0 < npp < maxpp < MAX_V):
        return None
    return {"v_current": cur, "v_npp": npp, "v_maxpp": maxpp}


def parse_rzgw_text(text: str) -> dict | None:
    """Wiersz zbiornika Nysa z komunikatu RZGW (archiwum Wayback, 2019-2024).

    Co robi: znajduje linię złożoną wyłącznie ze słowa „Nysa”, a następną linię zaczynającą się
      od „Nysa Kłodzka”; z liczb za nią bierze 3., 4. i 5. (aktualna, przy NPP, przy Max PP).
    Dlaczego tak: pypdf zwraca nazwę zbiornika i rzekę w osobnych liniach; „Nysa Kłodzka” to
      też rzeka Otmuchowa i Topoli, więc samo dopasowanie nazwy rzeki dałoby zły zbiornik.
    Wejście → wyjście: tekst strony PDF → {"v_current","v_npp","v_maxpp"} w mln m3 albo None.
    Jak to obronić: test na prawdziwym wycinku PDF i testy negatywne dla Otmuchowa i Słupa.
    """
    lines = text.splitlines()
    for i, ln in enumerate(lines[:-1]):
        if ln.strip() == "Nysa" and lines[i + 1].lstrip().startswith("Nysa Kłodzka"):
            rest = lines[i + 1].lstrip()[len("Nysa Kłodzka"):]
            return _row(_numbers(rest.split()))
    return None


_GOVPL_ROW = re.compile(r"^\s*\d+\s+Nysa\s+\(Nysa Kłodzka\)\s+(.*)$", re.M)


def parse_govpl_text(text: str) -> dict | None:
    """Wiersz „43 Nysa (Nysa Kłodzka)” z tabeli „Informacja o zbiornikach” (gov.pl, od 02.2024).

    Co robi: dopasowuje linię `<nr> Nysa  (Nysa Kłodzka) q_odpływ q_dopływ V V_NPP V_MaxPP ...`
      i zwraca 3., 4. i 5. liczbę.
    Dlaczego tak: w tym formacie nazwa, rzeka i liczby są w jednej linii; wymagamy numeru
      porządkowego i nazwy „Nysa” tuż przed nawiasem, więc „42 Otmuchów (Nysa Kłodzka)” i
      „46 Słup (Nysa Szalona)” nie pasują. „b.d.” (brak danych) daje None, nie zero.
    Wejście → wyjście: tekst PDF → {"v_current","v_npp","v_maxpp"} albo None.
    Jak to obronić: fixture’y z trzech prawdziwych komunikatów (różna liczba miejsc po przecinku
      i wariant „skrócony”), a wartości sprawdzone ręcznie w PDF.
    """
    m = _GOVPL_ROW.search(text)
    return _row(_numbers(m.group(1).split())) if m else None


def text_date(text: str) -> date | None:
    """Data z nagłówka „z dnia 27 grudnia 2021 r.” (pierwsze wystąpienie) albo None."""
    m = re.search(r"z dnia\s+(\d{1,2})\s+([a-ząćęłńóśźż]+)\s*(\d{4})", text)
    if not m or m.group(2) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))


def _hhmm(s: str) -> tuple[int, int] | None:
    """„6:00” / „600” / „0600” / „1200” → (godzina, minuta) albo None."""
    s = s.replace(" ", "")
    if ":" in s:
        h, m = s.split(":")
    elif len(s) in (3, 4):
        h, m = s[:-2], s[-2:]
    else:
        return None
    h, m = int(h), int(m)
    return (h, m) if h < 24 and m < 60 else None


_READ_RZGW = re.compile(r"na godzin[ęe]\s+(\d{1,2}\s?:\d{2})\s*(?:\(\s*(\d{1,2}:\d{2})\s*UTC\s*\)|(UTC))?")
_READ_GOVPL = re.compile(r"Sytuacja na dzień[^\n]*?na godz\.?\s*(\d{1,2}\s?:\d{2}|\d{3,4})\s*\(UTC\)")


def reading_utc(text: str, d: date) -> str | None:
    """Godzina odczytu komunikatu w UTC jako „HH:MM” albo None.

    Co robi: czyta „na godzinę 6:00 UTC” (RZGW), „Sytuacja na dzień D na godz. 1200 (UTC)”
      (gov.pl) i „na godzinę 16:00 (14:00 UTC)”; gdy podano tylko czas lokalny, przelicza go
      z Europe/Warsaw na UTC dla daty `d`.
    Dlaczego tak: tego samego dnia bywają dwa komunikaty (06 i 12 UTC), a wybieramy ten
      najbliższy przelotowi satelity.
    Wejście → wyjście: tekst PDF + data komunikatu → „HH:MM” (UTC) albo None.
    Jak to obronić: wartość jest czytana z tekstu, nie zgadywana; brak = None (nigdy preferowany).
    """
    m = _READ_GOVPL.search(text)
    if m and (t := _hhmm(m.group(1))):
        return f"{t[0]:02d}:{t[1]:02d}"
    m = _READ_RZGW.search(text)
    if m:
        utc = m.group(2) or (m.group(1) if m.group(3) else None)
        if utc and (t := _hhmm(utc)):
            return f"{t[0]:02d}:{t[1]:02d}"
        if t := _hhmm(m.group(1)):
            local = datetime(d.year, d.month, d.day, t[0], t[1], tzinfo=ZoneInfo("Europe/Warsaw"))
            return local.astimezone(timezone.utc).strftime("%H:%M")
    return None


def pick_reading(rows: list[dict]) -> dict:
    """Z komunikatów jednego dnia wybiera ten o odczycie najbliższym 10:00 UTC (remis → wcześniejszy).

    Nieczytelna godzina (`reading_utc` None) nigdy nie wygrywa z czytelną.
    """
    def key(r):
        t = _hhmm(r["reading_utc"]) if r.get("reading_utc") else None
        if t is None:
            return (1, 0, 0)
        mins = t[0] * 60 + t[1]
        return (0, abs(mins - OVERPASS_MIN), mins)
    return min(rows, key=key)


def list_govpl(html: str) -> list[tuple[date, str]]:
    """Lista komunikatów z podstrony gov.pl jako posortowane (data, url załącznika).

    Co robi: wyciąga linki `https://www.gov.pl/attachment/<uuid>`, których tekst zawiera
      „z dnia D.M.RRRR”; raporty lodowe (bez „z dnia”) i tytuły z błędną datą (np. „21.102.2024”)
      są pomijane; ten sam załącznik występujący dwa razy jest scalany.
    Dlaczego tak: poprzedni parser oczekiwał linków względnych (`/attachment/...`), a strona ma
      adresy bezwzględne, więc zwracał 0. Nie filtrujemy po słowie „Skrócony”: skrócone
      komunikaty mają tę samą tabelę zbiorników (potwierdzone 29.09.2024).
    Wejście → wyjście: HTML → [(date, url)] posortowane rosnąco po dacie i url.
    Jak to obronić: fixture z prawdziwych linków (w tym przypadki brzegowe), a głębokość listy
      jest mierzona w skrypcie 06a na żywej stronie.
    """
    out = {}
    for url, label in re.findall(r'<a href="(https://www\.gov\.pl/attachment/[0-9a-f-]{36})"[^>]*>(.*?)</a>',
                                 html, flags=re.S):
        text = html_lib.unescape(re.sub(r"<[^>]+>", " ", label))
        m = re.search(r"z dnia\s+(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", text)
        typo = None if m else re.search(r"z dnia\s+(\d{1,2})\.(\d{1,2})\.2020(\d)(?!\d)", text)
        if not m and not typo:
            continue
        try:   # literówka „20204” → 2024 (zdublowane 0)
            d = (date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m
                 else date(2020 + int(typo.group(3)), int(typo.group(2)), int(typo.group(1))))
        except ValueError:
            continue
        out[url] = d
    return sorted(((d, u) for u, d in out.items()))


_WAYBACK_NAME = re.compile(
    r"Komunikat_o_sytuacji_w_regionie_z_dn_(\d{1,2})-(\d{1,2})-(\d{4})(?:_\d*)?\.pdf$", re.I)


def wayback_index(csv_path: Path | None = None) -> dict[date, list[tuple[str, str]]]:
    """Indeks CDX archiwum RZGW: data komunikatu → [(timestamp, oryginalny url), ...].

    Co robi: z `rzgw_wayback_index.csv` bierze pliki „Komunikat_o_sytuacji_w_regionie_z_dn_D-M-RRRR”
      (także warianty z sufiksem „_1” i jednocyfrowym dniem); informacje żeglugowe pomija.
    Dlaczego tak: tylko komunikaty o sytuacji w regionie mają tabelę zbiorników. Jedna data
      może mieć kilka plików (poprawki), więc zwracamy listę.
    Wejście → wyjście: CSV (timestamp, original, ...) → słownik data → lista (timestamp, url).
    Jak to obronić: data pochodzi z nazwy pliku, a po pobraniu jest weryfikowana z nagłówkiem PDF.
    """
    csv_path = csv_path or data_path("raw", "check", WAYBACK_CSV)
    out: dict[date, list[tuple[str, str]]] = {}
    for r in pd.read_csv(csv_path, dtype=str).itertuples():
        m = _WAYBACK_NAME.search(r.original.rsplit("/", 1)[-1])
        if not m:
            continue
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        out.setdefault(d, []).append((str(r.timestamp), r.original))
    return out


def choose_bulletin(scene_date: date, available: dict) -> date | None:
    """Reguła wyboru dnia komunikatu: ten sam dzień → ±1 dzień → None.

    Co robi: zwraca scene_date, jeśli jest w `available`; inaczej bliższy dzień z ±1 (przy remisie
      wcześniejszy, bo komunikat z 06:00 UTC poprzedniego dnia nie zna jeszcze przyszłości sceny);
      inaczej None.
    Dlaczego tak: poziom zbiornika zmienia się wolno (rząd cm/dobę), ale z reguły im bliżej
      daty sceny, tym mniejszy błąd h_t; dalej niż ±1 dzień nie zgadujemy.
    Wejście → wyjście: data sceny + dowolny słownik data → coś → wybrana data albo None.
    Jak to obronić: reguła jest czystą funkcją z testami (ten sam dzień wygrywa z sąsiadem).
    """
    if scene_date in available:
        return scene_date
    for delta in (-1, 1):
        d = scene_date + timedelta(days=delta)
        if d in available:
            return d
    return None


def _throttle():
    wait = MIN_INTERVAL_S - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.monotonic()


class DownloadError(RuntimeError):
    """Trwała awaria sieci (nie 404): przerywamy przebieg, żeby nie zgubić scen po cichu."""


def _download(url: str, dest: Path, retries: int = 5, backoff_s: float = 30.0) -> bool:
    """Pobiera PDF do cache (1 zapytanie/s) z długim odstępem po błędach.

    Wayback odcina połączenia („connection refused”) po kilkunastu zapytaniach w serii, więc po
    błędzie czekamy 30 s, 60 s, ... zamiast ponawiać od razu. 404/inna odpowiedź niebędąca PDF
    to brak pliku (False); wyczerpanie prób przy błędach sieci rzuca DownloadError, bo cicha
    strata sceny zafałszowałaby pokrycie. Skrypt jest wznawialny dzięki cache.
    """
    if dest.exists() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=90)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(dest)
                return True
            log.warning("HTTP %s dla %s (próba %d)", r.status_code, url, attempt + 1)
            if r.status_code in (404, 403, 410):
                return False
        except requests.RequestException as e:
            log.warning("błąd sieci dla %s: %s (próba %d)", url, type(e).__name__, attempt + 1)
        time.sleep(backoff_s * 2 ** attempt)
    raise DownloadError(f"nie udało się pobrać {url} po {retries} próbach")


def _pdf_text(path: Path) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)


def fetch_govpl_list(cache_dir: Path | None = None) -> list[tuple[date, str]]:
    """Pobiera (i zapisuje w cache) podstronę gov.pl z listą komunikatów, zwraca list_govpl()."""
    cache_dir = cache_dir or data_path("raw", "rzgw")
    cache = cache_dir / "govpl_list.html"
    if not cache.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        _throttle()
        r = requests.get(GOVPL_LIST_URL, headers={"User-Agent": USER_AGENT}, timeout=90)
        r.raise_for_status()
        cache.write_text(r.text, encoding="utf-8")
    return list_govpl(cache.read_text(encoding="utf-8"))


def _candidates(wayback: dict, govpl: list[tuple[date, str]]) -> dict[date, list[dict]]:
    """Wszystkie znane komunikaty wg daty; Wayback przed gov.pl (starsze, zweryfikowane)."""
    cand: dict[date, list[dict]] = {}
    for d, items in wayback.items():
        for ts, url in items:
            cand.setdefault(d, []).append({
                "source": "wayback", "url": f"https://web.archive.org/web/{ts}id_/{url}",
                "file": f"wayback/{ts}_{url.rsplit('/', 1)[-1]}"})
    for d, url in govpl:
        cand.setdefault(d, []).append({
            "source": "govpl", "url": url, "file": f"govpl/{url.rsplit('/', 1)[-1]}.pdf"})
    return cand


def _load(d: date, entry: dict, cache_dir: Path) -> dict | None:
    """Pobiera i parsuje jeden komunikat; None gdy brak pliku, wiersza lub zła data w PDF."""
    path = cache_dir / entry["file"]
    if not _download(entry["url"], path):
        log.warning("%s: nie udało się pobrać %s", d, entry["url"])
        return None
    try:
        text = _pdf_text(path)
    except Exception as e:  # uszkodzony PDF
        log.warning("%s: nie da się odczytać %s: %r", d, path.name, e)
        return None
    inner = text_date(text)
    if inner is None:
        log.warning("%s: brak daty „z dnia” w %s - nie można zweryfikować daty", d, path.name)
    if inner is not None and inner != d:
        log.warning("%s: data w PDF %s różni się od daty w nazwie (%s) - odrzucono", d, inner, path.name)
        return None
    parse = parse_rzgw_text if entry["source"] == "wayback" else parse_govpl_text
    row = parse(text)
    if row is None and entry["source"] == "wayback":
        row = parse_govpl_text(text)   # RZGW od 2024 używa też układu z numerowaną tabelą
    if row is None:
        log.warning("%s: brak czytelnego wiersza Nysa w %s", d, path.name)
        return None
    return row | {"source": entry["source"], "url": entry["url"], "reading_utc": reading_utc(text, d)}


def fetch_for_dates(dates: list[date], cache_dir: Path | None = None,
                    wayback: dict | None = None, govpl: list | None = None) -> pd.DataFrame:
    """Komunikat o pojemności dla każdej daty sceny (ten sam dzień, inaczej ±1 dzień).

    Co robi: łączy indeks Wayback i listę gov.pl, dla każdej daty wybiera dzień przez
      `choose_bulletin`, pobiera tylko potrzebne PDF-y (cache `data/raw/rzgw/`) i parsuje je.
      Gdy wybrany komunikat jest nieczytelny, próbuje następny najlepszy dzień w oknie ±1.
    Dlaczego tak: nie pobieramy całego archiwum (1000+ plików), tylko dni potrzebne scenom;
      `v_npp` zostaje per scena, bo pojemność przy NPP zmieniła się między 2021 a 2024.
    Wejście → wyjście: lista dat scen → DataFrame (scene_date, bulletin_date, source, v_current,
      v_npp, v_maxpp, reading_utc, url); sceny bez komunikatu nie mają wiersza.
    Jak to obronić: żadnej interpolacji ani dopisywania wartości; ślad w logu dla każdej straty.
    """
    cache_dir = cache_dir or data_path("raw", "rzgw")
    wayback = wayback_index() if wayback is None else wayback
    govpl = fetch_govpl_list(cache_dir) if govpl is None else govpl
    cand = _candidates(wayback, govpl)
    parsed: dict[date, dict | None] = {}
    rows = []
    for sd in sorted(dates):
        avail = {d: v for d, v in cand.items() if abs((d - sd).days) <= 1}
        found = False
        while (bd := choose_bulletin(sd, avail)) is not None:
            if bd not in parsed:
                loaded = [r for e in avail[bd] if (r := _load(bd, e, cache_dir))]
                parsed[bd] = pick_reading(loaded) if loaded else None
            if parsed[bd] is not None:
                rows.append({"scene_date": sd, "bulletin_date": bd} | parsed[bd])
                found = True
                break
            del avail[bd]
        if not found:
            log.info("%s: brak czytelnego komunikatu w oknie ±1 dzień", sd)
    cols = ["scene_date", "bulletin_date", "source", "v_current", "v_npp", "v_maxpp", "reading_utc", "url"]
    return pd.DataFrame(rows, columns=cols)
