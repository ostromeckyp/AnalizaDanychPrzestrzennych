# Hold-out roczny, budżet błędu dna i sekcja „Jak sprawdziliśmy” — projekt

Data: 2026-11-24. Status: do akceptacji (po recenzji budowniczego).

## Po co

Walidacja terenowa (echosonda, Messtischblatt, zdjęcia przy niskiej wodzie) jest odłożona do następnego sezonu.
Do tego czasu chcemy uczciwie powiedzieć, **jak sprawdziliśmy model dna i w jakim zakresie może się mylić**,
korzystając tylko z danych, które już mamy. Czytelnik: prowadzący przedmiot (raport) i użytkownik aplikacji
(strona „O metodzie”).

Brakuje jednej rzeczy: testu, czy model przewiduje sceny, których nie widział. Wszystkie dotychczasowe kontrole
(LiDAR, KŻ, objętość) porównują model z zewnętrzną referencją, ale żadna nie mierzy, jak model zachowuje się
na nowych danych z tego samego źródła.

## Cele

1. **Hold-out roczny** (decyzja użytkownika: cały rok, nie pojedyncza scena).
2. **Budżet błędu dna**: zestawienie wszystkich kontroli z zakresem błędu w pasmach wysokości.
3. **Raport**: nowe §5.5 (hold-out) i §5.6 (jak mierzyliśmy, zakres błędu, co zamknie teren); wiersze w tabeli §5.1.
4. **Strona „O metodzie”**: sekcja „Jak sprawdziliśmy model” z listą kontroli i tabelą zakresu błędu.

## Poza zakresem

- Pomiary w terenie, Messtischblatt, Navionics (odłożone).
- Hold-out pojedynczych scen i hold-out pasm poziomów (użytkownik wybrał rok).
- Porównanie z metodą interpolacji TIN/IDW i ręczne linie brzegowe (osobne luki w §5.1, nie tu).
- Zmiana samego modelu dna. Hold-out tylko mierzy.

## Czego unikać (porażka, nawet jeśli działa)

- **Jedna liczba „±X m” dla całego jeziora.** Błąd zależy od wysokości, a poniżej ok. 192,9 m model nic nie wie.
  Taka liczba sugerowałaby wiedzę, której nie mamy.
- **Sumowanie składników błędu (pierwiastek z sumy kwadratów).** Źródła są skorelowane (te same maski, te same poziomy);
  suma udawałaby niezależność.
- **Test na scenach, których poziom pochodzi z maski** (wariant C, krzywa powierzchnia–poziom): błędne koło.
- **Zawyżone IoU** liczone na całym jeziorze, gdzie rdzeń „zawsze woda” trafia się sam.

## Podejście (wybrane)

Rozważane: (a) leave-one-scene-out, łatwe, ale optymistyczne, bo sąsiednie sceny o prawie tym samym poziomie
zostają w modelu; (b) **leave-one-year-out**, uczciwsze, sprawdza nieznany sezon; (c) odkładanie pasm poziomów,
testuje interpolację, ale na brzegach zakresu wymusza ekstrapolację. **Wybrane: (b).** Dla porównania liczymy te
same miary na modelu pełnym (w próbie); różnica pełny − hold-out pokazuje, ile wynik w próbie zawyża jakość.

## Hold-out: projekt

**Fałdy.** Każdy rok Y ∈ 2020–2026 (lata ze scenami B/R; 7 fałd). Trening: sceny okresu `all` (model serwowany)
z `qc_ok`, bez scen roku Y (wszystkich metod). Ten sam kod co w 07: `select_scenes` → `combine_evidence` →
`compute_bounds` z tymi samymi parametrami (`k_sigma`, reguła C). Test: sceny roku Y z `h_method ∈ {B, R}`
i `qc_ok` (155 scen). Sceny A i C z lat testowych (np. 2022, 2025–2026) też wypadają z treningu swojej fałdy, ale nie są testowane.
Lata 2017–2019 (tylko A i C) są zawsze w treningu, nigdy w teście.

**Izolacja fałd (decyzja Claude).** Fałda usuwa tylko sceny roku Y. Klasyfikator RF i krzywa C (dopasowana do scen B,
także z roku Y) nie są trenowane od nowa. Przeciek jest mały: woda ze scen C i tak nie ustala `z_max` (reguła R24),
a RF ocenia piksel, nie poziom. Raport opisuje ten przeciek wprost; ponowny trening RF i krzywej na fałdę
pomnożyłby czas i ingerował w kroki 04/06.

**Powódź (decyzja Claude).** Wyniki per fałd plus grupy: przed powodzią (2020–2023), 2024 osobno (rok mieszany),
po powodzi (2025–2026). Tak widać, czy po zmianie dna przy brzegu błąd rośnie.

**Referencja.** Dowód sceny testowej z `combine_evidence` (RF∧Otsu), czyli to samo, co model dostałby na wejściu.
Referencja ma własny błąd klasyfikacji (OA ok. 0,90), więc wynik zawiera tę „podłogę”; raport to mówi.

**Miary na scenę, potem zbiorczo (mediana, P10/P90 po scenach; dodatkowo po fałdach):**

1. **Błąd pionowy na linii wody (główna miara).** Piksele brzegowe sceny testowej: piksel wody z sąsiadem lądu
   (4-sąsiedztwo, oba ważne). Tam prawdziwe dno ≈ `h_t` (± `h_sigma`). Błąd = `z` modelu hold-out − `h_t` dla pikseli
   z obiema granicami. Raport: bias, MAE, P90 |błędu|, udział pikseli z `h_t ∈ [z_min, z_max]` (kalibracja przedziałów)
   i udział pikseli brzegowych bez przewidywania (model hold-out nie ma tam obu granic). Rozbicie wg pasm poziomu sceny.
   To daje błąd w metrach wysokości wprost, bez przeliczania przez nachylenie.
2. **IoU wody w strefie zmiennej.** Strefa = piksele AOI, które w modelu pełnym mają przedział albo sprzeczności
   (bez rdzenia „zawsze woda” i dalekiego lądu). Przewidywana woda: `z_max ≤ h_t` lub „zawsze woda”; przewidywany ląd:
   `z_min ≥ h_t` lub „zawsze ląd”; pomiędzy: woda, gdy `z < h_t`. Dodatkowo udział strefy „niepewne” (pomiędzy). IoU całego
   jeziora tylko jako przypis.
3. **Odległość linii brzegowych (m).** `mask_to_shoreline` na masce przewidywanej i referencyjnej; średnia symetryczna,
   mediana i P90 odległości przewidywanej → obserwowanej. Pomocnicza, dla intuicji („linia o ok. N m obok”).

**Porównanie z modelem w próbie.** Te same miary dla modelu pełnego `all` na tych samych scenach testowych.

**Wyjście.** `data/processed/eval/holdout.json` (per fałd, per scena, zbiorczo, w próbie vs hold-out, pasma),
rysunek `docs/img/eval-holdout.png` (rozkład błędu pionowego wg pasm, hold-out vs w próbie). Nowy moduł
`pipeline/mielizna/holdout.py` (czyste funkcje, testowane), skrypt `pipeline/12_holdout.py`, cel `make holdout`.
Rastry fałd nie są zapisywane (tylko JSON); czas: 7 przebiegów `compute_bounds`, akceptowalny.

## Budżet błędu: projekt

**Pasma wysokości** (granice z tabeli pojemności i zakresu obserwacji): ≥ 194,8 m; 192,9–194,8 m; < 192,9 m.

**Źródła na pasmo** (bierzemy z istniejących JSON-ów, liczymy tylko hold-out):

| źródło | co mierzy | plik |
|---|---|---|
| hold-out roczny | błąd na nowych danych (nowy) | `holdout.json` |
| NMT LiDAR (model `all`, pierścień) | dno vs teren w pasie brzegowym | `bottom_vs_nmt.json` (rozbicie wg z do dodania, jeśli brak) |

**LiDAR wprost (decyzja użytkownika).** Do zakresu wchodzi MAE modelu serwowanego `all` (1,31 m, bias +1,16 m) bez
odejmowania obciążenia. Hipoteza o przesunięciu układu RZGW↔EVRF idzie do noty przy paśmie, nie zmienia liczby.
`pre_flood` (0,82 m) może pojawić się tylko jako kontekst w raporcie.
| mapa KŻ (punkty ≥ 192,5 m) | dno vs niezależna mapa | `kz_points.json` |
| objętość ΔV warstw | spójność całej warstwy | `volume.json` |
| poziomy `h_t` (B vs kontrole, A − B) | składnik poziomu | `levels.json` |

**Pasma w źródłach (decyzja Claude).** 13 liczy KŻ i objętość od nowa w pasmach budżetu z danych źródłowych
(punkty KŻ z `kz_spot_ocr.gpkg` i modelem, warstwy objętości przez `mielizna.volume`), bez zmiany istniejących kluczy
w `kz_points.json` i `volume.json`. Gdzie źródło pasma nie pokrywa (np. objętość 192,9–193,3 m), komórka zostaje pusta
z adnotacją, bez przybliżania.

**Jednostki (decyzja Claude).** Do zakresu w metrach wchodzą tylko źródła mierzące wysokość dna w metrach: hold-out,
LiDAR, KŻ. Objętość (stosunek ΔV) i poziomy `h_t` są w tabeli osobną kolumną „kontekst”: objętość mówi, czy warstwa
jest spójna, poziomy mówią, ile błędu wnosi sam poziom wody.

**Zestawienie, nie suma.** Dla każdego pasma: tabela źródeł z ich |bias| i MAE (lub ekwiwalentem dla objętości),
potem **zakres** = od najmniejszego do największego MAE spośród źródeł, które to pasmo pokrywają, i źródło dominujące.
Pasmo < 192,9 m: „brak danych, model nie ma dolnej granicy”, bez liczby. Wyjście: `data/processed/eval/error_budget.json`,
skrypt `pipeline/13_error_budget.py`, cel `make error-budget` (zależny od holdout i istniejących eval).

## Raport

- **§5.5 Hold-out roczny:** jak (fałdy, referencja, miary), wyniki (tabela zbiorcza, per fałd, rysunek), hold-out vs w próbie,
  co to znaczy i czego nie mówi (podłoga klasyfikacji, brak głębi).
- **§5.6 Jak zmierzyliśmy i zakres błędu (bez terenu):** dla każdej kontroli jeden akapit „co porównujemy, z czym, wynik,
  czego nie pokrywa”; tabela budżetu wg pasm; lista tego, co zamknie walidacja terenowa (echosonda dla < 192,9 m itd.).
- **§5.1:** wiersze „Hold-out roczny” i „Zakres błędu dna wg pasm”. Liczby przez istniejące znaczniki
  `<!-- eval:plik:klucz -->`, tak jak reszta raportu.

## API i strona „O metodzie”

**Backend.** `eval_accuracy` dostaje pola hold-out (`holdout_mae`, `holdout_bias`, `holdout_in_bounds`, `holdout_n_scenes`);
`MetaResponse` dostaje nowe pole `validation` (nullable): lista pasm `{band, range_m: [lo, hi] | null, dominant, note}`
i lista kontroli `{name, compared_with, result}` z `error_budget.json`. Brak pliku → `null`, strona ukrywa sekcję.
Aktualizacja `openapi.json` i typów frontu.

**Frontend.** Nowa sekcja między „Dokładność modelu” a „Źródła danych”:

```
Jak sprawdziliśmy model
  Bez pomiarów w terenie zrobiliśmy pięć kontroli; trzy z nich używają danych niezależnych od satelity (LiDAR, mapa KŻ, tabela pojemności).
  • Hold-out roczny — model bez danego roku vs sceny tego roku — błąd dna ±0,xx m
  • LiDAR (teren przy brzegu) — ...
  • Mapa KŻ — ...
  • Objętość zbiornika — ...
  • Poziomy wody — ...

  Zakres błędu dna
  | wysokość dna     | typowy błąd    | główne źródło |
  | ≥ 194,8 m        | 0,x–0,y m      | ...           |
  | 192,9–194,8 m    | 0,x–0,y m      | ...           |
  | < 192,9 m        | brak danych    | sprawdzimy echosondą |
```

Kafelek „Hold-out (MAE)” w `AccuracyTiles`. Testy komponentu jak istniejące (`MethodPage.test`, mobile).

## Ograniczenia

- Pipeline Python (uv), konwencje docstringów „Co robi / Dlaczego tak / Wejście → wyjście / Jak to obronić”.
- Liczby w raporcie tylko przez znaczniki eval, bez wpisywania na sztywno.
- Make: kroki eval nie mogą unieważniać łańcucha S2 → klasyfikacja → model.

## Zostawione budowniczemu

- Dokładny układ JSON-ów, nazwy kluczy, wygląd rysunku.
- Czy rozbicie `bottom_vs_nmt` wg pasm wymaga nowego liczenia (jeśli tak, dopisać w 08 lub w 13, bez zmiany istniejących kluczy).
- Styl CSS nowej sekcji (zgodny z `methodPage.css`).
