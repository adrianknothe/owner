"""Skan całego rynku akcji USA -> docs/results.json + docs/h/*.json (historia do wykresów).
Źródła: Yahoo Finance (ceny, newsy, konsensus analityków), Google News RSS, ApeWisdom (Reddit),
StockTwits, CNN Fear & Greed. Tylko informacyjnie – to nie jest porada inwestycyjna."""
import hashlib, json, math, os, re, time
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
NAME = {}
FUND_N, NEWS_N = 120, 150  # ile symboli odświeżamy na skan (rotacyjnie, z archiwum poprzednich skanów)
CORE = ("S&P 500", "NASDAQ-100", "DAX", "FTSE 100", "WIG20")  # w pierwszej kolejności: dane finansowe i historia 5-letnia
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


def row(sym, df, meta, spy3m, uf=1.0):
    df = extra(indicators(df))
    r, p = df.iloc[-1], df.iloc[-2]
    k = min(63, len(df) - 1)
    ret3m = float(r.Close / df.Close.iloc[-1 - k] - 1)
    sig = signal(df)
    rel = None if spy3m is None else ret3m - spy3m  # benchmark regionalny (USA: SPY, DE: DAX, UK: FTSE 100, PL: WIG20)
    cu = meta.get("cur") or "USD"
    return {"mkt": meta.get("mkt", "US"), "cur": cu, "symbol": sym, "name": meta.get("name", ""), "index": meta["index"], "n100": meta.get("n100", False), "etf": meta.get("etf", False), "extra": meta.get("extra", False), "exch": meta.get("exch", ""),
            "sector": meta.get("sector", ""), "price": n(r.Close), "change_pct": n((r.Close / p.Close - 1) * 100),
            "week_pct": n((r.Close / df.Close.iloc[-6] - 1) * 100), "month_pct": n((r.Close / df.Close.iloc[-22] - 1) * 100),
            "rsi": n(r.RSI, 1), "adx": n(r.ADX, 1), "vol_ratio": n(r.VOL_RATIO), "avg_vol": int(df.Volume.tail(20).mean()),
            "dvol": n((df.Close * df.Volume).tail(20).mean() / 1e6 * uf, 1), "atr_pct": n(r.ATR / r.Close * 100),
            "rs": n(rel * 100, 1) if rel is not None else None, "hi52_pct": n((r.Close / df.High.tail(252).max() - 1) * 100, 1),
            "above50": bool(r.Close > r.SMA50), "above200": bool(r.Close > r.SMA200) if r.SMA200 == r.SMA200 else None,
            "sma20": n(r.SMA20), "bar": [df.index[-1].strftime("%Y-%m-%d"), n(r.Open), n(r.High), n(r.Low), n(r.Close), int(r.Volume)], **sig, "plan": plan(df, sig, rel or 0.0)}


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
    for a in sorted(ynews(sym) + gnews(f'"{NAME[sym]}" stock when:7d' if "." in sym and NAME.get(sym) else f"{sym} stock when:7d"), key=lambda a: -a["ts"]):
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
    """Poprzednia wersja pliku z GitHub Pages. 404 = pierwszy skan; inny błąd przerywa skan,
    żeby nie nadpisać archiwum (Pages podmienia całą stronę przy każdym wdrożeniu)."""
    repo = os.getenv("GITHUB_REPOSITORY", "adrianknothe/owner").split("/")
    r = requests.get(f"https://{repo[0]}.github.io/{repo[1]}/{name}", timeout=30)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return r.json()


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
    r.update(lv=lv, vscore=round(tot, 2), conf=conf, compl=round(sum(v[1] for v in c.values()) * 100), flags=flags, comps={k: v[::2] if k != "tech" else [v[0]] for k, v in c.items()})



COST = 0.001  # założenie: 0,1% na stronę (prowizja + poślizg)
SETUPS = ("Wybicie", "Trend", "Odbicie")


def fx_rates():
    out = {"PLN": {"r": 1.0, "d": None, "src": "—"}}
    pairs = {c: f"{c}PLN=X" for c in ("USD", "EUR", "GBP", "CHF", "CZK", "SEK", "NOK", "DKK")}
    d = dl(list(pairs.values()), "7d")
    for c, t in pairs.items():
        try:
            sr = d[t]["Close"].dropna()
            out[c] = {"r": n(sr.iloc[-1], 4), "d": sr.index[-1].strftime("%Y-%m-%d"), "src": f"Yahoo Finance ({t}, zamknięcie dzienne)"}
        except Exception:
            pass
    return out


def _vol(b):
    v = getattr(b, "Volume", 0)
    return int(v) if v == v else 0


def eval_one(s, after, bench, keep=True):
    """Ocena sygnału na danych dziennych. Wejście: otwarcie NASTĘPNEJ sesji + poślizg (sygnał nie jest dostępny przed zamknięciem).
    Jeśli stop i cel mieszczą się w jednej świecy, kolejność jest nieznana -> 'amb' (nie zakładamy korzystnej)."""
    if len(after) < 1:
        return
    entry = float(after.Open.iloc[0]) * (1 + COST)
    bn = bench.loc[bench.index.intersection(after.index)] if bench is not None else None
    for k in (5, 10, 20):
        if len(after) >= k:
            s[f"r{k}"] = round((float(after.Close.iloc[k - 1]) * (1 - COST) / entry - 1) * 100, 2)
            if bn is not None and len(bn) >= k:
                s[f"b{k}"] = round((float(bn.Close.iloc[k - 1]) / float(bn.Open.iloc[0]) - 1) * 100, 2)
    s["mfe"], s["mae"], s["n"] = round((float(after.High.max()) / entry - 1) * 100, 2), round((float(after.Low.min()) / entry - 1) * 100, 2), len(after)
    if keep:
        s["fb"] = [[round(float(b.Open), 2), round(float(b.High), 2), round(float(b.Low), 2), round(float(b.Close), 2), _vol(b)] for b in after.itertuples()]
    s["ex"] = None
    for _, b in after.iterrows():
        hs, ht = b.Low <= s["s"], b.High >= s["t1"]
        if hs or ht:
            s["ex"] = "amb" if hs and ht else "stop" if hs else "t1"
            break


def archive(S, rows):
    cut = time.time() - 7 * 86400
    recent = {(x["sym"], x["setup"]) for x in S if x["ts"] > cut}
    for r in rows:
        p = r["plan"]
        if r["lv"] >= 3 and p and p.get("state") == "teraz" and (r["symbol"], p["setup"]) not in recent:
            S.append({"sym": r["symbol"], "ts": int(time.time()), "bd": r["bar"][0], "bar": r["bar"][1:], "setup": p["setup"], "px": r["price"], "lv": r["lv"],
                      "vs": r["vscore"], "cf": r["conf"], "cp": r.get("compl"), "comps": {k: v[0] for k, v in (r.get("comps") or {}).items()},
                      "e": p["entry"], "s": p["stop"], "t1": p["t1"], "t2": p["t2"]})
    todo = [x for x in S if "r20" not in x and x["ts"] < time.time() - 86400]
    syms = sorted({x["sym"] for x in todo} | {"SPY"})
    bars = {}
    for i in range(0, len(syms), 100):
        d = dl(syms[i:i + 100], "3mo")
        for t in syms[i:i + 100]:
            try:
                bars[t] = d[t].dropna(subset=["Close"])
            except Exception:
                pass
    for x in todo:
        df = bars.get(x["sym"])
        if df is not None:
            eval_one(x, df[df.index.strftime("%Y-%m-%d") > x["bd"]].head(20), bars.get("SPY"))
    return S[-3000:]


def summarize(g):
    o = {"n": len(g), "from": min((x["ts"] for x in g), default=None), "to": max((x["ts"] for x in g), default=None)}
    for k in (5, 10, 20):
        h = [x for x in g if f"r{k}" in x]
        o[f"n{k}"] = len(h)
        if h:
            o[f"w{k}"] = round(100 * sum(x[f"r{k}"] > 0 for x in h) / len(h))
            o[f"a{k}"] = round(sum(x[f"r{k}"] for x in h) / len(h), 2)
            hb = [x for x in h if f"b{k}" in x]
            if hb:
                o[f"x{k}"] = round(sum(x[f"r{k}"] - x[f"b{k}"] for x in hb) / len(hb), 2)
    ev = [x for x in g if "ex" in x]
    o.update(ev=len(ev), t1=sum(x["ex"] == "t1" for x in ev), stop=sum(x["ex"] == "stop" for x in ev), amb=sum(x["ex"] == "amb" for x in ev))
    if ev:
        o["mfe"], o["mae"] = round(sum(x["mfe"] for x in ev) / len(ev), 2), round(sum(x["mae"] for x in ev) / len(ev), 2)
    return o


def sig_stats(S):
    return {st: summarize([x for x in S if x["setup"] == st]) for st in SETUPS}


# ---------- powiadomienia poza aplikacją (Telegram) ----------
def hid(k):
    return hashlib.sha1(("owner:" + k).encode()).hexdigest()[:12]  # w publicznym pliku stanu nie ujawniamy symboli


def parse_rules(txt):
    """Reguły z sekretu NOTIFY_RULES, np.:  AAPL >= 200 | NVDA <= 120 | signal NVDA AAPL | earnings MSFT"""
    rules = []
    for line in (txt or "").splitlines():
        t = line.split("#")[0].split()
        try:
            if t and t[0].lower() in ("signal", "earnings"):
                rules += [(t[0].lower(), x.upper()) for x in t[1:]]
            elif len(t) == 3 and t[1] in (">=", "<="):
                rules.append(("price", t[0].upper(), t[1], float(t[2])))
        except ValueError:
            pass
    return rules


def eval_rules(rules, by_sym, state, now=None):
    now = now or time.time()
    st = {"fired": {k: v for k, v in (state.get("fired") or {}).items() if now - v < 30 * 86400}, "lv": dict(state.get("lv") or {})}
    msgs = []
    for r in rules:
        x = by_sym.get(r[1])
        if not x:
            continue
        if r[0] == "price":
            cond = x["price"] >= r[3] if r[2] == ">=" else x["price"] <= r[3]
            key = hid(f"p:{r[1]}{r[2]}{r[3]}")
            if cond and key not in st["fired"]:
                msgs.append(f"{r[1]}: cena {x['price']} {r[2]} {r[3]}"); st["fired"][key] = now
            elif not cond:
                st["fired"].pop(key, None)
        elif r[0] == "signal":
            key = hid("lv:" + r[1]); prev = st["lv"].get(key)
            if prev is not None and prev < 3 <= x["lv"]:
                msgs.append(f"{r[1]}: nowy sygnał kupna ({['Sprzedaj', 'Unikaj', 'Obserwuj', 'Kupno', 'Silne kupno'][x['lv']]})")
            st["lv"][key] = x["lv"]
        elif r[0] == "earnings" and x.get("earnings_days") is not None and 0 <= x["earnings_days"] <= 3:
            key = hid(f"e:{r[1]}:{time.strftime('%Y-%m', time.gmtime(now))}")
            if key not in st["fired"]:
                msgs.append(f"{r[1]}: wyniki kwartalne za {x['earnings_days']} dni"); st["fired"][key] = now
    return msgs, st


def send_telegram(msgs):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return None
    try:
        return requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": "Owner:\n" + "\n".join(msgs)}, timeout=20).status_code == 200
    except Exception:
        return False


def long_term(r, e):
    """Ocena długoterminowa (12–36 mies.) z danych finansowych. Progi bezwzględne, bez korekty branżowej; None gdy za mało danych."""
    m, y = (e or {}).get("m") or {}, (e or {}).get("y") or {}
    if not m:
        return None
    sc = lambda v, lo, hi: None if v is None else max(0.0, min(1.0, (v - lo) / (hi - lo)))
    inv = lambda v: None if v is None else 1 - v
    avg = lambda xs: (sum(x for x in xs if x is not None) / len([x for x in xs if x is not None])) if any(x is not None for x in xs) else None
    rev = y.get("rev") or []
    cagr = ((rev[-1][1] / rev[0][1]) ** (1 / (len(rev) - 1)) - 1) * 100 if len(rev) >= 3 and (rev[0][1] or 0) > 0 and (rev[-1][1] or 0) > 0 else None
    fcfm = m["fcf"] / m["rev"] * 100 if m.get("fcf") is not None and m.get("rev") else None
    pe = m["pe"] if (m.get("pe") or 0) > 0 else None
    up = (m["target"] / r["price"] - 1) * 100 if m.get("target") and r.get("price") else None
    dy = m["dr"] / r["price"] * 100 if m.get("dr") and r.get("price") else None
    P = {"quality": (avg([sc(m.get("roe"), 5, 25), sc(m.get("om"), 5, 25), sc(m.get("pm"), 3, 20), sc(fcfm, 0, 12)]), .30),
         "growth": (avg([sc(m.get("revg"), 0, 20), sc(cagr, 0, 15)]), .25),
         "value": (avg([inv(sc(pe, 12, 40)), inv(sc(m["fpe"] if (m.get("fpe") or 0) > 0 else None, 12, 35)), inv(sc(m["evebitda"] if (m.get("evebitda") or 0) > 0 else None, 8, 25)), sc(up, -5, 25)]), .20),
         "safety": (avg([inv(sc(m.get("de"), 50, 250)), sc(m.get("cr"), .8, 2.0)]), .15),
         "income": (avg([sc(dy, 0, 4), inv(sc(m.get("payout"), 60, 110))]) if dy else None, .05),
         "trend": (avg([None if r.get("above200") is None else float(r["above200"]), sc(r.get("hi52_pct"), -40, -5)]), .05)}
    av = {k: v for k, v in P.items() if v[0] is not None}
    cov = round(sum(w for _, w in av.values()) * 100)
    if cov < 40 or "quality" not in av and "growth" not in av:
        return None
    s = round(sum(v * w for v, w in av.values()) / sum(w for _, w in av.values()) * 100)
    p = {k: (round(v[0] * 100) if v[0] is not None else None) for k, v in P.items()}
    tr_ok, val_ok = (av["trend"][0] >= .5) if "trend" in av else True, (av["value"][0] >= .3) if "value" in av else True
    act = "Gromadź" if s >= 65 and tr_ok and val_ok else "Obserwuj" if s >= 55 else "Unikaj" if s < 40 else "Trzymaj"
    why = [t for t in (f"ROE {m['roe']:.0f}%" if m.get("roe") is not None else None, f"marża operacyjna {m['om']:.0f}%" if m.get("om") is not None else None, f"wzrost przychodów {m['revg']:.0f}% r/r" if m.get("revg") is not None else None,
                       f"P/E {m['pe']:.0f}" if pe else None, f"cel analityków {up:+.0f}%" if up is not None else None, f"dywidenda {dy:.1f}%" if dy else None) if t]
    fl = [t for t in ("strata netto (brak sensownego P/E)" if (m.get("eps") or 0) < 0 else None, "ujemny free cash flow" if (m.get("fcf") or 0) < 0 else None, "spadek przychodów" if (m.get("revg") or 0) < 0 else None,
                      "wysokie zadłużenie" if (m.get("de") or 0) > 200 else None, "payout > 90%" if (m.get("payout") or 0) > 90 else None, "cena poniżej SMA200" if r.get("above200") is False else None) if t]
    return {"s": s, "l": "Silne" if s >= 70 else "Dobre" if s >= 55 else "Przeciętne" if s >= 40 else "Słabe", "a": act, "cov": cov, "p": p, "why": why, "fl": fl, "up": round(up, 1) if up is not None else None, "tg": m.get("target"), "an": m.get("analysts")}


def main():
    FUND0 = prev_json("fundamentals.json").get("d", {})  # najpierw archiwa: błąd sieci = przerwanie, bez utraty danych
    SIG0 = prev_json("signals.json")
    NEWS0 = prev_json("news.json").get("d", {})
    uni = get_universe()
    syms = list(uni)
    attempted = 0
    fx = fx_rates()
    usd = {c: v["r"] / fx["USD"]["r"] for c, v in fx.items() if v.get("r") and fx.get("USD", {}).get("r")}
    usd["GBX"], usd["PLN"] = usd.get("GBP", 1.3) / 100, (1 / fx["USD"]["r"]) if fx.get("USD", {}).get("r") else 0.26
    bm = {}
    for mk, t in (("DE", "^GDAXI"), ("UK", "^FTSE"), ("PL", "WIG20.WA")):
        try:
            d0 = yf.download(t, period="1y", auto_adjust=True, progress=False)
            d0.columns = d0.columns.get_level_values(0)
            bm[mk] = float(d0.Close.iloc[-1] / d0.Close.iloc[-64] - 1)
        except Exception:
            bm[mk] = None  # brak benchmarku: siła względna nie jest liczona (nie podstawiamy S&P)
    bm["US"] = None
    spy = yf.download("SPY", period="1y", auto_adjust=True, progress=False)
    spy.columns = spy.columns.get_level_values(0)
    spy3m = float(spy.Close.iloc[-1] / spy.Close.iloc[-64] - 1)
    bm_us = spy3m

    # NAJPIERW (przed długim skanem rynku, żeby budżet czasu go nie ucinał): dane finansowe i newsy dla najważniejszych symboli
    FUND, NEWS = FUND0, NEWS0
    NAME.update({s: m.get("name", "") for s, m in uni.items()})
    pre = list(dict.fromkeys([s for s, m in uni.items() if m.get("extra")] + list(uni)[:2300]))
    fstat = {"try": 0, "ok": 0}
    try:
        need_f = [s for s in pre if time.time() - FUND.get(s, {}).get("ts", 0) > 7 * 86400][:FUND_N]
        need_n = [s for s in pre if time.time() - NEWS.get(s, {}).get("ts", 0) > 3 * 3600][:NEWS_N]
        with ThreadPoolExecutor(8) as ex:
            for s, d in ex.map(fin, need_f):
                fstat["try"] += 1
                if d["m"] or d["y"]["rev"]:
                    FUND.setdefault(s, {}).update(d)
                    fstat["ok"] += 1
            for s, items in ex.map(fetch_news, need_n):
                NEWS[s] = {"ts": time.time(), "items": items}
        print(f"Wstępnie: dane finansowe {fstat['ok']}/{fstat['try']}, newsy {len(need_n)}, {elapsed():.1f} min")
    except Exception as e:
        print("wstępne dane:", e)

    # etap 1: cały rynek (1 rok dziennych świec), tylko płynne spółki
    rows = []
    for i in range(0, len(syms), CHUNK):
        if elapsed() > 13:
            print(f"Przekroczono budżet czasu – przeskanowano {i} z {len(syms)}"); break
        attempted = min(i + CHUNK, len(syms))
        data = dl(syms[i:i + CHUNK], "1y")
        if data is None:
            continue
        for s in syms[i:i + CHUNK]:
            try:
                df = data[s].dropna(subset=["Close"])
                m, mk = uni[s], uni[s].get("mkt", "US")
                uf = usd.get(m.get("cur") or "USD", 1.0)
                dv = (df.Close * df.Volume).tail(20).mean() * uf
                ok = m.get("extra") or (mk != "US" and dv >= 2e5) or (mk == "US" and df.Close.iloc[-1] >= 1.5 and dv >= (3e6 if m.get("etf") else 1e6))
                if len(df) >= 70 and ok:
                    rows.append(row(s, df.copy(), m, bm_us if mk == "US" else bm.get(mk), uf))
                    write_hist(s, df)
            except Exception:
                pass
        time.sleep(0.5)
    if len(rows) < 100:
        raise SystemExit(f"Zbyt mało danych ({len(rows)}) – przerywam, żeby nie nadpisać strony")
    print(f"Etap 1: {len(rows)} płynnych spółek, {elapsed():.1f} min")

    def mood_of(rs_):
        N = max(1, len(rs_))
        a50, buy, sell = sum(r["above50"] for r in rs_) / N, sum(r["label"] == "kupno" for r in rs_) / N, sum(r["label"] == "sprzedaż" for r in rs_) / N
        md = ("Byczy", 0.5) if a50 >= .6 and buy > sell else ("Niedźwiedzi", -0.5) if a50 < .4 or sell > buy * 1.5 else ("Mieszany", 0.0)
        return md, {"name": md[0], "a50": round(a50 * 100), "buy": round(buy * 100), "sell": round(sell * 100), "adv": round(sum((r["change_pct"] or 0) > 0 for r in rs_) / N * 100), "n": len(rs_)}
    mood, market = mood_of([r for r in rows if r["mkt"] == "US"] or rows)
    moods, market_by = {"US": mood}, {"US": market}
    for mk in ("DE", "UK", "PL"):
        sub = [r for r in rows if r["mkt"] == mk]
        if len(sub) >= 25:
            moods[mk], market_by[mk] = mood_of(sub)

    # etap 2: Reddit, newsy, analitycy, social, wyniki – dla najciekawszych spółek
    NAME.update({r["symbol"]: r["name"] for r in rows})
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
        verdict(r, moods.get(r['mkt'], mood))

    nt = {"configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")), "rules": 0, "msgs": 0, "sent": None}
    try:
        rules = parse_rules(os.getenv("NOTIFY_RULES", ""))
        try:
            st0 = prev_json("notified.json")
        except Exception:
            st0 = {}
        msgs, st1 = eval_rules(rules, {r["symbol"]: r for r in rows}, st0)
        sent = send_telegram(msgs) if msgs else None
        if msgs and not sent:
            st1 = st0  # nie oznaczaj jako wysłane – spróbujemy przy następnym skanie
        Path("docs").mkdir(exist_ok=True)
        Path("docs/notified.json").write_text(json.dumps(st1, separators=(",", ":")))
        nt.update(rules=len(rules), msgs=len(msgs), sent=sent)
    except Exception as e:
        print("notify:", e)

    # dane finansowe (sprawozdania, wskaźniki, ETF) – uzupełniane stopniowo, ~70 symboli na skan, odświeżane co 7 dni
    try:
        need = []
        keep = {r["symbol"] for r in rows}
        Path("docs").mkdir(exist_ok=True)
        Path("docs/fundamentals.json").write_text(json.dumps({"ts": time.time(), "d": {k: v for k, v in FUND.items() if k in keep}}, separators=(",", ":"), allow_nan=False))
        for s_, it in news.items():
            NEWS[s_] = {"ts": time.time(), "items": it}
        Path("docs/news.json").write_text(json.dumps({"ts": time.time(), "d": {k: v for k, v in NEWS.items() if k in keep and time.time() - v["ts"] < 7 * 86400}}, separators=(",", ":"), allow_nan=False))
        print(f"Dane finansowe: {fstat['ok']} pobranych teraz, {len([k for k in FUND if k in keep])} łącznie; newsy w pamięci: {len(NEWS)}")
    except Exception as e:
        print("fundamentals:", e)

    for r in rows:
        m = (FUND.get(r["symbol"]) or {}).get("m") or {}
        if r["extra"] and m.get("qt"):
            r["etf"] = m["qt"] == "ETF"
            r["index"] = "ETF" if r["etf"] else r["index"]
        r["cur"] = (m.get("cur") if r["extra"] else None) or r["cur"]

    for r in rows:
        r["lt"] = None if r["etf"] else long_term(r, FUND.get(r["symbol"]))

    # poprzedni wynik -> oznacz nowe rekomendacje kupna
    try:
        repo = os.getenv("GITHUB_REPOSITORY", "adrianknothe/owner").split("/")
        old = {x["symbol"]: x.get("lv") for x in requests.get(f"https://{repo[0]}.github.io/{repo[1]}/results.json", timeout=20).json()["results"]}
        for r in rows:
            r["new"] = bool(old) and r["lv"] >= 3 and (old.get(r["symbol"]) or 0) < 3
    except Exception:
        pass

    # historia 5-letnia dla głównych spółek i okazji
    big = [r["symbol"] for r in rows if r["index"] in CORE or r["n100"] or r["plan"] or r["symbol"] in news]
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
    for s, name in [("^GSPC", "S&P 500 (US500)"), ("^NDX", "NASDAQ-100 (US100)"), ("^IXIC", "NASDAQ Composite"), ("^DJI", "Dow Jones (US30)"), ("^RUT", "Russell 2000"), ("^GDAXI", "DAX (Niemcy)"), ("^FTSE", "FTSE 100 (UK)"), ("WIG20.WA", "WIG20 (Polska)"), ("^VIX", "VIX – zmienność")]:
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

    signals = archive(SIG0.get("signals", []), rows)
    for r in rows:
        r.pop("bar", None)
    Path("docs").mkdir(exist_ok=True)
    Path("docs/signals.json").write_text(json.dumps({"updated": time.time(), "cost_pct": COST * 100, "signals": signals, "stats": sig_stats(signals)}, separators=(",", ":"), allow_nan=False))
    fng = jget("https://production.dataviz.cnn.io/index/fearandgreed/graphdata").get("fear_and_greed", {})
    top_reddit = [{"s": k, **v} for k, v in sorted(reddit.items(), key=lambda kv: kv[1]["rank"])[:12]]
    out = {"updated_at": time.time(), "indices": idx, "market": market, "market_by": market_by, "fng": {"score": n(fng.get("score"), 0), "rating": fng.get("rating")} if fng else None,
           "market_news": market_news, "news": news, "reddit": top_reddit, "st_trending": st_trend, "scanned": len(syms), "fx": fx,
           "diag": {"universe": len(syms), "attempted": attempted, "processed": len(rows), "skipped": attempted - len(rows), "cut": attempted < len(syms),
                    "news": len(news), "fund": len(FUND), "fund_try": fstat["try"], "fund_ok": fstat["ok"], "news_cached": len(NEWS), "reddit": len(reddit), "stocktwits": ST_FAIL[0] < 3 and bool(st_trend), "fng": bool(fng), "notify": nt, "fx": len(fx) > 1, "minutes": round(elapsed(), 1)},
           "results": rows}
    Path("docs").mkdir(exist_ok=True)
    Path("docs/results.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    print(f"OK: {len(rows)} spółek (z {len(syms)}), {sum(r['lv'] >= 3 for r in rows)} rekomendacji kupna, {elapsed():.1f} min")


if __name__ == "__main__":
    main()
