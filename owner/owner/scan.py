"""Skan całego rynku akcji USA -> docs/results.json + docs/h/*.json (historia do wykresów).
Źródła: Yahoo Finance (ceny, newsy, konsensus analityków), Google News RSS, ApeWisdom (Reddit),
StockTwits, CNN Fear & Greed. Tylko informacyjnie – to nie jest porada inwestycyjna."""
import json, math, os, re, time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import yfinance as yf

from app.analysis import extra, indicators, plan, sentiment, signal
from app.universe import UA, get_universe

T0 = time.time()
CHUNK = 100
ST_FAIL = [0]
elapsed = lambda: (time.time() - T0) / 60


def n(x, d=2):
    try:
        x = float(x)
        return round(x, d) if math.isfinite(x) else None
    except Exception:
        return None


def dl(chunk, period):
    for _ in range(2):
        try:
            d = yf.download(chunk, period=period, interval="1d", group_by="ticker", auto_adjust=True, threads=True, progress=False)
            if len(d):
                return d
        except Exception as e:
            print("download:", e)
        time.sleep(5)


def write_hist(sym, df):
    fn = re.sub(r"[^A-Za-z0-9-]", "", sym)
    Path("docs/h").mkdir(parents=True, exist_ok=True)
    vol = [int(v / 1000) if math.isfinite(v) else 0 for v in df.Volume]
    Path(f"docs/h/{fn}.json").write_text(json.dumps(
        {"t": [int(x.timestamp() // 86400) for x in df.index], "c": [n(x) for x in df.Close], "v": vol}, separators=(",", ":")))


def row(sym, df, meta, spy3m):
    df = extra(indicators(df))
    r, p = df.iloc[-1], df.iloc[-2]
    k = min(63, len(df) - 1)
    ret3m = float(r.Close / df.Close.iloc[-1 - k] - 1)
    sig = signal(df)
    return {"symbol": sym, "name": meta.get("name", ""), "index": meta["index"], "n100": meta.get("n100", False), "etf": meta.get("etf", False), "extra": meta.get("extra", False), "exch": meta.get("exch", ""),
            "sector": meta.get("sector", ""), "price": n(r.Close), "change_pct": n((r.Close / p.Close - 1) * 100),
            "week_pct": n((r.Close / df.Close.iloc[-6] - 1) * 100), "month_pct": n((r.Close / df.Close.iloc[-22] - 1) * 100),
            "rsi": n(r.RSI, 1), "adx": n(r.ADX, 1), "vol_ratio": n(r.VOL_RATIO), "avg_vol": int(df.Volume.tail(20).mean()),
            "dvol": n((df.Close * df.Volume).tail(20).mean() / 1e6, 1), "atr_pct": n(r.ATR / r.Close * 100),
            "rs": n((ret3m - spy3m) * 100, 1), "hi52_pct": n((r.Close / df.High.tail(252).max() - 1) * 100, 1),
            "above50": bool(r.Close > r.SMA50), "above200": bool(r.Close > r.SMA200) if r.SMA200 == r.SMA200 else None,
            "sma20": n(r.SMA20), **sig, "plan": plan(df, sig, ret3m - spy3m)}


# ---------- źródła informacji ----------
def gnews(q, k=6):
    out = []
    try:
        x = requests.get("https://news.google.com/rss/search", params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}, headers=UA, timeout=15).text
        for it in ET.fromstring(x).iter("item"):
            title, src = it.findtext("title", ""), it.findtext("source", "")
            if src and title.endswith(" - " + src):
                title = title[:-len(src) - 3]
            out.append({"title": title, "url": it.findtext("link", ""), "src": src or "Google News",
                        "ts": int(parsedate_to_datetime(it.findtext("pubDate")).timestamp()), "sent": sentiment(title)})
            if len(out) >= k:
                break
    except Exception:
        pass
    return out


def ynews(sym, k=6):
    out = []
    try:
        for it in (yf.Ticker(sym).news or [])[:k]:
            c = it.get("content", it)
            t = c.get("title", "")
            ts = int(datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00")).timestamp()) if c.get("pubDate") else 0
            out.append({"title": t, "url": (c.get("canonicalUrl") or {}).get("url") or c.get("link", ""),
                        "src": "Yahoo · " + ((c.get("provider") or {}).get("displayName") or c.get("publisher", "")), "ts": ts, "sent": sentiment(t)})
    except Exception:
        pass
    return out


def fetch_news(sym):
    items, seen = [], set()
    for a in sorted(ynews(sym) + gnews(f"{sym} stock when:7d"), key=lambda a: -a["ts"]):
        key = re.sub(r"\W", "", a["title"].lower())[:40]
        if key and key not in seen and (not a["ts"] or time.time() - a["ts"] < 10 * 86400):
            seen.add(key)
            items.append(a)
    return sym, items[:8]


def stocktwits(sym):
    if ST_FAIL[0] >= 3:
        return sym, None
    try:
        r = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json", headers=UA, timeout=15)
        if r.status_code != 200:
            ST_FAIL[0] += 1
            return sym, None
        ST_FAIL[0] = 0
        sent = [((m.get("entities") or {}).get("sentiment") or {}).get("basic") for m in r.json().get("messages", [])]
        b, s = sent.count("Bullish"), sent.count("Bearish")
        return sym, {"bull": b, "bear": s, "pct": round(100 * b / (b + s)) if b + s >= 5 else None}
    except Exception:
        return sym, None


def pct(x):
    return n(x * 100, 1) if x is not None else None


def fund(sym):
    try:
        i = yf.Ticker(sym).info
        g = i.get
        er = g("netExpenseRatio") if g("netExpenseRatio") is not None else (pct(g("annualReportExpenseRatio")))
        return sym, {"rec": g("recommendationKey"), "target": n(g("targetMeanPrice")), "tlow": n(g("targetLowPrice")), "thigh": n(g("targetHighPrice")),
                     "analysts": g("numberOfAnalystOpinions"), "pe": n(g("trailingPE"), 1), "fpe": n(g("forwardPE"), 1), "peg": n(g("trailingPegRatio")),
                     "ps": n(g("priceToSalesTrailing12Months")), "pb": n(g("priceToBook")), "evebitda": n(g("enterpriseToEbitda"), 1), "mcap": g("marketCap"),
                     "rev": g("totalRevenue"), "revg": pct(g("revenueGrowth")), "gm": pct(g("grossMargins")), "om": pct(g("operatingMargins")),
                     "pm": pct(g("profitMargins")), "roe": pct(g("returnOnEquity")), "roa": pct(g("returnOnAssets")), "de": n(g("debtToEquity"), 1),
                     "cr": n(g("currentRatio")), "fcf": g("freeCashflow"), "eps": n(g("trailingEps")), "feps": n(g("forwardEps")),
                     "dr": n(g("dividendRate") if g("dividendRate") is not None else g("trailingAnnualDividendRate")), "exdiv": g("exDividendDate"),
                     "payout": pct(g("payoutRatio")), "short": pct(g("shortPercentOfFloat")), "beta": n(g("beta")), "sector": g("sector") or "",
                     "industry": g("industry") or "", "name": g("longName") or "", "desc": (g("longBusinessSummary") or "")[:300],
                     "emp": g("fullTimeEmployees"), "cur": g("currency"), "qt": g("quoteType"), "cat": g("category"), "aum": g("totalAssets"), "er": n(er, 3)}
    except Exception:
        return sym, None


def statements(sym):
    t = yf.Ticker(sym)

    def ser(df, labels, k, fmt):
        try:
            for lb in labels:
                if df is not None and lb in df.index:
                    s = df.loc[lb].dropna().sort_index().tail(k)
                    return [[d.strftime(fmt), n(v / 1e6, 1)] for d, v in s.items()]
        except Exception:
            pass
        return []

    def get(a):
        try:
            return getattr(t, a)
        except Exception:
            return None
    inc, cf, bs, q = get("income_stmt"), get("cashflow"), get("balance_sheet"), get("quarterly_income_stmt")
    out = {"y": {"rev": ser(inc, ["Total Revenue", "Operating Revenue"], 5, "%Y"), "net": ser(inc, ["Net Income"], 5, "%Y"),
                 "ebitda": ser(inc, ["EBITDA", "Normalized EBITDA"], 5, "%Y"), "fcf": ser(cf, ["Free Cash Flow"], 5, "%Y"),
                 "ocf": ser(cf, ["Operating Cash Flow"], 5, "%Y"), "assets": ser(bs, ["Total Assets"], 5, "%Y"),
                 "debt": ser(bs, ["Total Debt"], 5, "%Y"), "cash": ser(bs, ["Cash And Cash Equivalents"], 5, "%Y")},
           "q": {"rev": ser(q, ["Total Revenue", "Operating Revenue"], 6, "%Y-%m"), "net": ser(q, ["Net Income"], 6, "%Y-%m")}}
    try:
        fd = t.funds_data
        out["etf"] = {"hold": [[str(i), str(r.get("Name", ""))[:30], n(float(r.get("Holding Percent", 0)) * 100, 1)] for i, r in fd.top_holdings.head(10).iterrows()],
                      "sectors": {k: n(v * 100, 1) for k, v in (fd.sector_weightings or {}).items()}}
    except Exception:
        pass
    return out


def fin(sym):
    _, m = fund(sym)
    return sym, {"ts": time.time(), "m": m or {}, **statements(sym)}


def prev_json(name):
    try:
        repo = os.getenv("GITHUB_REPOSITORY", "adrianknothe/owner").split("/")
        return requests.get(f"https://{repo[0]}.github.io/{repo[1]}/{name}", timeout=30).json()
    except Exception:
        return {}


def earnings_days(sym):
    try:
        ed = yf.Ticker(sym).calendar.get("Earnings Date")
        return sym, ((ed[0] if isinstance(ed, (list, tuple)) else ed) - date.today()).days
    except Exception:
        return sym, None


def apewisdom():
    out = {}
    for p in (1, 2, 3):
        try:
            for x in requests.get(f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{p}", headers=UA, timeout=20).json().get("results", []):
                out[x["ticker"].upper().replace(".", "-")] = {"rank": x["rank"], "mentions": x["mentions"], "prev": x.get("mentions_24h_ago")}
        except Exception as e:
            print("apewisdom:", e)
    return out


def jget(url):
    try:
        return requests.get(url, headers=UA, timeout=20).json()
    except Exception:
        return {}


# ---------- rekomendacja łączona ----------
def verdict(r, mood):
    c, cl = {}, lambda x: round(max(-2, min(2, x)), 2)
    a200 = r["above200"]
    c["tech"] = [cl(r["score"] * 0.4 + (0.3 if a200 else -0.3 if a200 is False else 0)), 0.5, None]
    if r.get("news_n"):
        c["news"] = [cl(r["news_sent"] / 2), 0.2, f"{r['news_n']} wiadomości, bilans nastroju {r['news_sent']:+.0f}"]
    st = r.get("st")
    if st and st.get("pct") is not None:
        c["social"] = [cl((st["pct"] - 50) / 20), 0.1, f"StockTwits: {st['pct']}% wpisów byczych ({st['bull'] + st['bear']} ocenionych)"]
    f = r.get("fund") or {}
    a = {"strong_buy": 2, "buy": 1, "hold": 0, "underperform": -1, "sell": -2}.get(f.get("rec"))
    if a is not None:
        up = (f["target"] / r["price"] - 1) * 100 if f.get("target") else None
        a += 0.5 if up is not None and up > 15 else -0.5 if up is not None and up < -5 else 0
        c["analyst"] = [cl(a), 0.15, f"konsensus: {f['rec']}" + (f", cena docelowa {f['target']} $ ({up:+.0f}%)" if up is not None else "")]
    c["market"] = [mood[1] * 2, 0.05, f"rynek: {mood[0].lower()}"]
    tot = sum(v[0] * v[1] for v in c.values()) / sum(v[1] for v in c.values())
    nn = [v for k, v in c.items() if k != "market"]
    agree = sum(1 for v in nn if v[0] * tot > 0 and abs(v[0]) >= 0.3)
    conf = "wysoka" if len(nn) >= 3 and agree >= 3 else "średnia" if len(nn) >= 2 and agree >= 2 else "niska"
    if c["tech"][0] * tot < 0 and abs(c["tech"][0]) >= 0.3:
        conf = "sprzeczne"  # technika przeczy pozostałym sygnałom
    lv = 4 if tot >= 1.2 else 3 if tot >= 0.6 else 2 if tot > -0.6 else 1 if tot > -1.2 else 0
    flags = []
    if conf in ("niska", "sprzeczne"):
        lv = 3 if lv == 4 else 1 if lv == 0 else lv
    if conf == "sprzeczne" and lv >= 3:
        lv = 2; flags.append("Sygnały są sprzeczne – analiza techniczna nie potwierdza newsów/analityków, nie kupuj wbrew trendowi")
    if lv >= 3 and r.get("earnings_days") is not None and r["earnings_days"] <= 5:
        lv -= 1; flags.append(f"Wyniki kwartalne za {r['earnings_days']} dni – obniżono ocenę (ryzyko luki)")
    if lv >= 3 and r["rsi"] and r["rsi"] > 78:
        lv -= 1; flags.append("RSI > 78 – spółka wykupiona, obniżono ocenę")
    if lv >= 3 and mood[1] < 0:
        flags.append("Słaby rynek ogólny – zmniejsz wielkość pozycji")
    if (r.get("reddit") or {}).get("rank", 999) <= 25:
        flags.append("Wysokie zainteresowanie na Reddit – ryzyko nagłych ruchów (hype)")
    r.update(lv=lv, vscore=round(tot, 2), conf=conf, flags=flags, comps={k: v[::2] if k != "tech" else [v[0]] for k, v in c.items()})


def main():
    uni = get_universe()
    syms = list(uni)
    spy = yf.download("SPY", period="1y", auto_adjust=True, progress=False)
    spy.columns = spy.columns.get_level_values(0)
    spy3m = float(spy.Close.iloc[-1] / spy.Close.iloc[-64] - 1)

    # etap 1: cały rynek (1 rok dziennych świec), tylko płynne spółki
    rows = []
    for i in range(0, len(syms), CHUNK):
        if elapsed() > 13:
            print(f"Przekroczono budżet czasu – przeskanowano {i} z {len(syms)}"); break
        data = dl(syms[i:i + CHUNK], "1y")
        if data is None:
            continue
        for s in syms[i:i + CHUNK]:
            try:
                df = data[s].dropna(subset=["Close"])
                m, dv = uni[s], (df.Close * df.Volume).tail(20).mean()
                if len(df) >= 70 and (m.get("extra") or (df.Close.iloc[-1] >= 1.5 and dv >= (3e6 if m.get("etf") else 1e6))):
                    rows.append(row(s, df.copy(), uni[s], spy3m))
                    write_hist(s, df)
            except Exception:
                pass
        time.sleep(0.5)
    if len(rows) < 100:
        raise SystemExit(f"Zbyt mało danych ({len(rows)}) – przerywam, żeby nie nadpisać strony")
    print(f"Etap 1: {len(rows)} płynnych spółek, {elapsed():.1f} min")

    N = len(rows)
    a50, buy, sell = sum(r["above50"] for r in rows) / N, sum(r["label"] == "kupno" for r in rows) / N, sum(r["label"] == "sprzedaż" for r in rows) / N
    mood = ("Byczy", 0.5) if a50 >= .6 and buy > sell else ("Niedźwiedzi", -0.5) if a50 < .4 or sell > buy * 1.5 else ("Mieszany", 0.0)
    market = {"name": mood[0], "a50": round(a50 * 100), "buy": round(buy * 100), "sell": round(sell * 100),
              "adv": round(sum((r["change_pct"] or 0) > 0 for r in rows) / N * 100)}

    # etap 2: Reddit, newsy, analitycy, social, wyniki – dla najciekawszych spółek
    FUND = prev_json("fundamentals.json").get("d", {})
    reddit = apewisdom()
    for r in rows:
        r["reddit"] = reddit.get(r["symbol"])
    cand = sorted(rows, key=lambda r: -(r["plan"]["quality"] if r["plan"] else abs(r["score"]) * 10))[:140]
    movers = sorted(rows, key=lambda r: -abs(r["change_pct"] or 0))[:20]
    focus = list(dict.fromkeys([r["symbol"] for r in cand] + [r["symbol"] for r in movers]))
    news, market_news, st_trend = {}, [], []
    if elapsed() < 15:
        with ThreadPoolExecutor(8) as ex:
            news = dict(ex.map(fetch_news, focus))
            fu = dict(ex.map(fund, focus[:90]))
            ea = dict(ex.map(earnings_days, [r["symbol"] for r in cand[:60]]))
            sto = dict(ex.map(stocktwits, focus[:50]))
        for r in rows:
            s = r["symbol"]
            if s in news:
                ns = news[s]
                r["news_n"] = len(ns)
                r["news_sent"] = round(sum(a["sent"] * (1 if time.time() - a["ts"] < 72 * 3600 else .5) for a in ns), 1)
            m = fu.get(s)
            r["fund"] = {k: m.get(k) for k in ("rec", "target", "analysts", "pe", "fpe", "mcap", "short", "beta", "sector", "industry", "dr", "payout", "exdiv")} if m else None
            r["st"] = sto.get(s)
            if m:
                FUND.setdefault(s, {}).update(m=m, mts=time.time())
            if r["fund"] and r["fund"].get("sector") and not r["sector"]:
                r["sector"] = r["fund"]["sector"]
            e = ea.get(s)
            r["earnings_days"] = e if e is not None and 0 <= e <= 10 else None
        market_news = sorted(ynews("SPY", 5) + gnews("stock market Wall Street when:2d", 6) + gnews("Federal Reserve economy when:3d", 4), key=lambda a: -a["ts"])[:12]
        st_trend = [{"s": x["symbol"], "t": x.get("title", "")} for x in jget("https://api.stocktwits.com/api/2/trending/symbols.json").get("symbols", [])[:12]]
    for r in rows:
        verdict(r, mood)

    # dane finansowe (sprawozdania, wskaźniki, ETF) – uzupełniane stopniowo, ~70 symboli na skan, odświeżane co 7 dni
    try:
        order = [r["symbol"] for r in sorted(rows, key=lambda r: (not r["extra"], not r["symbol"] in focus, not (r["index"] in ("S&P 500", "NASDAQ-100") or r["n100"]), -(r["dvol"] or 0)))]
        need = [s for s in order if time.time() - FUND.get(s, {}).get("ts", 0) > 7 * 86400][:70]
        if elapsed() < 16 and need:
            with ThreadPoolExecutor(6) as ex:
                for s, d in ex.map(fin, need):
                    if d["m"] or d["y"]["rev"]:
                        FUND.setdefault(s, {}).update(d)
        keep = {r["symbol"] for r in rows}
        Path("docs").mkdir(exist_ok=True)
        Path("docs/fundamentals.json").write_text(json.dumps({"ts": time.time(), "d": {k: v for k, v in FUND.items() if k in keep}}, separators=(",", ":"), allow_nan=False))
        print(f"Dane finansowe: {len(need)} odświeżonych, {len([k for k in FUND if k in keep])} łącznie")
    except Exception as e:
        print("fundamentals:", e)

    # poprzedni wynik -> oznacz nowe rekomendacje kupna
    try:
        repo = os.getenv("GITHUB_REPOSITORY", "adrianknothe/owner").split("/")
        old = {x["symbol"]: x.get("lv") for x in requests.get(f"https://{repo[0]}.github.io/{repo[1]}/results.json", timeout=20).json()["results"]}
        for r in rows:
            r["new"] = bool(old) and r["lv"] >= 3 and (old.get(r["symbol"]) or 0) < 3
    except Exception:
        pass

    # historia 5-letnia dla głównych spółek i okazji
    big = [r["symbol"] for r in rows if r["index"] in ("S&P 500", "NASDAQ-100") or r["n100"] or r["plan"] or r["symbol"] in news]
    for i in range(0, len(big), 50):
        if elapsed() > 17:
            break
        data = dl(big[i:i + 50], "5y")
        for s in big[i:i + 50]:
            try:
                write_hist(s, data[s].dropna(subset=["Close"]))
            except Exception:
                pass

    # indeksy
    idx = []
    for s, name in [("^GSPC", "S&P 500 (US500)"), ("^NDX", "NASDAQ-100 (US100)"), ("^IXIC", "NASDAQ Composite"), ("^DJI", "Dow Jones (US30)"), ("^RUT", "Russell 2000"), ("^VIX", "VIX – zmienność")]:
        try:
            d = yf.download(s, period="5y", auto_adjust=True, progress=False)
            d.columns = d.columns.get_level_values(0)
            write_hist(s, d)
            d = indicators(d)
            r, p = d.iloc[-1], d.iloc[-2]
            idx.append({"symbol": s, "name": name, "price": n(r.Close), "change_pct": n((r.Close / p.Close - 1) * 100),
                        "week_pct": n((r.Close / d.Close.iloc[-6] - 1) * 100), "month_pct": n((r.Close / d.Close.iloc[-22] - 1) * 100),
                        "ytd_pct": n((r.Close / d.Close[d.index.year == d.index[-1].year].iloc[0] - 1) * 100), "rsi": n(r.RSI, 1),
                        "above50": bool(r.Close > r.SMA50), "above200": bool(r.Close > r.SMA200), "spark": [n(x, 1) for x in d.Close.tail(60)]})
        except Exception as e:
            print("indeks", s, e)

    fng = jget("https://production.dataviz.cnn.io/index/fearandgreed/graphdata").get("fear_and_greed", {})
    top_reddit = [{"s": k, **v} for k, v in sorted(reddit.items(), key=lambda kv: kv[1]["rank"])[:12]]
    out = {"updated_at": time.time(), "indices": idx, "market": market, "fng": {"score": n(fng.get("score"), 0), "rating": fng.get("rating")} if fng else None,
           "market_news": market_news, "news": news, "reddit": top_reddit, "st_trending": st_trend, "scanned": len(syms), "results": rows}
    Path("docs").mkdir(exist_ok=True)
    Path("docs/results.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    print(f"OK: {len(rows)} spółek (z {len(syms)}), {sum(r['lv'] >= 3 for r in rows)} rekomendacji kupna, {elapsed():.1f} min")


if __name__ == "__main__":
    main()
