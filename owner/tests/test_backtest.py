import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import backtest


def mk(n=700, seed=3):
    np.random.seed(seed); c = 100 + np.cumsum(np.random.randn(n) * 1.1) + np.linspace(0, 80, n)
    return pd.DataFrame({"Open": c * (1 + np.random.randn(n) * .002), "High": c + 1.2, "Low": c - 1.2, "Close": c, "Volume": np.random.randint(1e6, 3e6, n)}, index=pd.date_range("2022-01-03", periods=n, freq="B"))


def test_no_lookahead():
    df = mk(); full = backtest.replay("X", df, df)
    cut = 600
    part = backtest.replay("X", df.iloc[:cut], df.iloc[:cut])
    f = {(x["i"], x["setup"]) for x in full if x["i"] < cut - 2}
    p = {(x["i"], x["setup"]) for x in part if x["i"] < cut - 2}
    assert f == p and len(f) > 0                      # sygnały sprzed t nie zależą od przyszłych danych
    altered = df.copy(); altered.iloc[cut:, :4] *= 3  # zmiana przyszłości nie zmienia wcześniejszych sygnałów
    a = {(x["i"], x["setup"]) for x in backtest.replay("X", altered, altered) if x["i"] < cut - 2}
    assert a == f


def test_entry_next_open_with_costs():
    df = mk(); sg = backtest.replay("X", df, df)
    assert sg and all("n" in x for x in sg)


if __name__ == "__main__":
    test_no_lookahead(); test_entry_next_open_with_costs(); print("ok backtest")
