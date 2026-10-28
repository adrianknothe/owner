"""Testy podstawowe: python -m pytest tests  (lub python tests/test_core.py)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import scan
from app.analysis import indicators, sentiment, signal


def mk(seed=1, drift=40, n=300):
    np.random.seed(seed); c = 100 + np.cumsum(np.random.randn(n) * 1.2) + np.linspace(0, drift, n)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": np.random.randint(1e6, 3e6, n)}, index=pd.date_range("2025-06-01", periods=n))


def test_indicators_bounds():
    d = indicators(mk())
    assert d.RSI.dropna().between(0, 100).all() and d.SMA200.notna().iloc[-1]


def test_missing_data_not_zero():
    r = scan.row("X", mk(), {"index": "ETF", "etf": True}, 0.0)
    assert r["etf"] and r["extra"] is False and scan.n(float("nan")) is None and scan.pct(None) is None


def test_verdict_conflict_and_completeness():
    r = scan.row("X", mk(2, 40), {"index": "S&P 500"}, 0.05)
    r.update(news_n=4, news_sent=3.0, st={"bull": 18, "bear": 4, "pct": 82}, fund={"rec": "buy", "target": r["price"] * 1.2}, reddit=None, earnings_days=None, score=-3)
    scan.verdict(r, ("Byczy", 0.5))
    assert r["conf"] == "sprzeczne" and r["lv"] <= 2 and r["compl"] == 100
    r2 = scan.row("Y", mk(2, 40), {"index": "S&P 500"}, 0.05); r2.update(reddit=None, earnings_days=None); scan.verdict(r2, ("Mieszany", 0.0))
    assert r2["compl"] == 55  # tylko technika + rynek


def test_signal_eval_conservative():
    idx = pd.date_range("2026-01-05", periods=3)
    after = pd.DataFrame({"Open": [100, 101, 102], "High": [103, 104, 104], "Low": [99, 98, 101], "Close": [101, 102, 103]}, index=idx)
    s = {"s": 95.0, "t1": 110.0}
    scan.eval_one(s, after, None)
    assert s["ex"] is None
    after2 = after.copy(); after2.loc[idx[1], ["High", "Low"]] = [112, 94]
    s3 = {"s": 95.0, "t1": 110.0}; a3 = after.copy(); a3.loc[idx[2], "High"] = 111; scan.eval_one(s3, a3, None); assert s3["ex"] == "t1"
    s2 = {"s": 95.0, "t1": 110.0}; scan.eval_one(s2, after2, None)
    assert s2["ex"] == "amb"  # stop i cel w jednej świecy – nie zakładamy kolejności


def test_sentiment():
    assert sentiment("X beats estimates, raises guidance") > 0 > sentiment("X misses estimates amid class action")


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("ok", k)
