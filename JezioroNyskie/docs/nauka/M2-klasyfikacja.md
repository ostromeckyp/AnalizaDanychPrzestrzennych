# M2 — Klasyfikacja: które piksele to woda, a które ląd (Random Forest vs próg Otsu vs SCL)

Najpierw po ludzku, potem terminy. Wszystkie liczby: `data/processed/model/rf_report.md` i `rf_metrics.json`
(chyba że podano inny plik). **Cel M2 (OA ≥ 95% na punktach ręcznych) NIE został spełniony — piszemy to wprost.**

## 1. Co powstało (pliki)

| plik | co to jest |
|---|---|
| `data/reference/labels.gpkg` | 620 punktów do oceny (warstwy: `auto_water`, `auto_land`, `shore`, `shore_low`); etykiety ludzkie w kolumnie `label`, `source=human` |
| `data/processed/model/rf_model.joblib` | wytrenowany model + opis (cechy, próg wody `water_threshold` = 0,70, sha etykiet i configu) |
| `data/processed/model/rf_metrics.json`, `rf_report.md` | wyniki walidacji: tabele A–E |
| `data/processed/masks/{data}.tif` | maska RF: 0 = ląd, 1 = woda, 255 = brak danych/chmura |
| `data/processed/masks_otsu/{data}.tif` | to samo progiem Otsu (do porównania i do modelu dna) |
| `data/processed/proba/{data}.tif` | P(woda) 0–254 (nieużywane przez model dna po decyzji U1) |
| `data/processed/classify_stats.csv` | 221 wierszy: powierzchnia RF/Otsu, kontrola jakości sceny (`qc_ok`) |
| `data/processed/shorelines.gpkg` | linia brzegowa i powierzchnia wody każdej sceny |

Skrypty: `04a_label_candidates.py` (losowanie punktów), `tools/label_server.py` (okno do klikania), `04b_train_rf.py`
(trening + ocena), `04_classify.py` (klasyfikacja wszystkich scen), `05_shorelines.py` (linie brzegowe).

## 2. Jak powstały etykiety (to jest „prawda", z którą porównujemy)

- **Dwie rundy ręcznego etykietowania** w oknie `label_server` (klawisze woda/ląd/pomiń; obraz RGB + false-color SWIR/NIR/G z daty sceny).
  - Runda 1: 220 punktów `shore` → woda 168 / ląd 21 / pomiń 31 (189 etykiet klasowych).
  - Runda 2: 24 „podejrzane" punkty (patrz niżej) + 100 punktów `shore_low` → razem **244 etykiety ludzkie klasowe: 194 woda / 50 ląd**
    (`make check-labels` pokazuje 244). W raporcie RF jest 193/50, bo jeden punkt leży w scenie 2024-09-01, wykluczonej jako uszkodzona (`rf_report.md`: „scena niedozwolona 7" wierszy).
- **Punkty automatyczne** (`auto`: 147 woda, 147 ląd w raporcie): wybrane tam, gdzie woda jest zawsze albo nigdy. Są łatwe i
  „poprawne dla Otsu z konstrukcji", więc służą tylko do uczenia, nie do oceny.
- **Przegląd „w ciemno" (R17).** 24 punkty, które autor oznaczył jako woda, ale ich MNDWI był wyraźnie poniżej progu Otsu (MNDWI − Otsu < −0,3),
  wyglądały spektralnie jak ląd. Zresetowano je i autor ocenił je ponownie nie widząc starej etykiety. Wynik: **20 woda, 4 pomiń, 0 ląd** — zero zmian
  na „ląd", czyli szum etykiet ≈ 0: to nie błędy autora, tylko punkty spektralnie niejednoznaczne (mokre błoto, zalane roślinki).
  **Zastrzeżenie:** przegląd był tylko częściowo „w ciemno" — kolejka sama sugerowała, że punkty są podejrzane (zob. „znane ograniczenia").
- Dlaczego warstwa `shore_low`: w pierwszej rundzie było tylko 21 punktów lądu, za mało na jakąkolwiek miarę lądu (przedział ufności recall 13/21 ≈ 0,41–0,79 był
  szerszy niż różnica RF–Otsu). Dolosowaliśmy 100 punktów w strefie, gdzie woda bywa rzadko (częstość wody 0,05–0,30), **bez patrzenia na Otsu**, żeby Otsu nie decydował, które punkty trafią do testu.

## 3. Wyniki (rf_report.md, tabela A: punkty human `shore`, n = 185, podział po blokach 500 m)

| metoda | OA | BA | κ | recall lądu | recall wody |
|---|---|---|---|---|---|
| wszystko = woda | 0,886 | 0,500 | 0,000 | 0/21 | 1,000 |
| Otsu | 0,714 | 0,755 | 0,264 | 17/21 | 0,701 |
| SCL == 6 | 0,768 | 0,724 | 0,279 | 14/21 | 0,780 |
| **RF (próg 0,5)** | **0,897** [0,845–0,933] | **0,797** | 0,538 | 14/21 | 0,927 |
| RF t* (próg dobrany) | 0,816 | 0,772 | 0,373 | 15/21 | 0,829 |
| RF uczony tylko na auto | 0,827 | 0,799 | 0,410 | 16/21 | 0,835 |

Linia M2 z raportu: *RF = 89,7% [84,5–93,3] → **NOT MET**. Kontekst: wszystko-woda = 88,6%, więc samo OA jest prawie trywialne.*
Mocniej: BA = 0,797 vs Otsu 0,755; κ = 0,538; recall lądu 14/21 (Otsu łapie więcej lądu: 17/21).

Punkty `shore_low` (n = 58: 29 woda + 29 ląd, tabela C), tam gdzie ląd jest częsty: Otsu BA 0,569 (recall lądu 29/29, ale recall wody tylko 0,138),
RF BA 0,638 (ląd 17/29), RF t* BA 0,621 (ląd 24/29). Zbiór łączny `shore ∪ shore_low` (n = 243, ląd 50): Otsu BA 0,768, RF BA 0,756,
RF t* BA 0,773 (ląd 39/50 vs 31/50 dla RF @0,5).

## 4. Dlaczego tak

**Dlaczego samo OA (dokładność) wprowadza w błąd.** Jeśli 88,6% punktów ręcznych to woda, to „wszystko woda" ma 88,6% dokładności i zero wiedzy.
Cel M2 (95%) był ustawiony zanim to zmierzyliśmy. Dlatego główne miary: **BA** (zbalansowana dokładność = średnia z recall wody i recall lądu;
wszystko-woda ma 0,5), **κ Cohena** (dokładność ponad przypadek), recall lądu k/n.

**Przedział Wilsona.** Przedział ufności dla proporcji (np. 14/21), który działa przy małych n i nie wychodzi poza [0,1].
**Bootstrap** dla BA/κ/F1: losujemy wiersze ze zwracaniem i patrzymy na rozrzut; jest optymistyczny, bo punkty są skupione w 50 blokach.

**McNemar.** Porównuje dwie metody na *tych samych* punktach, licząc tylko punkty, w których jedna się myli, a druga nie (b i c).
Uwaga: to porównanie *liczby błędów* (dokładności), w którym dominuje woda (jej jest 9× więcej): wiersze wody b=37, c=0; wiersze lądu b=1, c=4.
Dlatego **p < 0,001 nie znaczy, że RF ma istotnie lepsze BA** — nigdy tak nie twierdzimy; o lądzie mówią wiersze lądu.

**Podział po grupach, nie losowy (przeciek przestrzenny).** Sąsiednie piksele i ten sam dzień są niemal identyczne. Losowy podział wrzuciłby
„bliźniaki" do uczenia i testu, a model wyglądałby na świetny, bo rozpoznaje miejsca, nie wodę. `by_block`: całe bloki 500 m idą do testu;
`by_scene`: całe sceny. Wynik główny to by_block (miejsca, których model nie widział). `StratifiedGroupKFold(5)` dba też, by w każdym foldzie
był ląd ręczny (rozkład 4/3/4/6/4 w pierwszej wersji).

**Próg wody t\* i dlaczego nie 0,5 (R18, R22).** RF zwraca P(woda). Błąd „ląd uznany za wodę" jest niebezpieczny (obniża górną granicę dna,
płycizna wygląda na bezpieczną), więc dopuszczamy tylko progi ≥ 0,5. Zagnieżdżone CV w każdym foldzie wybierało próg t*:
**[0,75; 0,70; 0,80; 0,80; 0,65]** (rf_report) — niestabilne, bo krzywa BA(t) jest płaska (0,773 dla 0,50 → 0,800 dla 0,70 → 0,762 dla 0,90; różnice ≲ 0,01 w przedziale 0,60–0,80).
Dlatego (R22) uśredniamy krzywą z **10 powtórzeń** podziału i bierzemy jej maksimum: **t\* = 0,70** (`rf_metrics.json: water_threshold`).
Odrzuciliśmy „największe t przy remisie": powyżej 0,75 całe sceny zapadają się w „ląd" (2020-11-06 przy 0,80: tylko 40% rdzenia wodą).

**Czy próg nie był dobrany na teście?** Próg jest wybierany *wewnątrz* zbioru uczącego danego foldu (zagnieżdżone CV), a ocena folda idzie na jego
foldzie testowym, którego próg nie widział (test z „szpiegiem" to potwierdza). Wynik główny M2 jest zamrożony na 0,5, a „RF t*" to osobny wiersz.
Wybór finalnego t* = 0,70 na wszystkich wierszach jest już decyzją produktową (konserwatywną), nie wynikiem raportowanym jako dokładność testowa.
Hiperparametry RF są zamrożone z góry (100 drzew, `min_samples_leaf=2`, `class_weight=balanced`, seed 42), więc nie strojono ich na teście.

**Kontrola jakości sceny, QC (R21).** Bez etykiet, z trzech miar: rdzeń jeziora (brzeg odsunięty o 200 m) ma być ≥95% wodą, ≥50% rdzenia znane,
a powierzchnia wody RF ≥ 90% powierzchni Otsu. Oflagowane **3 sceny: 2019-06-15, 2023-09-27, 2024-04-11** (`scenes.json`, `qc_reason: core_water<0.95;rf/otsu<0.90`);
dla nich nie liczymy poziomu z powierzchni. Pozostałe 218 mają powierzchnię RF 12,39–15,01 km² (`classify_stats.csv`, `qc_ok`). Ta lista zmieniała się po poprawkach
(najpierw oczekiwano 7, potem 2, ostatecznie 3 po zmianie t* na 0,70): poprzednie 7 było artefaktem modelu wytrenowanego na uszkodzonej scenie.

**Błąd „błoto południowego brzegu".** Jasne, odsłonięte błoto przy niskiej wodzie RF często uznaje za wodę (P 0,7–0,9). Na `shore_low` RF
łapie ląd 17/29 (przy t*=0,70 24/29), a Otsu 29/29. To **niebezpieczny** kierunek (obniża górne ograniczenie dna). Odpowiedź to nie podnoszenie t*
(zwijałoby całe sceny), tylko decyzja U1 w modelu dna: za wodę uznajemy tylko piksele, gdzie RF **i** Otsu mówią „woda" (M4).

**Cechy (16):** 6 pasm, NDWI, MNDWI, AWEI (2 warianty), NDVI, `mndwi_minus_otsu`, średnia i odchylenie MNDWI z okna 3×3, `doy_sin`/`doy_cos` (pora roku).
Ważność permutacyjna na punktach human (tabela E2): NDWI 0,036 ± 0,057 — reszta w granicach szumu. Pasma i indeksy są skorelowane, więc ważność się rozkłada.

## 5. Pytania, które może zadać prowadzący

**1. Dlaczego nie spełniliście M2 (95%)?**
Zmierzyliśmy: RF ma 89,7% [84,5–93,3] na punktach ręcznych, wszystko-woda ma 88,6%. Cel 95% był zakładany zanim wiedzieliśmy, że punkty
brzegowe są ~89% wodą i spektralnie niejednoznaczne (mokre błoto, zalane roślinki). Nie strojono modelu do liczby. Raportujemy NOT MET
i dajemy rzetelniejsze miary (BA 0,797, κ 0,538, recall lądu 14/21). 4 z 24 „podejrzanych" punktów po ponownym przeglądzie autor uznał za „nie da się ocenić".

**2. Dlaczego MNDWI, a nie NDWI?**
MNDWI = (zielony − SWIR1)/(zielony + SWIR1) lepiej oddziela wodę od zabudowy i gleby, bo SWIR mocniej pochłaniany przez wodę niż NIR. NDWI używa NIR i miesza wodę z roślinnością.
Próg Otsu liczymy na MNDWI. RF dostaje jednak oba indeksy i inne cechy; w tabeli E2 najważniejszy wyszedł akurat NDWI (0,036 ± 0,057, duży rozrzut), więc nie twierdzimy, że MNDWI jest „lepszy" dla RF, tylko że jest standardem dla progu.

**3. Skąd wiesz, że RF nie uczy się na danych testowych?**
Wynik główny to podział po blokach 500 m: każdy punkt oceniamy modelem, który nie widział ani jego, ani jego sąsiadów (ani innych punktów z tego bloku).
Test `test_rf.py` sprawdza rozłączność grup. Gdyby to był losowy podział, bliźniacze piksele zawyżyłyby wynik.

**4. Czy próg t* nie został dobrany na teście?**
Nie: próg wybiera zagnieżdżone CV na części uczącej (R18), a próg końcowy (0,70) z 5-krotnego OOF na wszystkich wierszach; wynik główny M2 zostaje przy
progu 0,5. Wiersz „RF t*" w tabeli pokazuje uczciwy, niezależny od testu efekt progu.

**5. Co oznacza McNemar p < 0,001? Czy RF jest istotnie lepszy od Otsu?**
Tylko tyle, że RF popełnia istotnie mniej *błędów w ogóle* (głównie na wodzie: 37 do 0). Nie wolno z tego wnioskować o BA. Na lądzie Otsu jest lepszy (RF–Otsu: b=1, c=4).

**6. Dlaczego uczycie RF, skoro Otsu łapie więcej lądu?**
Bo Otsu ma recall wody tylko 0,70 (myli wodę z lądem: mętna woda, cienie), a RF 0,93. Do modelu dna używamy obu (RF ∧ Otsu), czerpiąc z RF dobry recall wody, a z Otsu ochronę przed błotem.

**7. Skąd wiesz, że etykiety są dobre?**
Nie wiemy bezwzględnie (nie ma terenowej prawdy). Test: przegląd „w ciemno" 24 podejrzanych punktów dał 0 zmian na „ląd" (20 woda, 4 pomiń). Zastrzeżenie: był tylko częściowo „ślepy".

**8. Co robicie ze scenami, na których RF zawodzi (np. 2019-06-15)?**
QC oflaguje je (3 sceny). Nie wchodzą do krzywej powierzchnia–poziom, a w modelu dna nie czytamy ich masek.
