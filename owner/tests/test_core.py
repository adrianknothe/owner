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


def test_notify_rules():
    rules = scan.parse_rules("AAPL >= 200  # cena\nNVDA <= 100\nsignal NVDA TSLA\nearnings MSFT\nzły wiersz\nX >= abc")
    assert len(rules) == 5
    rows = {"AAPL": {"price": 205, "lv": 2, "earnings_days": None}, "NVDA": {"price": 120, "lv": 2, "earnings_days": None}, "TSLA": {"price": 1, "lv": 3, "earnings_days": None}, "MSFT": {"price": 1, "lv": 2, "earnings_days": 2}}
    m1, s1 = scan.eval_rules(rules, rows, {}, now=1e9)
    assert any("AAPL" in m for m in m1) and any("MSFT" in m for m in m1) and not any("nowy sygnał" in m for m in m1)  # pierwszy odczyt sygnału: tylko zapamiętaj
    m2, s2 = scan.eval_rules(rules, rows, s1, now=1e9 + 60)
    assert m2 == []  # brak duplikatów
    rows["AAPL"]["price"] = 190; _, s3 = scan.eval_rules(rules, rows, s2, now=1e9 + 120)   # warunek ustąpił -> reguła uzbrojona
    rows["AAPL"]["price"] = 210; rows["NVDA"]["lv"] = 3
    m4, _ = scan.eval_rules(rules, rows, s3, now=1e9 + 180)
    assert any("AAPL" in m for m in m4) and any("NVDA: nowy sygnał" in m for m in m4)
    assert "AAPL" not in str(s1)  # stan nie ujawnia symboli


def test_forward_bars_and_summary():
    idx = pd.date_range("2026-01-05", periods=25)
    after = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": [100 + i * .2 for i in range(25)], "Volume": 1000}, index=idx).head(20)
    s = {"s": 90.0, "t1": 130.0, "ts": 1}; scan.eval_one(s, after, after)
    assert len(s["fb"]) == 20 and "r20" in s and "b20" in s
    o = scan.summarize([s]); assert o["n20"] == 1 and o["ev"] == 1


if __name__ == "__main__":
    test_notify_rules(); test_forward_bars_and_summary(); print("ok extra")


def test_eu_universe_and_rows():
    import io
    from app.universe import parse_eu_html
    dax = "<table><tr><th>Company</th><th>Ticker</th><th>Sector</th></tr>" + "".join(f"<tr><td>Firma {i}</td><td>AB{i}</td><td>Industrials</td></tr>" for i in range(20)) + "</table>"
    assert parse_eu_html(dax, ".DE")[0][0] == "AB0.DE" and len(parse_eu_html(dax, ".DE")) == 20
    ftse = "<table><tr><th>Company</th><th>EPIC</th></tr><tr><td>BT</td><td>BT.A</td></tr><tr><td>Rolls</td><td>RR.</td></tr>" + "".join(f"<tr><td>X{i}</td><td>X{i}</td></tr>" for i in range(18)) + "</table>"
    syms = [x[0] for x in parse_eu_html(ftse, ".L")]
    assert "BT-A.L" in syms and "RR.L" in syms
    assert parse_eu_html("<table><tr><th>Ticker</th></tr><tr><td>A</td></tr></table>", ".DE") == []   # za krótka tabela = odrzucona (użyj zapasowej listy)
    r = scan.row("SAP.DE", mk(), {"index": "DAX", "mkt": "DE", "cur": "EUR", "exch": "XETRA"}, None, uf=1.08)
    assert r["mkt"] == "DE" and r["cur"] == "EUR" and r["rs"] is None   # brak benchmarku => brak siły względnej, nie podstawiamy S&P
    r2 = scan.row("X", mk(), {"index": "S&P 500"}, 0.05); assert r2["cur"] == "USD" and r2["mkt"] == "US" and r2["rs"] is not None
    assert abs(scan.row("X", mk(), {"index": "S&P 500"}, 0.05, uf=1.0)["dvol"] * 2 - scan.row("X", mk(), {"index": "S&P 500"}, 0.05, uf=2.0)["dvol"]) < 0.2


if __name__ == "__main__":
    test_eu_universe_and_rows(); print("ok eu")


def test_long_term():
    e = {"m": {"roe": 28, "om": 30, "pm": 24, "fcf": 120, "rev": 800, "revg": 15, "pe": 18, "fpe": 16, "evebitda": 11, "de": 40, "cr": 2.1, "dr": 2.0, "payout": 40, "target": 130, "eps": 5},
         "y": {"rev": [["2022", 500], ["2023", 600], ["2024", 720], ["2025", 800]]}}
    r = {"price": 100, "above200": True, "hi52_pct": -4}
    lt = scan.long_term(r, e)
    assert lt["s"] >= 75 and lt["l"] == "Silne" and lt["a"] == "Gromadź" and lt["cov"] == 100 and not lt["fl"]
    bad = scan.long_term({"price": 10, "above200": False, "hi52_pct": -45}, {"m": {"roe": -5, "om": -3, "pm": -8, "fcf": -20, "rev": 100, "revg": -10, "pe": None, "de": 300, "cr": 0.7, "eps": -1}})
    assert bad["s"] < 40 and bad["a"] == "Unikaj" and "ujemny free cash flow" in bad["fl"]
    assert scan.long_term(r, {"m": {"pe": 20}}) is None and scan.long_term(r, None) is None   # za mało danych = brak oceny, nie zero


if __name__ == "__main__":
    test_long_term(); print("ok lt")
