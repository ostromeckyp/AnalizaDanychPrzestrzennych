# M4 — Model dna: jak z 218 zdjęć robimy mapę „od jakiej rzędnej wody dno jest pokryte"

Po ludzku: dla każdego piksela (10 × 10 m) szukamy dwóch liczb. **z_min** = „na pewno suche przy tym poziomie wody" (najwyższy poziom, przy którym widzieliśmy tam ląd)
i **z_max** = „na pewno mokre" (najniższy poziom, przy którym widzieliśmy tam wodę). Dno leży gdzieś pomiędzy. Z tego aplikacja policzy, gdzie przy danym
poziomie wody jest bezpiecznie głęboko, a gdzie płytko. Liczby: `data/processed/model/all/model_meta.json`, `logs/07_bottom_model.log` (ostatni przebieg 2026-10-27 18:33, po poprawce R25).

## 1. Co powstało (pliki)

W `data/processed/model/{all,pre_flood,post_flood}/` (okresy z `config.yaml → periods`):

| plik | zawartość |
|---|---|
| `bottom_zmin.tif`, `bottom_zmax.tif` | granice dna, float32, poszerzone o niepewność poziomu σ (NaN = brak granicy) |
| `bottom_z.tif`, `bottom_unc.tif` | środek przedziału i jego pół-szerokość |
| `obs_count.tif`, `conflict_count.tif` | liczba obserwacji i liczba obserwacji sprzecznych z progiem dna (uint16, 65535 poza AOI) |
| `bottom_flags.tif` | bity: 1 zawsze woda, 2 zawsze ląd, 4 sprzeczności, 8 woda C pominięta (informacyjna), 16 nierozstrzygnięty, 255 poza AOI |
| `model_meta.json` | liczba scen, zakres poziomów, `flags`, `nan_semantics`, `evidence`, `version`, sha modelu RF |
| `data/processed/qc/bottom_*_{okres}.png` | mapy kontrolne |

Skrypt: `07_bottom_model.py`, logika: `mielizna/bottom.py` (`combine_evidence`, `select_scenes`, `compute_bounds`, `write_model`, `read_model`).

## 2. Metoda krok po kroku

1. **Które sceny.** Tylko `qc_ok` z poziomem h_t: **218 scen** (153 B, 63 C, 2 R; `model_meta.json`), poziomy 192,90–197,92 m. Okresy:
   `pre_flood` 2017-01-01..2024-08-31 = 155 scen (96 B, 59 C; poziomy 192,90–196,79), `post_flood` 2024-09-30.. = 59 scen (53 B, 4 C, 2 R; poziomy 193,81–197,92),
   `all` = wszystko. Wrzesień 2024 (powódź Boris) jest tylko w `all`; serwujemy `all`.
2. **Dowód „woda" w jednej scenie (decyzja U1).** Woda tylko tam, gdzie **RF ∧ Otsu** (obie maski mówią „woda"); ląd, jeśli **którakolwiek** maska pokazuje ląd (RF=ląd *lub* Otsu=ląd, także gdy druga ma 255);
   w pozostałych przypadkach (np. woda + 255) = 255, nieznane (`combine_evidence`, R25).
3. **Linia wodna dla piksela.** Piksel widział serię (poziom h, woda/ląd). Gdyby klasyfikacja była bezbłędna, istniałby próg dna: ląd poniżej, woda powyżej.
   W praktyce są pomyłki, więc szukamy progu **minimalizującego liczbę sprzecznych obserwacji** (estymator liczący, bez wag). Liczba sprzeczności = `n_conflict`.
4. **Remisy → strona ostrożna.** Gdy kilka progów daje tę samą liczbę błędów, bierzemy **obwiednię** wszystkich minimalizatorów, więc przy remisach przedział się **poszerza**:
   z_min może tylko spaść albo zostać (ląd uznajemy tylko dla poziomów poniżej najmniejszego minimalizatora k_min), a z_max może tylko wzrosnąć albo zostać
   (woda tylko dla poziomów ≥ największego minimalizatora k_max). Efekt: strefy „ryzykowne" zamiast „bezpieczne".
5. **Poszerzenie o σ poziomu.** Każda obserwacja ma poziom h ± σ; bierzemy z_min = max(h − σ) po spójnym lądzie i z_max = min(h + σ) po spójnej wodzie.
   Nie istnieje piksel ze z_min > z_max (niezmiennik sprawdzany w `07`: 0 naruszeń z 42 096).
6. **Woda ze scen C nigdy nie jest liczona (R24) — ani sama, ani z innymi; ląd ze scen C jest liczony.** Obserwacje *wody* ze scen C (poziom z krzywej, błąd skorelowany w roku, w paśmie 195–198 m skłonny do zaniżenia)
   traktujemy jako 255 (nieznane) zarówno przy wyborze progu, jak i przy z_max. *Ląd* z C zostaje. Flaga 8 oznacza, że piksel miał taką wodę C — to **informacja, nie ostrzeżenie** (57,7% pikseli AOI: 144 538 z 250 584, `counts.c_water_ignored_px`).

### Dlaczego RF ∧ Otsu jest bezpieczniejsze (dowód, R25)
Niebezpieczny błąd to „ląd uznany za wodę": obniża z_max i płycizna wygląda na głęboką. Reguła łączenia: **woda wymaga obu masek**, a **ląd wystarczy z jednej**.
W porównaniu z samym RF (RF-only) zmiana obserwacji może więc być tylko: woda → ląd, woda → nieznane albo nieznane → ląd (woda nie może się pojawić tam, gdzie RF mówił „ląd" lub „nieznane").
Każda taka zmiana albo dodaje obserwację lądu (składnik błędu, który **nie rośnie ze wzrostem progu**), albo usuwa obserwację wody — w obu przypadkach największy minimalizator
może się tylko podnieść, a zbiór spójnej wody tylko zmniejszyć, czyli **surowe z_max nie może spaść względem RF-only**. Test własności `test_adding_land_never_lowers_zmax` sprawdza ten mechanizm losowo,
a test R25 (`r25_combined_never_lowers_zmax_vs_rf_only`) sprawdza go dla samej reguły łączenia; w `07` jest twarda asercja na danych: **0 pikseli ze z_max niższym niż RF-only** (`07_bottom_model.log`, pkt 4).
Zastrzeżenie: dowód dotyczy surowych z_max_raw; po poszerzeniu o σ wymaga σ_C ≥ σ_nie-C (spełnione), a woda C i tak jest ignorowana (R24).
**Historia (uczciwie):** wcześniejszy pomiar „z_max niżej o >5 cm na 0,2% px" brał się stąd, że Otsu=255 wymazywało ląd z RF (ląd → nieznane); R25 to naprawił i teraz jest 0.
Ten sam argument obowiązuje dla R24 (usunięcie obserwacji wody).

## 3. Liczby z tego przebiegu (`07_bottom_model.log`, okres `all`, 141 652 px jeziora)

- **Niezmiennik** z_min ≤ z_min_raw < z_max_raw ≤ z_max: **0 naruszeń** z 42 189 pikseli z przedziałem.
- **Sprzeczności:** `n_conflict_px` = 58 412 = **23,3%** obserwowanych px AOI (32,4% px jeziora); ≥3 sprzeczności: 9,3%; stosunek > 0,1: 2,4%; p99 = 37.
- **Zatoka W vs E (kolumna < 330):** W: sprzeczności w 53,0% px, stosunek > 0,1 w 8,8%, „zawsze woda" 64,1%; E: 27,6%, 1,8%, 76,4%. (Plamistość zachodniej płytkiej zatoki.)
- **Klasy w jeziorze:** zawsze woda 104 886, zawsze ląd 5 365, przedział 31 401, nierozstrzygnięte 0. Całe AOI (`model_meta.json`): obserwowane 250 421 z 250 584, przedział 42 096, zawsze woda 104 920, zawsze ląd 103 405.
- **Rdzeń jeziora „zawsze woda":** 92,3% (próg asercji ≥ 85%).
- **Głębokość wg odległości od brzegu (mediana z; zawsze woda):** 0–20 m: 195,72 (3,5%); 20–50: 193,88 (26,7%); 50–100: 193,34 (64,1%); 100–200: 193,20 (68,7%); 200–400: 193,04 (84,2%). Monotonicznie (asercja z tolerancją 0,05 m).
- **Wpływ U1:** względem samego RF z_max wyższe o >5 cm na 22,4% px (średnio +0,602 m wśród podniesionych), niższe na **0,0%** (0 pikseli, asercja w `07`); 42,4% z podniesionych leży na południu (wiersze > 450), czyli tam, gdzie jest błoto.
- **Okresy przed i po powodzi** (8 352 px z przedziałem w obu): mediana Δz = post − pre = **−0,345 m**; pasmo pre < 195 m: −0,175 (26,2% px z |Δz| > suma niepewności); 195–196 m: −0,440 (68,4%); ≥ 196 m: +0,005 (49,2%).
  **Zastrzeżenie:** post_flood nie widział poziomów poniżej 193,81 m, więc nic nie mówi o głębszym dnie. To jest wejście do decyzji, który model serwować; **tu jej nie podjęto**.
- **Efekt C:** px ze zmienionym z_max względem „C jak każda inna scena": 6 599 (diagnostyka).

## 4. Znane ograniczenia M4

- **Plamistość zatoki W** (sprzeczności w 53% px): płytka woda, mieszane odbicia; model jest tam zachowawczy. Nie stroiliśmy.
- **Brak porównania z mapą KŻ**: głębokości z mapy wymagają georeferencji (K1), plan 4. Do tego czasu nie wiemy, jak model ma się do głębokości rzeczywistych.
- **Żwirownie w zachodniej zatoce:** w danych widać wyspy na zachodzie; warstwa ostrzeżeń (obrys żwirowni z mapy KŻ) odłożona do planu 4.
- **Brak granicy dla „zawsze woda":** z_max ≈ 192,90 + σ ≈ 193,05 m. Dla poziomu h, przy którym h − głębokość − margines < ~193,05, nie ma strefy „bezpiecznej", a frontend musi napisać
  „dno poniżej 192,9 m nie było obserwowane" (najniższy poziom z jakiego mamy sceny).
- **Flaga 8 to nie ostrzeżenie** (informacyjna, 57,7% AOI). NaN w z_min = −∞, NaN w z_max = +∞ (`nan_semantics`).
- **SW płat roślinny** (z_max 196–197 m) nie został jeszcze sprawdzony z ortofotomapą; do weryfikacji w planie 4.

## 5. Pytania, które może zadać prowadzący

**1. Jak policzyłeś głębokość z samych zdjęć satelitarnych?**
Nie liczymy głębokości, tylko rzędną dna *względem* poziomu wody. Obserwujemy, przy jakich poziomach wody (znanych z komunikatów/krzywej)
dany piksel był wodą, a przy jakich lądem. Tam, gdzie widzieliśmy ląd przy 195,0 m i wodę przy 195,6 m, dno leży między nimi.

**2. Skąd wiesz, że RF ∧ Otsu jest bezpieczniejsze?**
Bo błąd groźny to „ląd jako woda". Woda wymaga obu masek, a ląd wystarczy z jednej, więc względem samego RF zmiany to tylko woda → ląd/nieznane lub nieznane → ląd, a to z dowodu wyżej nigdy nie obniża z_max.
Potwierdza to dane (z_max niżej na 0 px, wyżej o >5 cm na 22,4%). Na etykietach mamy tylko liczbę **historyczną** ze starszego modelu (próg 0,6, ledger Task 8, nieprzeliczoną dla obecnego modelu t = 0,70): RF∧Otsu łapało ląd 47/50 wobec 36/50 dla RF.
Cena: woda traci recall (0,61 na trudnych punktach brzegowych), więc przedziały są szersze.

**3. Dlaczego sceny C nie mogą ustalać wody?**
Poziom C pochodzi z krzywej z błędem 0,49 m, skorelowanym w obrębie roku, a w paśmie 195–198 m poziom C bywa zaniżony o 0,1–0,4 m — czyli dno wyglądałoby na głębsze. Nie ma tu symetrii: błąd w jedną stronę jest groźny. Usunięcie wody C może tylko podnieść z_max (konserwatywnie).

**4. Co się dzieje z pikselem zawsze zalanym?**
Nie ma żadnego lądu → `z_min` = NaN (= −∞), flaga 1 „zawsze woda", `z_max` skończone (ok. 193,05 m, bo najniższy poziom, jaki widzieliśmy, to 192,90 + σ).
Strefa „za płytko" nigdy się dla niego nie włączy, ale „bezpiecznie" tylko do poziomu, jaki zaobserwowaliśmy.

**5. A piksel zawsze suchy?**
Brak wody → `z_max` = NaN (= +∞), flaga 2 „zawsze ląd"; nigdy „bezpiecznie".

**6. Dlaczego 23% pikseli ma sprzeczności? Czy model jest zepsuty?**
Sprzeczność to obserwacja niezgodna z progiem dna (np. woda przy niskim poziomie, ląd przy wysokim) — błąd klasyfikacji albo chwilowe zjawisko (zakwit, cień, zalana roślinność).
Estymator jest na to odporny (minimalizuje liczbę sprzeczności), a liczba jest zapisana jako `conflict_count.tif`. Skupiają się na brzegach, wyspach i w zatoce W. Raportujemy, nie stroimy.

**7. Dlaczego trzy okresy modeli?**
`pre_flood` (do 2024-08-31) pozwala porównać z mapą KŻ z tamtego czasu; `post_flood` pokazuje dno po powodzi (mediana −0,35 m względem pre w obszarze wspólnym), ale nie widzi poziomów < 193,81 m. Serwujemy `all`; zmiana to decyzja na później.

**8. Czy komunikat o niskim poziomie z innej godziny niż zdjęcie nie psuje progu dna?**
Błąd poziomu o kilka cm (kilka godzin) wchodzi do σ = 0,15 m (B), a model poszerza przedział o σ (k = 1). To dlatego `z_min`/`z_max` są szersze niż samo h.

**9. Co jeśli na brzegu było lód albo mgła?**
Lód: wykluczono 14 dat po przeglądzie wzrokowym (M1); razem z uszkodzoną 2024-09-01 daje to 15 `exclude_dates`. Mgła i chmury: SCL + maska poszerzona o 2 px = 255, czyli nieznane, nigdy „ląd".
