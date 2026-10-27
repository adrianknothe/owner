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
    df["SMA20"], df["SMA50"] = c.rolling(20).mean(), c.rolling(50).mean()
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


def sentiment(title: str) -> int:
    w = set(title.lower().replace(",", " ").replace(".", " ").split())
    return len(w & POS) - len(w & NEG)
