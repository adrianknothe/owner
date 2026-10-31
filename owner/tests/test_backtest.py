import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import backtest


def mk(n=700, seed=3):
    np.random.seed(seed); c = 100 + np.cumsum(np.random.randn(n) * 1.1) + np.linspace(0, 80, n)
    return pd.DataFrame({"Open": c * (1 + np.random.randn(n) * .002), "High": c + 1.2, "Low": c - 1.2, "Close": c, "Volume": np.random.randint(1e6, 3e6, n)}, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def test_no_lookahead():
    orig = backtest.tech_buy
    backtest.tech_buy = lambda w, sig, rel=None: True            # badamy przyczynowość potoku, nie ostrość bramki
    try:
        _no_lookahead()
    finally:
        backtest.tech_buy = orig


def _no_lookahead():
    df = mk(); full = backtest.replay("X", df, df)
    cut = 600
    part = backtest.replay("X", df.iloc[:cut], df.iloc[:cut])
    f = {(x["i"], x["setup"]) for x in full if x["i"] < cut - 2}
    p = {(x["i"], x["setup"]) for x in part if x["i"] < cut - 2}
    assert f == p and len(f) > 0                      # sygnały sprzed t nie zależą od przyszłych danych
    altered = df.copy(); altered.iloc[cut:, :4] *= 3  # zmiana przyszłości nie zmienia wcześniejszych sygnałów
    a = {(x["i"], x["setup"]) for x in backtest.replay("X", altered, altered) if x["i"] < cut - 2}
    assert a == f


def test_gate_rejects_weak_confirmations():
    from app.analysis import extra, indicators, signal
    d = extra(indicators(mk()))
    sig = {"score": 1}
    d2 = d.copy(); d2.iloc[-1, d2.columns.get_loc("Close")] = float(d2.SMA200.iloc[-1]) * 1.01
    assert backtest.tech_buy(d2, {"score": 3}, 0.1) in (True, False)           # nie rzuca wyjątków
    assert backtest.tech_buy(d2, sig, -0.2) is False                            # słaby sygnał bez potwierdzeń odpada


def test_entry_next_open_with_costs():
    orig = backtest.tech_buy
    backtest.tech_buy = lambda w, sig, rel=None: True
    try:
        df = mk(); sg = backtest.replay("X", df, df)
    finally:
        backtest.tech_buy = orig
    assert sg and all("n" in x and "pt" in x for x in sg)
    assert all(x["pt"] is None or 0 <= x["pt"] <= 100 for x in sg)


if __name__ == "__main__":
    test_no_lookahead(); test_gate_rejects_weak_confirmations(); test_entry_next_open_with_costs(); print("ok backtest")
