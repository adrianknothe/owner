# Owner – skaner rynku USA (wersja darmowa)

GitHub Actions co ~10 min (kolejka, gdy skan trwa dłużej) (pn–pt, godziny sesji USA) skanuje ~1400 spółek (S&P 500/400/600 + NASDAQ-100)
z Yahoo Finance, liczy RSI/MACD/SMA/Bollinger/wolumen i publikuje wynik na GitHub Pages.
Nie jest to porada inwestycyjna.

## Uruchomienie (5 kroków, 0 zł)
1. Repo musi być **publiczne** (Settings → General → Danger Zone → Change visibility). Darmowe Pages i darmowe minuty Actions działają tak tylko dla publicznych repo.
2. Wgraj całą zawartość tego folderu do repo (Add file → Upload files). Uwaga: folder `.github` jest ukryty na Macu (Cmd+Shift+. pokazuje ukryte pliki).
3. Settings → Pages → **Source: GitHub Actions**.
4. Zakładka Actions → „Skan rynku” → **Run workflow** (pierwszy skan ~5 min).
5. Strona: https://adrianknothe.github.io/owner/

## Uwagi
- GitHub może opóźniać zaplanowane uruchomienia o kilka–kilkanaście minut.
- Po 60 dniach bez aktywności w repo GitHub wyłącza harmonogram – wystarczy kliknąć „Enable workflow”.
- Dane z Yahoo mogą być opóźnione ~15 min; yfinance to nieoficjalny dostęp.
- Strona jest publiczna (bez hasła) – nie wrzucaj tu nic prywatnego.

## Testy
    python tests/test_core.py                        # wskaźniki, rekomendacja, ocena sygnałów, brak danych
    npm i xlsx && node tests/test_portfolio.js       # wycena walutowa, import XTB, deduplikacja, renderowanie

## Pliki generowane przy skanie (GitHub Pages)
`results.json`, `fundamentals.json`, `signals.json` (archiwum sygnałów), `h/*.json` (historia cen). Archiwa są pobierane z poprzedniego
wdrożenia; błąd sieci przy ich pobraniu przerywa skan, żeby nie nadpisać danych.

## Struktura frontendu
`docs/index.html` (szkielet), `docs/style.css`, `docs/js/00-core.js … 09-start.js` – klasyczne skrypty ładowane po kolei (wspólny zakres globalny).
Testy: `python tests/test_core.py`, `python tests/test_calendar.py`, `node tests/test_portfolio.js`, `node tests/test_features.js` (wymagają `npm i xlsx`).

## Harmonogram
Workflow wywołuje `scripts/market_open.py` (kalendarz NYSE: święta, skrócone sesje, zmiana czasu) i pomija skan poza sesją.
Ręczne uruchomienie (Run workflow) zawsze skanuje.

## Rynki
USA (całość, w tym ETF), Niemcy (DAX, MDAX, SDAX), Wielka Brytania (FTSE 100, FTSE 250), Polska (WIG20, mWIG40, sWIG80). Składy z Wikipedii z zapasowymi listami w `app/universe.py`.
Siła względna jest liczona wobec indeksu danego rynku (SPY, DAX, FTSE 100, WIG20); gdy benchmarku brak, pole jest puste. Ceny z Londynu są w pensach (GBX). Obrót jest przeliczany na USD kursami dziennymi.

## Powiadomienia (Telegram) – opcjonalne
Sekrety repozytorium: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NOTIFY_RULES` (wiersze np. `AAPL >= 200`, `NVDA <= 120`, `signal NVDA AAPL`, `earnings MSFT`).
Reguły są w sekrecie, bo repozytorium i strona są publiczne; stan wysłanych alertów zapisuje tylko skróty (`docs/notified.json`).

## Backtest techniczny
`backtest.py` (workflow „Backtest techniczny”, co tydzień lub ręcznie) zapisuje `docs/backtest.json` do repozytorium. Tylko technika, z obciążeniem przeżywalnością – patrz zastrzeżenia w pliku.

## Dane finansowe i newsy
Przed długim skanem rynku skan odświeża rotacyjnie dane finansowe (do 120 symboli na skan, co 7 dni) i wiadomości (do 150 symboli, co 3 godziny).
Wyniki trafiają do `fundamentals.json` i `news.json` (przenoszone między skanami przez GitHub Pages). W panelu „Status źródeł” widać, ile pobrano.
Zakładka „Długi termin” ocenia spółki z dostępnych danych finansowych (patrz opis metody w aplikacji).

## Symulator portfela papierowego (agent w trybie testowym)
`paper.py` uruchamia się przy każdym skanie: tworzy wirtualne zlecenia z rekomendacji, symuluje wypełnienia (otwarcie następnej sesji + poślizg i koszty), pilnuje stopów/celów i limitów ryzyka (kill switch).
Stan trzyma `docs/paper.json` (przenoszony między skanami przez GitHub Pages). Ustawienia: `paper_config.json` (kapitał, ryzyko na transakcję, limity, `reset_halt`).
Zakładka „Symulator” pokazuje krzywą kapitału vs SPY, pozycje, dziennik decyzji i listę „Do wykonania w XTB” (ręcznie – XTB nie ma API). Testy: `python tests/test_paper.py`.
Ograniczenia: tylko USA w USD, bez dywidend/podatków/FX, dane Yahoo opóźnione; wynik nie dowodzi przewagi przed ~100 transakcjami.

## Portfel XTB i start symulatora

- Plik `moj-portfel-xtb.json` (osobno, **nie wrzucaj go do repozytorium** – to prywatne dane) wczytasz w aplikacji: Portfel XTB → „Wczytaj portfel / kopię (JSON)". Dane zostają tylko w Twojej przeglądarce. Wartości ze zrzutu ekranu to migawka; aktualizuj ją importem Excela z XTB.
- Każda pozycja ma decyzję łączoną (krótki + długi termin): Dokup / Trzymaj / Rozważ redukcję / Sprzedaj. Plany ETF korzystają z sygnałów amerykańskich odpowiedników (proxy).
- Symulator: `paper_config.json` → `start_date` (2026-11-02), kapitał 10 000 USD. Zlecenia realizowane są po otwarciu następnej sesji; zlecenia złożone po otwarciu nie wypełniają się po cenie otwarcia tego samego dnia.

## Jakość i kompletność danych (v6)
- Skan raportuje pokrycie (`diag.cov`, panel boczny): dane finansowe i newsy na spółkę, symbole bez notowań (ponawiane w mniejszych paczkach), nieaktualne notowania.
- Newsy i dane finansowe odświeżane są od najstarszych (rotacja obejmuje cały rynek), moje instrumenty z `extra_tickers.txt` mają pierwszeństwo.
- Spółki poza paczką bieżącego skanu korzystają z zapisanych wcześniej newsów i danych finansowych.
- Kontrola jakości: skok ceny >35% (split/błąd), brak obrotu 5 sesji, nieaktualna ostatnia sesja → rekomendacja kupna jest blokowana i oznaczona.
- Daty wyników kwartalnych sprawdzane są także dla wszystkich spółek z planem wejścia.
- Harmonogram `*/10`: GitHub nie gwarantuje terminów (opóźnienia bywają duże), a Yahoo i tak opóźnia ceny ~15 min – realna świeżość to zwykle 10–25 min.

## Symulator: wejścia w trakcie sesji (v1.1)
- Zlecenie z poprzedniej sesji wypełnia się wstępnie po dzisiejszym otwarciu (cena otwarcia jest znana od otwarcia); wieczorem pozycja jest potwierdzana zakończoną świecą, bez dubla. Zlecenia utworzone po otwarciu nadal czekają do następnej sesji.
- Test A/B: każda rekomendacja „kupuj teraz” z trwającej sesji jest zapisywana z ceną z chwili sygnału (A) i porównywana z wejściem po następnym otwarciu (B) według tych samych reguł stopu i celów. Wyłączniki: `live_fill`, `live_test` w `paper_config.json`.

## Analityka i newsy (v6.1)
- Nowe składniki oceny: momentum 12-1 (percentyl w obrębie rynku, 10%) i siła sektora (mediana siły względnej 3M, 5%); nie liczą się do „zgodności źródeł”, bo wynikają z cen. Wagi nie były kalibrowane historycznie – backtest dotyczy samej techniki.
- Nowe ostrzeżenia: wysoki udział krótkiej sprzedaży (>15%), beta >1,8, ATR >6% ceny, VIX >25.
- Newsy spółek: Yahoo + Google News (nazwa/symbol) + zapytanie o katalizatory (analitycy, wyniki, sprawy prawne, M&A) + polskie źródła dla GPW; rozszerzony słownik fraz. Newsy rynkowe: CNBC, MarketWatch, Yahoo Finance, Nasdaq, Seeking Alpha, Bankier.pl (panel statusu pokazuje, które źródła odpowiedziały).
- Telefon: naprawiony układ (na wąskich ekranach treść zajmowała tylko ~60% szerokości), 2 kolumny kafelków, węższe tabele w symulatorze.

## Pozycje w stracie (v6.2)
Zakładka „Portfel XTB”: dla akcji ze stratą ≥10% panel „Sprawdzian tezy” liczy 8 warunków (trend SMA200/SMA50, momentum 12-1, siła względna, fundamenty, cena docelowa analityków, bilans newsów, krótki termin), pokazuje wymagany wzrost do ceny zakupu i szansę jego osiągnięcia w 12 mies. (symulacja bez dryfu – nie prognoza), alternatywy ze skanera oraz ogólną notę podatkową (Polska). Decyzja zależy od przyszłych przesłanek, nie od ceny zakupu. Przy mniej niż 5 dostępnych warunkach ocena jest wstrzymana.
