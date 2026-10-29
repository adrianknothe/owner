import math
import re
import pandas as pd

POS = {"beat", "beats", "surge", "surges", "soar", "soars", "jump", "jumps", "upgrade", "record",
       "growth", "rally", "gain", "gains", "profit", "outperform", "bullish", "raises", "strong"}
NEG = {"miss", "misses", "plunge", "plunges", "drop", "drops", "fall", "falls", "downgrade", "lawsuit",
       "probe", "loss", "losses", "cut", "cuts", "weak", "bearish", "recall", "layoffs", "fraud", "warning"}


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"]
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["RSI"] = 100 - 100 / (1 + up / down.replace(0, 1e-9))
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIG"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["SMA20"], df["SMA50"], df["SMA200"] = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    sd = c.rolling(20).std()
    df["BB_UP"], df["BB_LO"] = df["SMA20"] + 2 * sd, df["SMA20"] - 2 * sd
    df["VOL_RATIO"] = df["Volume"] / df["Volume"].rolling(20).mean()
    return df


def signal(df: pd.DataFrame) -> dict:
    """Score -5..+5 from simple technical rules. Informational only, not advice."""
    r, p = df.iloc[-1], df.iloc[-2]
    score, why = 0, []
    if r.RSI < 30: score += 1; why.append("RSI < 30 (wyprzedanie)")
    elif r.RSI > 70: score -= 1; why.append("RSI > 70 (wykupienie)")
    if p.MACD < p.MACD_SIG and r.MACD > r.MACD_SIG: score += 1; why.append("MACD przecina sygnał w górę")
    elif p.MACD > p.MACD_SIG and r.MACD < r.MACD_SIG: score -= 1; why.append("MACD przecina sygnał w dół")
    if r.Close > r.SMA20 > r.SMA50: score += 1; why.append("Cena > SMA20 > SMA50 (trend wzrostowy)")
    elif r.Close < r.SMA20 < r.SMA50: score -= 1; why.append("Cena < SMA20 < SMA50 (trend spadkowy)")
    if r.Close < r.BB_LO: score += 1; why.append("Cena poniżej dolnej wstęgi Bollingera")
    elif r.Close > r.BB_UP: score -= 1; why.append("Cena powyżej górnej wstęgi Bollingera")
    if r.VOL_RATIO > 1.8:
        score += 1 if r.Close > p.Close else -1
        why.append(f"Skok wolumenu x{r.VOL_RATIO:.1f}")
    label = "kupno" if score >= 2 else "sprzedaż" if score <= -2 else "neutralnie"
    return {"score": int(score), "label": label, "reasons": why}


def extra(df: pd.DataFrame) -> pd.DataFrame:
    """ATR, ADX i 20-dniowe maksimum (do wybić)."""
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    up, dn = h.diff(), -l.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    mdm = dn.where((dn > up) & (dn > 0), 0.0)
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
    mdi = 100 * mdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9)
    df["ATR"], df["ADX"] = atr, dx.ewm(alpha=1 / 14, adjust=False).mean()
    df["HH20"] = h.rolling(20).max().shift()
    return df


def plan(df: pd.DataFrame, sig: dict, rs: float):
    """Plan transakcji (long) oparty o ATR. Zwraca None, jeśli brak setupu. Nie jest poradą inwestycyjną."""
    r, p = df.iloc[-1], df.iloc[-2]
    px, atr = float(r.Close), float(r.ATR)
    if not atr > 0 or sig["score"] < 1:
        return None
    macd_up = (r.MACD - r.MACD_SIG) > (p.MACD - p.MACD_SIG)
    if r.Close > r.HH20 and r.VOL_RATIO > 1.3 and r.ADX > 20:
        kind, hor = "Wybicie", "3–10 sesji"
    elif r.Close > r.SMA20 > r.SMA50 and r.ADX > 22 and 45 < r.RSI < 68 and px - r.SMA20 < 1.2 * atr:
        kind, hor = "Trend", "5–15 sesji"
    elif r.RSI < 35 and macd_up:
        kind, hor = "Odbicie", "2–6 sesji"
    else:
        return None
    q = 40 + 8 * sig["score"] + (15 if r.ADX > 25 else 8 if r.ADX > 20 else 0)
    q += max(-10, min(10, rs * 50)) + (8 if r.VOL_RATIO > 1.5 else 0) - (12 if r.RSI > 75 else 0)
    risk = 1.5 * atr
    ref = float(r.HH20) if kind == "Wybicie" else float(r.SMA20) if kind == "Trend" else None
    wait = ref is not None and (px - ref) / atr > (1.0 if kind == "Wybicie" else 0.8)   # cena oddalona od poziomu wejścia
    pull = round(ref + 0.3 * atr, 2) if wait else None
    zlo, zhi = (round(ref, 2), pull) if wait else (round(max(ref, px - 0.5 * atr) if ref is not None else px - 0.3 * atr, 2), round(px, 2))
    t1, t2 = px + 1.5 * risk, px + 3 * risk
    out = {"setup": kind, "quality": int(max(0, min(100, q))), "entry": round(px, 2), "stop": round(px - risk, 2), "t1": round(t1, 2), "t2": round(t2, 2),
           "horizon": hor, "atr_pct": round(atr / px * 100, 2), "state": "czekaj" if wait else "teraz", "pull": pull, "zlo": zlo, "zhi": zhi,
           "up1": round((t1 / px - 1) * 100, 1), "up2": round((t2 / px - 1) * 100, 1), "dn": round((-risk / px) * 100, 1), "rng10": round(atr / px * 100 * math.sqrt(10), 1)}
    if wait:
        out["alt"] = {"entry": pull, "stop": round(pull - risk, 2), "t1": round(pull + 1.5 * risk, 2), "t2": round(pull + 3 * risk, 2),
                      "up1": round((1.5 * risk / pull) * 100, 1), "up2": round((3 * risk / pull) * 100, 1)}
    return out


PHRASES = {
    "beats estimates": 2, "beat estimates": 2, "tops estimates": 2, "raises guidance": 2, "raised guidance": 2, "raises outlook": 2,
    "price target raised": 2, "raises price target": 2, "record revenue": 2, "record profit": 2, "record high": 1, "upgraded": 2,
    "upgrades": 2, "buyback": 1, "strong demand": 1, "surges": 2, "soars": 2, "jumps": 1, "rallies": 1, "outperform": 1,
    "approval": 1, "approved": 1, "wins contract": 2, "partnership": 1, "expands": 1, "beats": 1,
    "misses estimates": -2, "missed estimates": -2, "cuts guidance": -2, "lowers guidance": -2, "cuts outlook": -2,
    "price target cut": -2, "lowers price target": -2, "downgraded": -2, "downgrades": -2, "sec investigation": -2,
    "class action": -2, "lawsuit": -1, "recall": -1, "plunges": -2, "tumbles": -2, "sinks": -2, "slides": -1, "falls": -1,
    "drops": -1, "layoffs": -1, "bankruptcy": -3, "fraud": -3, "probe": -1, "warning": -1, "halts": -1, "delisting": -3,
    "misses": -1, "short seller": -2, "data breach": -2,
}


def sentiment(title: str) -> int:
    """Ocena tytułu -3..+3 na podstawie słownika fraz finansowych (orientacyjna)."""
    t = title.lower()
    return max(-3, min(3, sum(v for k, v in PHRASES.items() if re.search(r"\b" + re.escape(k), t))))
