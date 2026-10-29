import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import pandas as pd
from market_open import should_run

T = lambda s: pd.Timestamp(s, tz="UTC")


def test_calendar_eu():
    from market_open import CALENDARS
    assert "XETR" in CALENDARS
    assert should_run(T("2026-10-29 07:30"))                    # NYSE zamknięta, Niemcy/UK otwarte
    assert not should_run(T("2026-10-29 03:00")) and not should_run(T("2026-10-29 22:30"))
    assert should_run(T("2026-11-02 09:00")) and not should_run(T("2026-11-01 09:00"))   # niedziela


def test_calendar():
    N = ("NYSE",)
    assert should_run(T("2026-10-29 15:00"), calendars=N)            # czwartek, sesja
    assert not should_run(T("2026-10-31 15:00"))                     # sobota
    assert not should_run(T("2026-11-26 15:00"), calendars=N)        # Thanksgiving (NYSE)
    assert not should_run(T("2026-11-26 19:00"))                     # i po sesjach europejskich
    assert should_run(T("2026-11-02 14:45"), calendars=N) and not should_run(T("2026-11-02 13:20"), calendars=N)   # po zmianie czasu otwarcie 14:30 UTC
    assert should_run(T("2026-11-27 18:45"), calendars=N) and not should_run(T("2026-11-27 19:30"), calendars=N)   # skrócona sesja (zamknięcie 18:00 UTC)


if __name__ == "__main__":
    test_calendar(); test_calendar_eu(); print("ok calendar")
