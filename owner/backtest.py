"""Backtest TECHNICZNY reguł setupów (Wybicie / Trend / Odbicie) na 5 latach danych dziennych.
Bez newsów, konsensusu i social (ich historii nie mamy). Uruchamiany co tydzień przez osobny workflow; wynik: docs/backtest.json.

Założenia i zastrzeżenia (zapisywane w wyniku):
 - sygnał liczony na zamknięciu sesji t, wejście po otwarciu sesji t+1 (+ poślizg), koszty 0,1% na stronę,
 - stop i cel z planu (ATR); stop i cel w jednej świecy = 'niejednoznaczne' (nie zakładamy kolejności),
 - reguły ustalone z góry, NIE stroione pod te dane; wyniki podzielone na pierwsze 60% i ostatnie 40% okresu,
 - OBCIĄŻENIE PRZEŻYWALNOŚCIĄ: uniwersum to dzisiejsi członkowie S&P 500 / NASDAQ-100 (spółki, które odpadły, nie są ujęte),
 - sygnały skorelowane (ten sam dzień rynkowy) – liczba obserwacji przeszacowuje niezależność."""
import json, time
from pathlib import Path

import pandas as pd

import scan
from app.analysis import extra, indicators, plan, signal
from app.universe import get_universe

HOLD, WARM, DEDUPE = 20, 252, 7


def tech_buy(w, sig):
    """Odpowiednik lv>=3 dla samej techniki (waga technika 0,5 + rynek 0): suma >= 0,6, bez kary za RSI>78."""
    r = w.iloc[-1]
    if r.SMA200 != r.SMA200:
        return False
    tot = (sig["score"] * 0.4 + (0.3 if r.Close > r.SMA200 else -0.3)) * 0.5 / 0.55
    return tot >= 0.6 and not (r.RSI > 78)


def replay(sym, df, bench):
    """Zwraca sygnały z oceną. Sygnał w dniu t korzysta wyłącznie z danych <= t (indykatory są przyczynowe)."""
    df = extra(indicators(df.copy()))
    b3 = bench.Close.reindex(df.index).ffill()
    rs3 = (df.Close / df.Close.shift(63) - 1) - (b3 / b3.shift(63) - 1)
    out, last = [], {}
    for t in range(WARM, len(df) - 1):
        w = df.iloc[:t + 1]
        sig = signal(w)
        if sig["score"] < 1 or not tech_buy(w, sig):
            continue
        rs = float(rs3.iloc[t]) if rs3.iloc[t] == rs3.iloc[t] else 0.0
        p = plan(w, sig, rs)
        if not p or t - last.get(p["setup"], -99) < DEDUPE:
            continue
        last[p["setup"]] = t
        s = {"sym": sym, "setup": p["setup"], "ts": int(df.index[t].timestamp()), "s": p["stop"], "t1": p["t1"], "i": t}
        scan.eval_one(s, df.iloc[t + 1:t + 1 + HOLD], bench, keep=False)
        out.append(s)
    return out


def main():
    uni = get_universe()
    syms = [s for s, m in uni.items() if m["index"] in ("S&P 500", "NASDAQ-100") or m.get("n100")]
    spy = scan.dl(["SPY"], "5y")["SPY"].dropna(subset=["Close"])
    sigs = []
    for i in range(0, len(syms), 50):
        d = scan.dl(syms[i:i + 50], "5y")
        for s in syms[i:i + 50]:
            try:
                df = d[s].dropna(subset=["Close"])
                if len(df) > WARM + 60:
                    sigs += replay(s, df, spy)
            except Exception:
                pass
        print(f"{min(i + 50, len(syms))}/{len(syms)}", len(sigs))
    if len(sigs) < 50:
        raise SystemExit("Za mało sygnałów – nie nadpisuję wyniku")
    ts = sorted(x["ts"] for x in sigs)
    cut = ts[int(len(ts) * 0.6)]
    grp = lambda st, f: scan.summarize([x for x in sigs if x["setup"] == st and f(x)])
    stats = {st: {"all": grp(st, lambda x: True), "is": grp(st, lambda x: x["ts"] < cut), "oos": grp(st, lambda x: x["ts"] >= cut)} for st in scan.SETUPS}
    Path("docs").mkdir(exist_ok=True)
    Path("docs/backtest.json").write_text(json.dumps({"generated": time.time(), "symbols": len(syms), "signals": len(sigs), "from": ts[0], "to": ts[-1], "split": cut,
        "cost_pct": scan.COST * 100, "hold": HOLD, "stats": stats, "notes": ["Tylko technika – bez newsów, konsensusu i social.", "Obciążenie przeżywalnością: dzisiejsi członkowie indeksów.",
        "Reguły nie były stroione pod te dane; podział 60/40 służy ocenie stabilności.", "Wejście po otwarciu następnej sesji, koszt 0,1% na stronę, stop i cel w jednej świecy = niejednoznaczne.", "Sygnały są skorelowane – efektywna liczba niezależnych obserwacji jest mniejsza niż N."]}, separators=(",", ":"), allow_nan=False))
    print("OK", len(sigs))


if __name__ == "__main__":
    main()
