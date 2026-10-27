"""Skan rynku USA -> docs/results.json (uruchamiany przez GitHub Actions). Tylko informacyjnie."""
import json, math, os, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import requests
import yfinance as yf

from app.analysis import extra, indicators, plan, sentiment, signal
from app.universe import get_universe

CHUNK = 80


def n(x, d=2):
    try:
        x = float(x)
        return round(x, d) if math.isfinite(x) else None
    except Exception:
        return None


def prep(df):
    return extra(indicators(df))


def row(sym, df, meta, spy3m):
    df = prep(df)
    r, p = df.iloc[-1], df.iloc[-2]
    k = min(63, len(df) - 1)
    ret3m = float(r.Close / df.Close.iloc[-1 - k] - 1)
    sig = signal(df)
    return {"symbol": sym, "index": meta["index"], "sector": meta["sector"],
            "price": n(r.Close), "change_pct": n((r.Close / p.Close - 1) * 100),
            "week_pct": n((r.Close / df.Close.iloc[-6] - 1) * 100), "month_pct": n((r.Close / df.Close.iloc[-22] - 1) * 100),
            "rsi": n(r.RSI, 1), "adx": n(r.ADX, 1), "vol_ratio": n(r.VOL_RATIO), "avg_vol": int(df.Volume.tail(20).mean()),
            "atr_pct": n(r.ATR / r.Close * 100), "rs": n((ret3m - spy3m) * 100, 1),
            "hi52_pct": n((r.Close / df.High.max() - 1) * 100, 1), "above50": bool(r.Close > r.SMA50),
            "closes": [n(x) for x in df.Close.tail(90)], **sig, "plan": plan(df, sig, ret3m - spy3m)}


def get_news(sym):
    try:
        out = []
        for it in (yf.Ticker(sym).news or [])[:5]:
            c = it.get("content", it)
            t = c.get("title", "")
            out.append({"title": t, "url": (c.get("canonicalUrl") or {}).get("url") or c.get("link", ""),
                        "publisher": (c.get("provider") or {}).get("displayName", c.get("publisher", "")),
                        "sent": sentiment(t)})
        return sym, out
    except Exception:
        return sym, []


def earnings_days(sym):
    try:
        ed = yf.Ticker(sym).calendar.get("Earnings Date")
        d = (ed[0] if isinstance(ed, (list, tuple)) else ed)
        return sym, (d - date.today()).days
    except Exception:
        return sym, None


def main():
    uni = get_universe()
    syms = list(uni)
    spy = yf.download("SPY", period="1y", auto_adjust=True, progress=False)
    spy.columns = spy.columns.get_level_values(0)
    spy3m = float(spy.Close.iloc[-1] / spy.Close.iloc[-64] - 1)
    rows = []
    for i in range(0, len(syms), CHUNK):
        chunk = syms[i:i + CHUNK]
        try:
            data = yf.download(chunk, period="1y", interval="1d", group_by="ticker", auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            print("chunk błąd", i, e)
            continue
        for s in chunk:
            try:
                df = data[s].dropna(subset=["Close"])
                if len(df) >= 70 and df.Volume.tail(20).mean() > 0:
                    rows.append(row(s, df.copy(), uni[s], spy3m))
            except Exception:
                pass
        time.sleep(1)
    if len(rows) < 100:
        raise SystemExit(f"Zbyt mało danych ({len(rows)}) – przerywam, żeby nie nadpisać strony")

    # poprzedni wynik -> oznacz nowe sygnały kupna
    try:
        repo = os.getenv("GITHUB_REPOSITORY", "adrianknothe/owner").split("/")
        prev = requests.get(f"https://{repo[0]}.github.io/{repo[1]}/results.json", timeout=20).json()
        old = {x["symbol"]: x["label"] for x in prev["results"]}
        for r in rows:
            r["new"] = bool(old) and r["label"] == "kupno" and old.get(r["symbol"]) != "kupno"
    except Exception:
        pass

    # newsy i terminy wyników dla najciekawszych spółek
    setups = sorted([r for r in rows if r["plan"]], key=lambda r: -r["plan"]["quality"])
    movers = sorted(rows, key=lambda r: -abs(r["change_pct"] or 0))[:20]
    focus = list({r["symbol"] for r in setups[:60] + movers})
    with ThreadPoolExecutor(8) as ex:
        news = dict(ex.map(get_news, focus + ["SPY"]))
        earn = dict(ex.map(earnings_days, [r["symbol"] for r in setups[:40]]))
    for r in rows:
        ns = news.get(r["symbol"])
        r["news_sent"] = sum(a["sent"] for a in ns) if ns else None
        e = earn.get(r["symbol"])
        r["earnings_days"] = e if e is not None and 0 <= e <= 10 else None

    idx = []
    for s, name in [("SPY", "S&P 500"), ("QQQ", "NASDAQ-100"), ("IWM", "Russell 2000"), ("^VIX", "VIX (zmienność)")]:
        try:
            d = yf.download(s, period="1y", auto_adjust=True, progress=False)
            d.columns = d.columns.get_level_values(0)
            d = indicators(d)
            r, p = d.iloc[-1], d.iloc[-2]
            idx.append({"symbol": s, "name": name, "price": n(r.Close), "change_pct": n((r.Close / p.Close - 1) * 100),
                        "week_pct": n((r.Close / d.Close.iloc[-6] - 1) * 100), "month_pct": n((r.Close / d.Close.iloc[-22] - 1) * 100),
                        "rsi": n(r.RSI, 1), "above50": bool(r.Close > r.SMA50)})
        except Exception as e:
            print("indeks", s, e)

    Path("docs").mkdir(exist_ok=True)
    out = {"updated_at": time.time(), "indices": idx, "market_news": news.get("SPY", []),
           "news": {k: v for k, v in news.items() if k != "SPY"}, "results": rows}
    Path("docs/results.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    print(f"OK: {len(rows)} spółek, {len(setups)} setupów")


if __name__ == "__main__":
    main()
