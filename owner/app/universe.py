"""Uniwersum: cały rynek USA (akcje + ETF z nasdaqtrader.com), członkostwo w indeksach (Wikipedia)
oraz własne symbole z pliku extra_tickers.txt (np. ETF-y europejskie z XTB w formacie Yahoo: VWCE.DE)."""
import io
import os
import re
import time

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
WIKI = [("S&P 500", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
        ("NASDAQ-100", "https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
        ("S&P 400", "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol"),
        ("S&P 600", "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", "Symbol")]
EXCH = {"Q": "NASDAQ", "N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe"}
POPULAR_ETF = """SPY VOO IVV VTI QQQ QQQM IWM DIA RSP SPLG SCHB ITOT SCHX VUG VTV IWF IWD MGK IJH IJR MDY VB VO
XLK XLF XLE XLV XLY XLP XLI XLU XLB XLRE XLC SMH SOXX XSD IGV VGT FTEC IYW XBI IBB KRE KBE XME XOP OIH ITA JETS URA COPX
GLD IAU SLV GDX GDXJ USO UNG DBC PDBC TLT IEF SHY AGG BND LQD HYG JNK TIP BIL SGOV SHV MUB EMB
VEA VWO EFA EEM IEMG IXUS VXUS VGK EWJ EWZ EWW FXI MCHI KWEB INDA EWY EWT EWG ACWI VT
SCHD VYM DVY VIG DGRO NOBL HDV SDY JEPI JEPQ QYLD XYLD DIVO SPYD FDVV SCHY VNQ VNQI IYR
ARKK ARKW ARKG TQQQ SQQQ SOXL SOXS UPRO SPXL SPXS TNA TZA UVXY VXX SVXY BITO IBIT FBTC ETHA GBTC BLOK
MTUM QUAL USMV VLUE SIZE MOAT COWZ CALF RPV VBR IWN IWO""".split()
EU = [("DAX", "DE", ".DE", "XETRA", "EUR", "https://en.wikipedia.org/wiki/DAX"), ("MDAX", "DE", ".DE", "XETRA", "EUR", "https://en.wikipedia.org/wiki/MDAX"),
      ("SDAX", "DE", ".DE", "XETRA", "EUR", "https://en.wikipedia.org/wiki/SDAX"), ("FTSE 100", "UK", ".L", "LSE", "GBX", "https://en.wikipedia.org/wiki/FTSE_100_Index"),
      ("FTSE 250", "UK", ".L", "LSE", "GBX", "https://en.wikipedia.org/wiki/FTSE_250_Index"), ("WIG20", "PL", ".WA", "GPW", "PLN", "https://en.wikipedia.org/wiki/WIG20"),
      ("mWIG40", "PL", ".WA", "GPW", "PLN", "https://pl.wikipedia.org/wiki/MWIG40"), ("sWIG80", "PL", ".WA", "GPW", "PLN", "https://pl.wikipedia.org/wiki/SWIG80")]
# Zapasowe listy (gdy Wikipedia nie odpowiada lub zmieni układ tabel). Symbole bez danych w Yahoo są po prostu pomijane przy skanie.
SEEDS = {"DAX": "ADS AIR ALV BAS BAYN BEI BMW BNR CBK CON 1COV DTG DBK DB1 DHL DTE EOAN FRE FME HNR1 HEI HEN3 IFX MBG MRK MTX MUV2 P911 PAH3 QIA RHM RWE SAP SRT3 SIE ENR SHL SY1 VOW3 VNA ZAL".split(),
         "FTSE 100": "AZN SHEL HSBA ULVR BP RIO GSK DGE BATS LSEG REL NG BARC LLOY VOD GLEN AAL CPG RKT TSCO NWG STAN PRU AV LGEN BA RR IMB EXPN CRH ANTO III SSE BT-A WPP".split(),
         "WIG20": "PKN PKO PZU KGH PEO DNP LPP CDR ALE PGE OPL SPL KRU CPS ALR MBK JSW KTY TPE PCO".split(),
         "mWIG40": "ACP APR ASB BDX CAR CCC CIE CMR DOM ENA EUR GPW ING MIL NEU TXT VRC XTB 11B".split()}
_cache = {"t": 0, "data": {}}


def _wiki(url, col):
    html = requests.get(url, headers=UA, timeout=30).text
    for t in pd.read_html(io.StringIO(html)):
        if col in t.columns:
            sec = t["GICS Sector"] if "GICS Sector" in t.columns else [""] * len(t)
            name = t["Security"] if "Security" in t.columns else t["Company"] if "Company" in t.columns else [""] * len(t)
            return list(zip(t[col].astype(str), sec, name))
    raise ValueError("brak tabeli")


SYM_COLS = ("ticker", "symbol", "epic", "ticker symbol", "kod", "skrót", "symbol giełdowy", "tidm")
NAME_COLS = ("company", "name", "spółka", "nazwa", "security", "constituent")


def parse_eu_html(html, suffix):
    """Tolerancyjny parser tabeli składu indeksu: szuka kolumny z tickerem i nazwą, zwraca [(symbol_yahoo, nazwa, sektor)]."""
    best = []
    for t in pd.read_html(io.StringIO(html)):
        cols = {str(c).strip().lower(): c for c in t.columns}
        sc = next((cols[c] for c in SYM_COLS if c in cols), None)
        if sc is None:
            continue
        nc = next((cols[c] for c in NAME_COLS if c in cols), None)
        sec = next((c for k, c in cols.items() if any(w in k for w in ("sector", "industry", "branża", "sektor"))), None)
        out = []
        for _, r in t.iterrows():
            s = str(r[sc]).strip().upper().rstrip(".")
            s = s[:-len(suffix)] if s.endswith(suffix) else s
            s = s.replace(".", "-").replace(" ", "")
            if re.fullmatch(r"[A-Z0-9]{1,6}(-[A-Z0-9]{1,2})?", s):
                out.append((s + suffix, str(r[nc])[:40] if nc is not None else "", str(r[sec]) if sec is not None and r[sec] == r[sec] else ""))
        if len(out) > len(best):
            best = out
    return best if len(best) >= 15 else []


def _eu():
    out = {}
    for label, mkt, suf, exch, cur, url in EU:
        got = []
        try:
            got = parse_eu_html(requests.get(url, headers=UA, timeout=30).text, suf)
        except Exception as e:
            print(f"[universe] {label}: {e}")
        for s in SEEDS.get(label, []):
            if not any(g[0] == s + suf for g in got):
                got.append((s + suf, "", ""))
        for s, name, sec in got:
            out.setdefault(s, {"index": label, "n100": False, "etf": False, "sector": sec, "name": name, "exch": exch, "mkt": mkt, "cur": cur})
    return out


def _trader():
    base, out = "https://www.nasdaqtrader.com/dynamic/SymDir/", {}
    for fn, sc, ex in (("nasdaqlisted.txt", "Symbol", None), ("otherlisted.txt", "ACT Symbol", "Exchange")):
        df = pd.read_csv(io.StringIO(requests.get(base + fn, headers=UA, timeout=30).text), sep="|", dtype=str)
        df = df[df[sc].notna() & ~df[sc].str.startswith("File Creation") & (df["Test Issue"] == "N")]
        bad = df["Security Name"].str.contains(r"Warrant|Right|Unit|Preferred|Depositary|Notes|Acquisition Corp|Trust", case=False, regex=True, na=False)
        for _, r in df[(df["ETF"] == "Y") | ~bad].iterrows():
            s = r[sc].strip().upper()
            if s and "$" not in s:
                out[s.replace(".", "-")] = {"exch": EXCH.get(r[ex], "US") if ex else "NASDAQ", "name": str(r["Security Name"]).split(" - ")[0][:40], "etf": r["ETF"] == "Y"}
    return out


def _extras():
    for p in ("extra_tickers.txt", "owner/extra_tickers.txt"):
        if os.path.exists(p):
            txt = "\n".join(l.split("#")[0] for l in open(p, encoding="utf-8"))
            return [t.upper() for t in re.split(r"[,\s]+", txt) if t]
    return []


def get_universe() -> dict:
    """{symbol: {index, n100, etf, extra, sector, name, exch}}. Kolejność: moje, indeksy, popularne ETF, reszta. Cache 24 h."""
    if _cache["data"] and time.time() - _cache["t"] < 86400:
        return _cache["data"]
    out = {}
    for label, url, col in WIKI:
        try:
            for s, sec, name in _wiki(url, col):
                s = s.strip().upper().replace(".", "-")
                m = out.setdefault(s, {"index": label, "n100": False, "etf": False, "sector": str(sec) if sec == sec else "", "name": str(name)[:40], "exch": ""})
                if label == "NASDAQ-100":
                    m["n100"] = True
        except Exception as e:
            print(f"[universe] {label}: {e}")
    try:
        tr = _trader()
        eu = {}
        try:
            eu = _eu()
        except Exception as e:
            print(f"[universe] EU: {e}")
        for s in POPULAR_ETF + list(eu) + list(tr):
            if s in eu:
                out.setdefault(s, eu[s])
                continue
            m = tr.get(s)
            if not m:
                continue
            if s in out:
                out[s]["exch"] = out[s]["exch"] or m["exch"]
                out[s]["name"] = out[s]["name"] or m["name"]
            else:
                out[s] = {"index": "ETF" if m["etf"] else "Inne USA", "n100": False, "sector": "", **m}
    except Exception as e:
        print(f"[universe] nasdaqtrader: {e}")
    ex = _extras()
    uni = {}
    for s in ex:
        uni[s] = {**out.get(s, {"index": "Moje", "n100": False, "etf": False, "sector": "", "name": "", "exch": ""}), "extra": True}
    for s, m in out.items():
        uni.setdefault(s, m)
    if not uni:
        uni = {s: {"index": "—", "n100": False, "etf": False, "sector": "", "name": "", "exch": ""} for s in "AAPL MSFT NVDA AMZN GOOGL META TSLA".split()}
    _cache.update(t=time.time(), data=uni)
    print(f"[universe] {len(uni)} symboli (w tym {len(ex)} własnych)")
    return uni
