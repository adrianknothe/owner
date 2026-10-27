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
