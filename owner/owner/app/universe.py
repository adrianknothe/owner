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
_cache = {"t": 0, "data": {}}


def _wiki(url, col):
    html = requests.get(url, headers=UA, timeout=30).text
    for t in pd.read_html(io.StringIO(html)):
        if col in t.columns:
            sec = t["GICS Sector"] if "GICS Sector" in t.columns else [""] * len(t)
            name = t["Security"] if "Security" in t.columns else t["Company"] if "Company" in t.columns else [""] * len(t)
            return list(zip(t[col].astype(str), sec, name))
    raise ValueError("brak tabeli")


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
        for s in POPULAR_ETF + list(tr):
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
