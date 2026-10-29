"""Czy uruchamiać skan? 'true', gdy otwarta jest którakolwiek z giełd: NYSE, XETRA (Niemcy), LSE (UK), GPW (Polska)
(od 30 min przed sesją do 60 min po niej). Kalendarze uwzględniają święta, skrócone sesje i zmianę czasu."""
import os

import pandas as pd
import pandas_market_calendars as mcal

CALENDARS = ("NYSE", "XETR", "LSE", "XWAR")


def should_run(now=None, before=30, after=60, calendars=CALENDARS):
    now = now or pd.Timestamp.now(tz="UTC")
    for name in calendars:
        try:
            sch = mcal.get_calendar(name).schedule(start_date=(now - pd.Timedelta(days=2)).date(), end_date=now.date())
        except Exception:
            continue  # nieznany kalendarz nie blokuje pozostałych
        if any(r.market_open - pd.Timedelta(minutes=before) <= now <= r.market_close + pd.Timedelta(minutes=after) for r in sch.itertuples()):
            return True
    return False


if __name__ == "__main__":
    n = os.getenv("NOW")
    print("true" if should_run(pd.Timestamp(n, tz="UTC") if n else None) else "false")
