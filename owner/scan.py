"""Jednorazowy skan całego rynku USA -> docs/results.json (uruchamiany przez GitHub Actions)."""
import json
import time
from pathlib import Path

import yfinance as yf

from app.analysis import indicators, signal
from app.universe import get_universe

CHUNK = 80


def row(sym, df, meta):
    df = indicators(df)
    r, p = df.iloc[-1], df.iloc[-2]
    return {"symbol": sym, "index": meta["index"], "sector": meta["sector"],
            "price": round(float(r.Close), 2), "change_pct": round(float(r.Close / p.Close - 1) * 100, 2),
            "week_pct": round(float(r.Close / df.Close.iloc[-6] - 1) * 100, 2),
            "rsi": round(float(r.RSI), 1), "vol_ratio": round(float(r.VOL_RATIO), 2),
            "avg_vol": int(df.Volume.tail(20).mean()), "closes": [round(float(x), 2) for x in df.Close.tail(90)],
            **signal(df)}


def main():
    uni = get_universe()
    syms, out = list(uni), []
    for i in range(0, len(syms), CHUNK):
        chunk = syms[i:i + CHUNK]
        try:
            data = yf.download(chunk, period="6mo", interval="1d", group_by="ticker",
                               auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            print("chunk błąd", i, e)
            continue
        for s in chunk:
            try:
                df = data[s].dropna(subset=["Close"])
                if len(df) >= 55 and df.Volume.tail(20).mean() > 0:
                    out.append(row(s, df.copy(), uni[s]))
            except Exception:
                pass
        time.sleep(1)
    if len(out) < 100:
        raise SystemExit(f"Zbyt mało danych ({len(out)}) – przerywam, żeby nie nadpisać strony pustym wynikiem")
    Path("docs").mkdir(exist_ok=True)
    Path("docs/results.json").write_text(json.dumps({"updated_at": time.time(), "results": out}, separators=(",", ":")))
    print(f"OK: {len(out)} spółek z {len(syms)}")


if __name__ == "__main__":
    main()
