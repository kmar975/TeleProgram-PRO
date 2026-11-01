# 📺 TeleProgram PRO - Inteligentny Ranking Filmowy TV

Zaawansowana, nowoczesna aplikacja okienkowa (GUI v3.0) w Pythonie zaprojektowana w stylistyce **Windows 11 Fluent / Obsidian Dark**, wyposażona we **własny algorytm rankingowy filmów (Indeks Jakości 0–100 pkt)** oparty na **średniej ważonej Bayesa**, analizie nagród i trwałym cache na dysku (`movies_cache.json`).

---

## 🏆 Jak działa Algorytm Rankingowy (Indeks Jakości 0–100 pkt)?

Zwykłe sortowanie po średniej ocenie jest zawodne (niszowy film z oceną `8.5` od 30 osób wyprzedziłby arcydzieło z oceną `8.8` od 2 milionów widzów). TeleProgram PRO stosuje matematyczny model wielokryterialny:

### 1. Średnia ważona Bayesa ($WR$ – Weighted Rating):
Dokładnie ten sam wzór, z którego korzysta **IMDb** przy tworzeniu listy *Top 250*:

$$WR = \left( \frac{v}{v + m} \cdot R \right) + \left( \frac{m}{v + m} \cdot C \right)$$

- $R$ – średnia ocena filmu (np. `8.7`)
- $v$ – liczba ocen / głosów (np. `2 800 000`)
- $m$ – próg wiarygodności głosów ($m = 3000$)
- $C$ – bazowa ocena przeciętnego filmu ($C = 6.0$)

### 2. Zaawansowana Hierarchia Prestiżu Nagród (Tier List: od -6.0 do +20.0 pkt):
Aby wybitne dzieła oraz polskie kino nie były krzywdzone, zastosowano 5-poziomową hierarchię prestiżu z rozróżnieniem **wygranej (100% wagi)** vs. **nominacji (35% wagi)** oraz malejącą korzyścią za kolejne statuetki:

- **🏆 Poziom S (Światowy prestiż):** Waga bazowa: **+10.0 pkt** (nominacja: **+3.5 pkt**)
  - *Oscar (Nagroda Akademii Filmowej)*, *Złota Palma w Cannes*, *Złoty Lew w Wenecji*, *Złoty Niedźwiedź w Berlinie*.
- **🥇 Poziom A (Wysoki prestiż międzynarodowy):** Waga bazowa: **+6.0 pkt** (nominacja: **+2.0 pkt**)
  - *Złoty Glob (Golden Globe)*, *BAFTA (Wielka Brytania)*, *Europejska Nagroda Filmowa (EFA)*, *Cezar (Francja)*.
- **🦅 Poziom B (Kluczowe nagrody polskie):** Waga bazowa: **+6.0 pkt** (nominacja: **+2.0 pkt**)
  - *Polskie Nagrody Filmowe Orły*, *Złote Lwy (Festiwal w Gdyni)*.
  - *Wysoka waga ratuje wartościowe polskie kino, które na zagranicznych portalach ma mniej głosów.*
- **🏅 Poziom C (Nagrody gatunkowe i festiwale kina niezależnego):** Waga bazowa: **+3.5 pkt** (nominacja: **+1.0 pkt**)
  - *Sundance*, *Saturn (Sci-Fi, Fantasy, Horror)*, *Emmy*.
- **🍓 Poziom Ujemny (Antynagrody):** Waga: **-6.0 pkt**
  - *Złota Malina (Razzie)*, polski *Wąż*. Wyświetla ostrzegawczą odznakę `🍓 Złota Malina` i obniża pozycję filmu.
- **👑 Premia za kategorię główną (+3.0 pkt):**
  - Dodatkowe punkty za wygraną lub nominację w kategoriach *Najlepszy Film*, *Najlepsza Reżyseria* lub *Najlepszy Scenariusz*.
- **Mnożnik za liczbę statuetek z malejącą korzyścią:**
  - Pierwsza statuetka daje 100% wagi bazowej, każda kolejna dodaje od +0.8 do +1.5 pkt (maksymalnie do +20.0 pkt).

### 3. Wiek filmu (Nowość vs. Klasyk):
- **🆕 Nowość** (premiery z lat 2024–2026): **+4.5 pkt**
- **💎 Kultowy Klasyk** (filmy sprzed >20 lat z wysoką oceną $WR \ge 7.2$): **+4.0 pkt**

### 4. Komfort oglądania (Kanał bez reklam):
- **📺 Bez reklam** (emisja w HBO, Canal+, Ale kino+, TVP Kultura, TVP Historia itd.): **+2.5 pkt** za brak uciążliwych przerw reklamowych.

### 5. Ostateczny wzór na wynik:
$$\text{Indeks Jakości (0–100 pkt)} = (WR \times 8.8) + \text{Punkty za Nagrody} + \text{Bonus za Wiek} + \text{Bonus Kanału}$$

---

## 🌐 Źródła ocen i trwały cache (`movies_cache.json`)

1. **Działa w 100% od razu bez kluczy API:**
   - Wbudowana baza wiedzy dla klasyków i popularnych filmów.
   - Analizator wyrażeń regularnych przeszukujący opisy Telemana pod kątem nagród.
   - Oceny Filmwebu powiązane z podstronami Telemana.
2. **Opcjonalne API OMDb / TMDB:**
   - Przycisk `⚙️ Klucze API (OMDb / TMDB)` w oknie aplikacji pozwala wkleić darmowe klucze API.
3. **Trwały cache na dysku (`movies_cache.json`):**
   - Raz oceniony film jest trwale zapisywany na dysku – kolejne uruchomienia programu działają w czasie rzeczywistym (0 ms opóźnienia).

---

## 🖥️ Nowe kolumny w tabeli Treeview

| Ranking (pkt) | Godz. | Kanał | Tytuł pozycji | Ocena (Głosy) | Nagrody filmowe |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **🥇 94.3 pkt** | 20:00 | TVN 7 | Skazani na Shawshank | ⭐ 9.3 (2.9M) | 🏆 7 nom. do Oscara |
| **🥈 85.6 pkt** | 21:00 | HBO | Diuna: Część druga | ⭐ 8.5 (520k) | 🏆 2 Oscary |
| **🥉 76.8 pkt** | 20:10 | TVP Kultura | Anatomia upadku | ⭐ 7.7 (165k) | 🌴 Złota Palma |
| **54.7 pkt** | 22:05 | Polsat | Terminator: Mroczne przeznaczenie | ⭐ 6.2 (190k) | — |

> [!NOTE]
> Kolumna **Nagrody filmowe** wyświetla wyłącznie rzeczywiste nagrody i statuetki (Oscary, Cannes, Złote Globy, Orły, Złote Lwy, Złote Maliny itd.). Dodatkowe premie za wiek filmu (Nowość / Klasyk) oraz emisję bez reklam są przejrzyście prezentowane w dolnej karcie szczegółów (`Premie rankingowe`) oraz w wyeksportowanym pliku CSV.

- Przyciski szybkiego sortowania: **`[ 🏆 Sortuj wg Rankingu ]`** oraz **`[ ⏰ Sortuj wg Godziny ]`**.

- **Podwójny widok prezentacji danych (przełączany 1 kliknięciem):**
  - **📋 Tabela PRO (`ttk.Treeview`):** Ultra-szybka, sortowalna tabela z przestronnymi wierszami (30px), wyróżnieniem filmów w kolorze ciepłego bursztynu, estetycznymi nagłówkami i wskaźnikami sortowania ▲/▼.
  - **🎴 Karty filmowe (Netflix / Feed style):** Interaktywne karty dla każdej pozycji z pigułkami godziny, stacji, kategorii, dużym tytułem, opisem oraz bezpośrednimi przyciskami akcji.

- **Pasek wskaźników KPI (Metrics Bar na górze):**
  - Wizualne pigułki z dynamicznie aktualizowanymi liczbami: `🎬 Filmy: X`, `📡 Stacje: Y`, `⏰ Zakres: Od – Do`.

- **Wyszukiwarka stacji w panelu bocznym:**
  - Pole `🔍 Filtruj stacje na liście...` pozwala natychmiast znaleźć dowolny kanał z listy 20+ stacji.

- **Grupy stacji jednym kliknięciem:**
  - `⭐ Domyślne 20` – przywraca 20 głównych polskich stacji.
  - `Tylko TVP` – zaznacza wyłącznie stacje Telewizji Polskiej.
  - `Komercyjne` – zaznacza wyłącznie stacje komercyjne (Polsat, TVN, TV4, Puls itd.).
  - `Zaznacz wszystkie` / `Odznacz`.

- **Szybkie presety godzinowe:**
  - `🌙 Prime Time (20:00 - 23:30)`
  - `☀️ Cały dzień (00:00 - 23:59)`
  - `🌆 Popołudnie (15:00 - 20:00)`
  - `⏰ Od teraz (+3h)` – dynamicznie wylicza bieżącą godzinę i dodaje 3 godziny.

- **Karta Podglądu (Hero Sheet):**
  - Duży tytuł z ikoną 🎬 / 📺.
  - Pigułki metadanych (stacja, godzina, gatunek, źródło).
  - Przycisk **`🎬 Szukaj zwiastuna`** – automatycznie otwiera wyszukiwanie zwiastuna na YouTube.
  - Przycisk **`🌐 Otwórz w teleman.pl`** – podgląd w serwisie.
  - Przycisk **`📋 Kopiuj`** – kopiowanie do schowka.

- **Dynamiczne motywy:**
  - Przełącznik ciemnego (*Dark Obsidian*) i jasnego (*Clean Apple/Fluent*) motywu.

- **Wybór stacji (checkboxy):**
  - **Domyślnie zaznaczonych jest 20 stacji:**
    1. TVP Kultura
    2. TVP Historia
    3. TVP Dokument
    4. TVP Nauka
    5. TVP Polonia
    6. Nowa TV
    7. WP
    8. TVP 1
    9. TVP 2
    10. Polsat
    11. TVN
    12. TV4
    13. TV Puls
    14. TVN7
    15. Puls2
    16. TV6
    17. Super Polsat
    18. Antena HD
    19. Stopklatka TV
    20. Fokus TV
  - Obsługa dodatkowych stacji (Polsat Film, TVN Fabuła, TVP Seriale, HBO, Canal+ itp.).
  - Szybkie przyciski wyboru: *Domyślne 20*, *Zaznacz wsz.*, *Odznacz*.

- **Wielopoziomowe źródła danych (Fallback):**
  - Wszystkie 20 stacji jest dostępne i pobierane z **teleman.pl**.
  - Aplikacja posiada wbudowany automatyczny mechanizm zapasowy (**tv.wp.pl**) – jeśli jakikolwiek kanał nie zostanie znaleziony lub zwróci błąd, scraper automatycznie pobierze jego ramówkę ze źródła zapasowego bez przerywania pracy aplikacji.

- **Filtr przedziału godzinowego:**
  - Możliwość wpisania dowolnego przedziału, np. **20:00 – 23:30** (domyślnie).
  - Elastyczny parser czasu (akceptuje formaty `20:00`, `20`, `20.30`, itp.).
  - Obsługa przedziałów przechodzących przez północ (np. `22:00 – 02:00`).
  - Szybkie presety jednym kliknięciem: *🌙 Wieczór (20:00–23:30)*, *☀️ Cały dzień*, *🌆 Popołudnie (15:00–20:00)*.

- **Filtr pozycji filmowych:**
  - Przełącznik **"🎬 Tylko pozycje będące filmami"** – natychmiastowo filtruje repertuar do filmów fabularnych i kinowych (zgodnie z klasyfikacją teleman.pl).

- **Wyszukiwarka tekstowa na żywo:**
  - Pole wyszukiwania fraz (tytuł, opis, gatunek, reżyser, obsada) filtrujące wyniki w czasie rzeczywistym bez ponownego odpytywania serwisu.

- **Czytelna i interaktywna tabela Treeview:**
  - Kolumny: **Godzina**, **Stacja**, **Kategoria**, **Tytuł**, **Gatunek**, **Opis fabuły**.
  - Sortowanie kolumn: kliknięcie nagłówka sortuje po danej kolumnie rosnąco/malejąco (ze wskaźnikami ▲/▼).
  - Wyróżnienie wierszy filmowych specjalnym akcentem kolorystycznym.

- **Karta podglądu szczegółów pozycji:**
  - Po zaznaczeniu wiersza wyświetlany jest pełny opis fabuły, szczegóły produkcji oraz gatunek.
  - Przycisk **"🌐 Otwórz w teleman.pl"** (oraz dwuklik na wierszu) otwiera podstronę programu w przeglądarce.
  - Przycisk **"📋 Kopiuj opis"** oraz menu pod prawym przyciskiem myszy.

- **Eksport do pliku CSV:**
  - Zapis przefiltrowanych wyników do pliku `.csv` ze standardowym kodowaniem UTF-8-sig (polskie znaki w arkuszu MS Excel).

- **Wybór dnia emisji:**
  - Możliwość sprawdzenia ramówki na dziś, jutro oraz kolejne dni tygodnia.

- **Wielowątkowość (Non-blocking GUI):**
  - Pobieranie danych z `teleman.pl` odbywa się asynchronicznie w tle (`ThreadPoolExecutor`), dzięki czemu interfejs użytkownika nigdy się nie zacina.

- **Wybór motywu:**
  - Przełącznik motywów: Ciemny (*Dark*), Jasny (*Light*), Systemowy.

---

## 🚀 Wymagania i instalacja

1. **Wymagania:**
   - Python 3.9+
   - Pakiety: `customtkinter`, `requests`, `beautifulsoup4`

2. **Instalacja zależności:**
   ```bash
   pip install -r requirements.txt
   ```

---

## 🖥️ Uruchomienie aplikacji

### Sposób 1: Jednym kliknięciem (Windows)
Wystarczy dwukrotnie kliknąć plik:
- **`run.bat`** lub **`Uruchom.bat`**

### Sposób 2: Przez wiersz poleceń
```bash
python main.py
```

---

## 📁 Struktura projektu

- `main.py` – Główny plik startowy aplikacji.
- `gui.py` – Nowoczesny interfejs graficzny w CustomTkinter i ttk.Treeview, obsługa widoków (Tabela PRO / Karty), sortowania i filtrów.
- `scraper.py` – Silnik pobierania i parsowania ramówki ze stacji teleman.pl z fallbackiem do tv.wp.pl.
- `ranker.py` – Moduł algorytmu rankingowego (Indeks Jakości 0–100 pkt, wzór Bayesa, Tier List nagród, obsługa API OMDb/TMDB).
- `movies_cache.json` – Trwały dyskowy cache ocen, nagród i punktacji filmów.
- `api_config.json` – Plik konfiguracyjny z kluczami API OMDb/TMDB.
- `run.bat` / `Uruchom.bat` – Skrypty szybkiego uruchomienia pod Windows.
- `requirements.txt` – Zależności Pythona.
