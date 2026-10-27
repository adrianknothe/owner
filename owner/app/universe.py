"""Lista spółek: S&P 500 + NASDAQ-100 + S&P 400 (mid cap) + S&P 600 (small cap) z Wikipedii."""
import io
import time

import pandas as pd
import requests

SOURCES = {
    "S&P 500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol", "GICS Sector"),
    "NASDAQ-100": ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker", "GICS Sector"),
    "S&P 400": ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "Symbol", "GICS Sector"),
    "S&P 600": ("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", "Symbol", "GICS Sector"),
}
FALLBACK = "AAPL MSFT NVDA AMZN GOOGL META TSLA AMD NFLX AVGO JPM XOM".split()
_cache = {"t": 0, "data": {}}


def _table(url, sym_col, sec_col):
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0 owner-scanner"}, timeout=30).text
    for t in pd.read_html(io.StringIO(html)):
        if sym_col in t.columns:
            sec = t[sec_col] if sec_col in t.columns else ""
            return pd.DataFrame({"sym": t[sym_col].astype(str), "sector": sec})
    raise ValueError("brak tabeli")


def get_universe() -> dict:
    """Zwraca {symbol: {"index": ..., "sector": ...}}, odświeżane raz na dobę."""
    if _cache["data"] and time.time() - _cache["t"] < 86400:
        return _cache["data"]
    out = {}
    for name, (url, sc, sec) in SOURCES.items():
        try:
            for _, r in _table(url, sc, sec).iterrows():
                s = r.sym.strip().upper().replace(".", "-")
                out.setdefault(s, {"index": name, "sector": str(r.sector)})
        except Exception as e:
            print(f"[universe] {name}: {e}")
    if not out:
        out = {s: {"index": "—", "sector": ""} for s in FALLBACK}
    _cache.update(t=time.time(), data=out)
    return out
