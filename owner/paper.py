"""Symulator portfela papierowego (agent w trybie testowym). Deterministyczny, bez prawdziwych zleceń.

Zasady (wersja 1.0):
 - decyzje tylko na zamkniętych sesjach; zlecenie powstaje po sygnale i jest wypełniane po OTWARCIU następnej sesji (+ poślizg, koszty),
 - zlecenie anulowane, gdy otwarcie jest poniżej stopa (luka) albo ponad 0,5% powyżej strefy wejścia,
 - stop i cel w jednej świecy = stop (nie zakładamy korzystnej kolejności); połowa pozycji na celu 1 (stop do punktu wejścia), reszta na celu 2,
   po zamknięciu poniżej SMA20 lub po limicie sesji,
 - limity: ryzyko na transakcję, waga pozycji, sektor, liczba pozycji, strata dzienna/tygodniowa, kill switch przy maksymalnym obsunięciu,
 - bez dywidend, podatków i walut (tylko USA w USD). Wynik NIE jest dowodem przewagi przed ≥100 transakcjami."""
import json
import math
import os
from datetime import datetime, timezone

VERSION = "1.0"
DEFAULTS = {"enabled": True, "capital": 10000.0, "risk_pct": 1.0, "max_positions": 8, "max_weight_pct": 20.0, "max_sector_pct": 40.0, "cost_pct": 0.1, "slippage_pct": 0.05,
            "daily_loss_limit_pct": 3.0, "weekly_loss_limit_pct": 6.0, "max_drawdown_halt_pct": 15.0, "min_quality": 60, "min_confirm_frac": 0.6, "min_dvol_musd": 20.0,
            "allow_etf": False, "markets": ["US"], "max_hold_sessions": 15, "cooldown_sessions": 5, "reset_halt": False}


def load_cfg(paths=("paper_config.json", "owner/paper_config.json")):
    cfg = dict(DEFAULTS)
    for p in paths:
        if os.path.exists(p):
            try:
                cfg.update(json.load(open(p, encoding="utf-8")))
            except Exception as e:
                print("paper_config:", e)
            break
    return _sane(cfg)


def _sane(c):
    c = dict(c)
    c["capital"] = float(c["capital"]) if float(c["capital"]) > 0 else DEFAULTS["capital"]
    c["risk_pct"] = min(5.0, max(0.05, float(c["risk_pct"])))
    c["max_weight_pct"] = min(100.0, max(1.0, float(c["max_weight_pct"])))
    c["max_positions"] = max(1, int(c["max_positions"]))
    return c


def new_state(cfg, now):
    return {"v": 1, "version": VERSION, "start": {"capital": cfg["capital"], "ts": int(now)}, "cash": float(cfg["capital"]), "positions": [], "pending": [], "closed": [],
            "curve": [], "journal": [], "todo": [], "halt": None, "rej": []}


def xtb(sym):
    return sym.replace("-", ".") + ".US"


def _today(now):
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")


def _after_close(now):
    t = datetime.fromtimestamp(now, timezone.utc)
    return t.hour * 60 + t.minute >= 21 * 60 + 15


def _completed(df, now):
    """Tylko zakończone sesje: dzisiejsza świeca liczy się dopiero po 21:15 UTC (inaczej to częściowy odczyt)."""
    if df is None or not len(df):
        return None
    t = _today(now)
    return df[[d < t or (d == t and _after_close(now)) for d in df.index.strftime("%Y-%m-%d")]]


def _log(S, now, typ, sym, text, todo=None, **kw):
    S["journal"].append({"ts": int(now), "t": typ, "s": sym, "m": text, **kw})
    S["journal"] = S["journal"][-400:]
    if todo:
        S["todo"].append({"ts": int(now), "k": todo, "s": sym, "x": xtb(sym), "m": text})


def _process_pending(S, comp, cfg, now):
    slip, cst, keep = cfg["slippage_pct"] / 100, cfg["cost_pct"] / 100, []
    for o in S["pending"]:
        df = comp.get(o["sym"])
        nb = df[df.index.strftime("%Y-%m-%d") > o["bd"]] if df is not None else None
        if nb is None or not len(nb):
            if now - o["ts"] > 7 * 86400:
                _log(S, now, "cancel", o["sym"], "Zlecenie wygasło (brak danych przez 7 dni)")
            else:
                keep.append(o)
            continue
        op, d = float(nb.iloc[0].Open), nb.index[0].strftime("%Y-%m-%d")
        why = "otwarcie poniżej stopa (luka)" if op <= o["stop"] else "cena uciekła powyżej strefy wejścia" if op > o["zhi"] * 1.005 else None
        px = op * (1 + slip)
        sh = min(o["shares"], int(S["cash"] / (px * (1 + cst)))) if not why else 0
        if not why and sh < 1:
            why = "brak gotówki"
        if why:
            _log(S, now, "cancel", o["sym"], f"Zlecenie anulowane: {why} (otwarcie {op:.2f}, strefa {o['zlo']}–{o['zhi']})", d=d)
            continue
        fee = px * sh * cst
        S["cash"] -= px * sh + fee
        S["positions"].append({"sym": o["sym"], "name": o.get("name", ""), "sector": o.get("sector", ""), "setup": o["setup"], "shares": sh, "shares0": sh, "entry": px, "entry_d": d,
                               "stop": o["stop"], "stop0": o["stop"], "t1": o["t1"], "t2": o["t2"], "fees": fee, "realized": 0.0, "proceeds": 0.0, "sold": 0, "half": False,
                               "hold": 0, "last": o["bd"], "mark": px, "why": o.get("why", [])})
        _log(S, now, "fill", o["sym"], f"Kupiono {sh} szt. po {px:.2f} (otwarcie {d} + poślizg)", d=d)
    S["pending"] = keep


def _sell(S, p, qty, px, d, reason, cfg, now):
    net = px * (1 - cfg["slippage_pct"] / 100)
    proceeds = net * qty
    fee = proceeds * cfg["cost_pct"] / 100
    S["cash"] += proceeds - fee
    p["realized"] += proceeds - fee - p["entry"] * qty
    p["proceeds"] += proceeds
    p["sold"] += qty
    p["shares"] -= qty
    _log(S, now, "exit", p["sym"], f"Sprzedano {qty} szt. {p['sym']} po {net:.2f} – {reason} ({d})", todo="sell", d=d)


def _manage(S, comp, cfg, now):
    keep = []
    for p in S["positions"]:
        df = comp.get(p["sym"])
        if df is None:
            keep.append(p)
            continue
        sma = df.Close.rolling(20).mean()
        for ts, b in df[df.index.strftime("%Y-%m-%d") > p["last"]].iterrows():
            d = ts.strftime("%Y-%m-%d")
            op, hi, lo, cl = (float(b[k]) for k in ("Open", "High", "Low", "Close"))
            p["hold"] += 1
            p["last"], p["mark"] = d, cl
            if lo <= p["stop"]:   # stop ma pierwszeństwo także przy świecy z celem (nie zakładamy korzystnej kolejności)
                _sell(S, p, p["shares"], min(op, p["stop"]), d, "stop" if not p["half"] else "stop (po realizacji części)", cfg, now)
            else:
                if not p["half"] and hi >= p["t1"]:
                    q = p["shares"] // 2 if p["shares"] >= 2 else p["shares"]
                    _sell(S, p, q, max(op, p["t1"]), d, "cel 1", cfg, now)
                    p["half"], p["stop"] = True, p["entry"]
                if p["shares"] > 0 and p["half"] and hi >= p["t2"]:
                    _sell(S, p, p["shares"], max(op, p["t2"]), d, "cel 2", cfg, now)
                elif p["shares"] > 0 and p["half"] and sma.loc[ts] == sma.loc[ts] and cl < sma.loc[ts]:
                    _sell(S, p, p["shares"], cl, d, "zamknięcie poniżej SMA20", cfg, now)
                elif p["shares"] > 0 and p["hold"] >= cfg["max_hold_sessions"]:
                    _sell(S, p, p["shares"], cl, d, "wyjście czasowe", cfg, now)
            if p["shares"] <= 0:
                pnl = p["realized"] - p["fees"]
                S["closed"].append({"sym": p["sym"], "name": p["name"], "setup": p["setup"], "entry_d": p["entry_d"], "exit_d": d, "shares": p["shares0"], "entry": round(p["entry"], 2),
                                    "exit": round(p["proceeds"] / p["sold"], 2), "pnl": round(pnl, 2), "pnl_pct": round(pnl / (p["entry"] * p["shares0"]) * 100, 2),
                                    "r": round(pnl / (p["shares0"] * max(p["entry"] - p["stop0"], 1e-9)), 2), "hold": p["hold"]})
                S["closed"] = S["closed"][-500:]
                break
        else:
            keep.append(p)
            continue
        if p["shares"] > 0:
            keep.append(p)
    S["positions"] = keep


def _equity(S):
    return S["cash"] + sum(p["shares"] * p["mark"] for p in S["positions"])


def _curve(S, comp, eq):
    ref = comp.get("SPY")
    if ref is None or not len(ref):
        return
    d = ref.index[-1].strftime("%Y-%m-%d")
    pt = {"d": d, "e": round(eq, 2), "spy": round(float(ref.Close.iloc[-1]), 2), "cash": round(S["cash"], 2), "n": len(S["positions"])}
    if S["curve"] and S["curve"][-1]["d"] == d:
        S["curve"][-1] = pt
    elif not S["curve"] or d > S["curve"][-1]["d"]:
        S["curve"].append(pt)


def _limits(S, cfg, eq, now):
    cur, cap = S["curve"], S["start"]["capital"]
    peak = max([c["e"] for c in cur] + [eq, cap])
    dd = (eq / peak - 1) * 100
    prev = cur[-2]["e"] if len(cur) >= 2 else cap
    wk = cur[-6]["e"] if len(cur) >= 6 else cap
    day, week = (eq / prev - 1) * 100, (eq / wk - 1) * 100
    if dd <= -cfg["max_drawdown_halt_pct"] and not S["halt"]:
        S["halt"] = {"reason": f"obsunięcie {dd:.1f}% przekroczyło limit {cfg['max_drawdown_halt_pct']}%", "ts": int(now)}
        _log(S, now, "limit", "", "KILL SWITCH: " + S["halt"]["reason"] + " – nowe wejścia zatrzymane do ręcznego wznowienia (reset_halt)")
    blocked = (["kill switch"] if S["halt"] else []) + (["limit straty dziennej"] if day <= -cfg["daily_loss_limit_pct"] else []) + (["limit straty tygodniowej"] if week <= -cfg["weekly_loss_limit_pct"] else [])
    return {"dd": round(dd, 2), "day": round(day, 2), "week": round(week, 2), "peak": round(peak, 2), "blocked": blocked}


def _new_orders(S, rows, cfg, eq, lim, now):
    if not any(True for _ in rows):
        return
    today, cst = _today(now), cfg["cost_pct"] / 100
    held = {p["sym"] for p in S["positions"]} | {o["sym"] for o in S["pending"]}
    recent = {c["sym"]: c["exit_d"] for c in S["closed"][-60:]}
    expo = {}
    for p in S["positions"]:
        expo[p["sector"]] = expo.get(p["sector"], 0) + p["shares"] * p["mark"]
    for o in S["pending"]:
        expo[o["sector"]] = expo.get(o["sector"], 0) + o["shares"] * o["entry"]
    reserved = sum(o["shares"] * o["entry"] * (1 + cst) for o in S["pending"])
    seen, nrej = set(S["rej"]), 0
    cands = sorted([r for r in rows if r.get("lv", 0) >= 3 and r.get("plan") and r.get("bar")], key=lambda r: (-r["vscore"], -r["plan"]["quality"], r["symbol"]))
    for r in cands[:40]:
        bd, p, sym = r["bar"][0], r["plan"], r["symbol"]
        if not (bd < today or _after_close(now)):
            continue   # sygnał na niezakończonej sesji – czekamy
        cf = r.get("cf")
        sec = r.get("sector") or (r.get("fund") or {}).get("sector") or "—"
        why = []
        if r.get("mkt", "US") not in cfg["markets"]:
            why.append("rynek poza symulacją")
        if r.get("etf") and not cfg["allow_etf"]:
            why.append("ETF wyłączone")
        if (r.get("dvol") or 0) < cfg["min_dvol_musd"]:
            why.append("zbyt mały obrót")
        if p["quality"] < cfg["min_quality"]:
            why.append(f"jakość setupu {p['quality']} < {cfg['min_quality']}")
        if cf and cf[1] and cf[0] / cf[1] < cfg["min_confirm_frac"]:
            why.append("za mało potwierdzeń technicznych")
        if r.get("earnings_days") is not None and r["earnings_days"] <= 5:
            why.append(f"wyniki za {r['earnings_days']} dni")
        if p["state"] != "teraz":
            why.append("czekaj na cofnięcie (cena oddalona od wejścia)")
        if sym in held:
            continue
        if sym in recent and bd <= recent[sym]:
            continue
        if lim["blocked"]:
            why.append("limity ryzyka: " + ", ".join(lim["blocked"]))
        if len(S["positions"]) + len(S["pending"]) >= cfg["max_positions"]:
            why.append("osiągnięto maksymalną liczbę pozycji")
        if expo.get(sec, 0) / max(eq, 1) * 100 >= cfg["max_sector_pct"]:
            why.append(f"limit sektora {sec}")
        shares = 0
        if not why:
            rps = (p["entry"] - p["stop"]) + p["entry"] * cst * 2
            shares = int(min(eq * cfg["risk_pct"] / 100 / rps, eq * cfg["max_weight_pct"] / 100 / p["entry"], (S["cash"] - reserved) / (p["entry"] * (1 + cst))))
            if shares < 1:
                why.append("zbyt mała pozycja przy tych limitach")
        if why:
            key = f"{sym}|{bd}|{why[0]}"
            if key not in seen and nrej < 15:
                _log(S, now, "reject", sym, f"Odrzucono {sym} ({p['setup']}): " + "; ".join(why), d=bd)
                S["rej"] = (S["rej"] + [key])[-400:]
                nrej += 1
            continue
        o = {"id": f"{sym}-{bd}", "sym": sym, "name": r.get("name", ""), "sector": sec, "setup": p["setup"], "bd": bd, "ts": int(now), "entry": p["entry"], "zlo": p["zlo"], "zhi": p["zhi"], "stop": p["stop"],
             "t1": p["t1"], "t2": p["t2"], "shares": shares, "up1": p["up1"], "dn": p["dn"], "quality": p["quality"], "vscore": r["vscore"],
             "why": (r.get("reasons") or [])[:3] + ([f"potwierdzenia {cf[0]}/{cf[1]}"] if cf else []),
             "pt": ((r.get("mc") or {}).get("sc") or {}).get("neutral", {}).get("pt")}
        S["pending"].append(o)
        reserved += shares * p["entry"] * (1 + cst)
        expo[sec] = expo.get(sec, 0) + shares * p["entry"]
        _log(S, now, "order", sym, f"Zlecenie kupna {shares} szt. {sym} ({p['setup']}) w strefie {p['zlo']}–{p['zhi']}, stop {p['stop']} ({p['dn']}%), cel 1 {p['t1']} (+{p['up1']}%), cel 2 {p['t2']}",
             todo="buy", d=bd)


def stats(S):
    cl, cur, cap = S["closed"], S["curve"], S["start"]["capital"]
    out = {"n": len(cl), "ver": VERSION}
    if cl:
        w = [c for c in cl if c["pnl"] > 0]
        lo = sum(c["pnl"] for c in cl if c["pnl"] <= 0)
        out.update(win=round(len(w) / len(cl) * 100), avg_r=round(sum(c["r"] for c in cl) / len(cl), 2), pf=round(sum(c["pnl"] for c in w) / abs(lo), 2) if lo < 0 else None,
                   hold=round(sum(c["hold"] for c in cl) / len(cl), 1))
    if cur:
        eq = cur[-1]["e"]
        out["ret"] = round((eq / cap - 1) * 100, 2)
        if cur[0].get("spy") and cur[-1].get("spy"):
            out["spy"] = round((cur[-1]["spy"] / cur[0]["spy"] - 1) * 100, 2)
        pk, mdd = cap, 0.0
        for c in cur:
            pk = max(pk, c["e"])
            mdd = min(mdd, c["e"] / pk - 1)
        out["mdd"] = round(mdd * 100, 2)
    return out


def step(S, rows, bars, cfg, now):
    cfg = _sane(cfg)
    if not cfg["enabled"]:
        return S
    if cfg["reset_halt"] and S.get("halt"):
        S["halt"] = None
        _log(S, now, "limit", "", "Wznowiono po ręcznym resecie kill switch (reset_halt) – pamiętaj, by ustawić je z powrotem na false")
    comp = {s: _completed(df, now) for s, df in bars.items()}
    S["todo"] = [t for t in S["todo"] if now - t["ts"] < 7 * 86400][-60:]
    _process_pending(S, comp, cfg, now)
    _manage(S, comp, cfg, now)
    eq = _equity(S)
    _curve(S, comp, eq)
    lim = _limits(S, cfg, eq, now)
    _new_orders(S, rows, cfg, eq, lim, now)
    S.update(stats=stats(S), updated=int(now), cfg=cfg, limits=lim, equity=round(eq, 2))
    return S
