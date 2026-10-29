# Owner – skaner rynku USA (wersja darmowa)

GitHub Actions co ~20 min (pn–pt, godziny sesji USA) skanuje ~1400 spółek (S&P 500/400/600 + NASDAQ-100)
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
