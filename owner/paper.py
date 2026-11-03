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
from datetime import datetime, timedelta, timezone

VERSION = "1.0"
DEFAULTS = {"enabled": True, "capital": 10000.0, "risk_pct": 1.0, "max_positions": 8, "max_weight_pct": 20.0, "max_sector_pct": 40.0, "cost_pct": 0.1, "slippage_pct": 0.05,
            "daily_loss_limit_pct": 3.0, "weekly_loss_limit_pct": 6.0, "max_drawdown_halt_pct": 15.0, "min_quality": 60, "min_confirm_frac": 0.6, "min_dvol_musd": 20.0,
            "allow_etf": False, "markets": ["US"], "max_hold_sessions": 15, "cooldown_sessions": 5, "reset_halt": False, "start_date": None, "live_fill": True, "live_test": True, "live_max_day": 12}


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


def _fill(S, o, op, d, cfg, now, prov=False):
    """Wypełnienie zlecenia po cenie otwarcia sesji d (z poślizgiem i kosztami). prov=True: sesja trwa, cena otwarcia już znana."""
    slip, cst = cfg["slippage_pct"] / 100, cfg["cost_pct"] / 100
    why = "otwarcie poniżej stopa (luka)" if op <= o["stop"] else "cena uciekła powyżej strefy wejścia" if op > o["zhi"] * 1.005 else None
    px = op * (1 + slip)
    sh = min(o["shares"], int(S["cash"] / (px * (1 + cst)))) if not why else 0
    if not why and sh < 1:
        why = "brak gotówki"
    if why:
        _log(S, now, "cancel", o["sym"], f"Zlecenie anulowane: {why} (otwarcie {op:.2f}, strefa {o['zlo']}–{o['zhi']})", d=d)
        return False
    fee = px * sh * cst
    S["cash"] -= px * sh + fee
    S["positions"].append({"sym": o["sym"], "name": o.get("name", ""), "sector": o.get("sector", ""), "setup": o["setup"], "shares": sh, "shares0": sh, "entry": px, "entry_d": d,
                           "stop": o["stop"], "stop0": o["stop"], "t1": o["t1"], "t2": o["t2"], "fees": fee, "realized": 0.0, "proceeds": 0.0, "sold": 0, "half": False,
                           "hold": 0, "last": o["bd"], "mark": px, "why": o.get("why", []), "prov": prov})
    _log(S, now, "fill", o["sym"], f"Kupiono {sh} szt. po {px:.2f} (otwarcie {d} + poślizg)" + (" – wstępnie, sesja trwa" if prov else ""), d=d)
    return True


def _min_fill_day(o):
    cd = datetime.fromtimestamp(o["ts"], timezone.utc)
    return (cd + timedelta(days=1 if cd.hour * 60 + cd.minute >= 13 * 60 + 30 else 0)).strftime("%Y-%m-%d")


def _live_bar(df, now):
    """Dzisiejsza, jeszcze niezakończona świeca (None, gdy brak lub sesja już zamknięta)."""
    if df is None or not len(df) or _after_close(now):
        return None
    t = _today(now)
    last = df.iloc[-1]
    if df.index[-1].strftime("%Y-%m-%d") != t or not all(last[k] == last[k] for k in ("Open", "Close")):
        return None
    return last


def _live_fill(S, raw, cfg, now):
    """Zlecenie z wczorajszego sygnału wypełnia się po dzisiejszym otwarciu już w trakcie sesji (cena otwarcia jest znana od otwarcia).
    Zlecenia utworzone po otwarciu dzisiejszej sesji nadal czekają do następnej (brak zaglądania w przyszłość)."""
    keep, t = [], _today(now)
    for o in S["pending"]:
        b = _live_bar(raw.get(o["sym"]), now)
        if b is not None and o["bd"] < t and _min_fill_day(o) <= t:
            _fill(S, o, float(b.Open), t, cfg, now, prov=True)
        else:
            keep.append(o)
    S["pending"] = keep


def _live_marks(S, raw, now):
    for p in S["positions"]:
        b = _live_bar(raw.get(p["sym"]), now)
        if b is not None:
            p["live"] = round(float(b.Close), 4)
        else:
            p.pop("live", None)
    return S["cash"] + sum(p["shares"] * p.get("live", p["mark"]) for p in S["positions"])


def _process_pending(S, comp, cfg, now):
    keep = []
    for o in S["pending"]:
        df = comp.get(o["sym"])
        nb = df[df.index.strftime("%Y-%m-%d") > o["bd"]] if df is not None else None
        if nb is None or not len(nb):
            if now - o["ts"] > 7 * 86400:
                _log(S, now, "cancel", o["sym"], "Zlecenie wygasło (brak danych przez 7 dni)")
            else:
                keep.append(o)
            continue
        min_d = _min_fill_day(o)      # zlecenie złożone po otwarciu sesji nie może wypełnić się po jej otwarciu (look-ahead)
        nb2 = nb[nb.index.strftime("%Y-%m-%d") >= min_d]
        if not len(nb2):
            keep.append(o)
            continue
        nb = nb2
        op, d = float(nb.iloc[0].Open), nb.index[0].strftime("%Y-%m-%d")
        _fill(S, o, op, d, cfg, now)
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
            p["prov"] = False
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



def _gate(r, cfg):
    p = r["plan"]; cf = r.get("cf"); why = []
    if r.get("mkt", "US") not in cfg["markets"]:
        why.append("rynek")
    if r.get("etf") and not cfg["allow_etf"]:
        why.append("ETF")
    if (r.get("dvol") or 0) < cfg["min_dvol_musd"]:
        why.append("obrót")
    if p["quality"] < cfg["min_quality"]:
        why.append("jakość")
    if cf and cf[1] and cf[0] / cf[1] < cfg["min_confirm_frac"]:
        why.append("potwierdzenia")
    if r.get("earnings_days") is not None and r["earnings_days"] <= 5:
        why.append("wyniki")
    if p["state"] != "teraz":
        why.append("stan")
    return why


def _sim_trade(L, entry_px, entry_d, last_d, df, cfg, now):
    """Wynik hipotetycznej pozycji (100 szt.) według tych samych reguł zarządzania co w symulatorze: {'st','ret','r'}."""
    pos = {"sym": L["sym"], "name": "", "sector": "", "setup": L["setup"], "shares": 100, "shares0": 100, "entry": entry_px, "entry_d": entry_d, "stop": L["stop"], "stop0": L["stop"],
           "t1": L["t1"], "t2": L["t2"], "fees": entry_px * 100 * cfg["cost_pct"] / 100, "realized": 0.0, "proceeds": 0.0, "sold": 0, "half": False, "hold": 0, "last": last_d, "mark": entry_px, "why": []}
    T = {"cash": 0.0, "positions": [pos], "closed": [], "journal": [], "todo": []}
    _manage(T, {L["sym"]: df}, cfg, now)
    if T["closed"]:
        c = T["closed"][0]
        return {"st": "zamknięta", "ret": c["pnl_pct"], "r": c["r"], "x": c["exit_d"]}
    tot = pos["realized"] + pos["shares"] * (pos["mark"] - pos["entry"]) - pos["fees"]
    return {"st": "otwarta", "ret": round(tot / (pos["entry"] * 100) * 100, 2), "r": round(tot / (100 * max(pos["entry"] - pos["stop0"], 1e-9)), 2)}


def _eval_live(S, comp, cfg, now):
    slip = cfg["slippage_pct"] / 100
    for L in S["live"]:
        df = comp.get(L["sym"])
        if df is None or not len(df):
            continue
        dates = df.index.strftime("%Y-%m-%d")
        dday = df[dates == L["d"]]
        nb = df[dates > L["d"]]
        if not len(dday) and not len(nb):
            continue
        # A: wejście od razu po cenie z chwili sygnału; B: czekanie na otwarcie następnej sesji
        a = _sim_trade(L, L["px"] * (1 + slip), L["d"], L["d"], df, cfg, now) if len(nb) else {"st": "sesja trwa", "ret": 0.0, "r": 0.0}
        if len(dday) and float(dday.iloc[0].Low) <= L["stop"]:   # ostrożnie: dołek dnia sygnału mógł nastąpić po wejściu
            ret = (L["stop"] * (1 - slip) / (L["px"] * (1 + slip)) - 1) * 100 - 2 * cfg["cost_pct"]
            a = {"st": "stop w dniu sygnału", "ret": round(ret, 2), "r": round(ret / 100 * L["px"] / max(L["px"] - L["stop"], 1e-9), 2), "x": L["d"]}
        L["a"] = a
        if len(nb):
            op = float(nb.iloc[0].Open)
            if op <= L["stop"] or op > L["zhi"] * 1.005:
                L["b"] = {"st": "odrzucone (luka/ucieczka ceny)", "ret": None, "r": None}
            else:
                L["b"] = _sim_trade(L, op * (1 + slip), nb.index[0].strftime("%Y-%m-%d"), L["d"], df, cfg, now)
                L["b"]["px"] = round(op, 2)
        else:
            L["b"] = {"st": "czeka na otwarcie", "ret": None, "r": None}


def _live_signals(S, rows, cfg, now):
    """Rejestr rekomendacji „kupuj teraz” z trwającej sesji – do testu: wejść od razu czy czekać na następne otwarcie."""
    t = _today(now)
    if _after_close(now):
        return
    dow = datetime.fromtimestamp(now, timezone.utc).weekday()
    mins = datetime.fromtimestamp(now, timezone.utc).hour * 60 + datetime.fromtimestamp(now, timezone.utc).minute
    if dow > 4 or mins < 13 * 60 + 45:
        return
    seen = {(L["sym"]) for L in S["live"] if L["d"] >= (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")}
    held = {p["sym"] for p in S["positions"]} | {o["sym"] for o in S["pending"]}
    n_today = sum(1 for L in S["live"] if L["d"] == t)
    for r in sorted([r for r in rows if r.get("lv", 0) >= 3 and r.get("plan") and r.get("bar")], key=lambda r: (-r["vscore"], r["symbol"])):
        if n_today >= cfg["live_max_day"]:
            break
        p, sym = r["plan"], r["symbol"]
        if r["bar"][0] != t or sym in seen or sym in held or _gate(r, cfg):
            continue
        px = float(r["price"])
        if not (p["stop"] < px <= p["zhi"] * 1.005):
            continue
        S["live"].append({"id": f"{sym}-{t}", "sym": sym, "name": r.get("name", ""), "d": t, "ts": int(now), "px": px, "setup": p["setup"], "zlo": p["zlo"], "zhi": p["zhi"], "stop": p["stop"], "t1": p["t1"], "t2": p["t2"],
                          "up1": p["up1"], "q": p["quality"]})
        n_today += 1
        _log(S, now, "live", sym, f"Rekomendacja „kupuj teraz” {sym} ({p['setup']}) po {px:.2f} – test: wejście od razu vs następne otwarcie", d=t)
    S["live"] = S["live"][-150:]


def live_stats(S):
    ev = [L for L in S["live"] if L.get("a") and L.get("b") and L["b"].get("ret") is not None and L["a"]["st"] != "sesja trwa"]
    out = {"n": len(S["live"]), "cmp": len(ev)}
    if ev:
        ra, rb = [L["a"]["ret"] for L in ev], [L["b"]["ret"] for L in ev]
        out.update(avg_a=round(sum(ra) / len(ra), 2), avg_b=round(sum(rb) / len(rb), 2), a_better=sum(x > y for x, y in zip(ra, rb)),
                   done=sum(1 for L in ev if L["a"]["st"] != "otwarta" and L["b"]["st"] != "otwarta"))
    return out


def step(S, rows, bars, cfg, now):
    cfg = _sane(cfg)
    if not cfg["enabled"]:
        return S
    sd = cfg.get("start_date")
    if sd and _today(now) < sd:   # przed datą startu symulator tylko czeka (bez transakcji)
        S.update(waiting=sd, updated=int(now), cfg=cfg, equity=round(_equity(S), 2), stats=stats(S), limits={"dd": 0, "day": 0, "week": 0, "peak": cfg["capital"], "blocked": ["czeka na start"]})
        return S
    if sd and S.get("sd") != sd:   # jednorazowy start/reset na wskazany dzień: świeży kapitał wirtualny
        S.update(sd=sd, waiting=None, cash=float(cfg["capital"]), start={"capital": cfg["capital"], "ts": int(now)}, positions=[], pending=[], closed=[], curve=[], todo=[], halt=None, rej=[])
        _log(S, now, "limit", "", f"Start symulacji ({sd}): {cfg['capital']:.0f} USD wirtualnego kapitału")
    if cfg["reset_halt"] and S.get("halt"):
        S["halt"] = None
        _log(S, now, "limit", "", "Wznowiono po ręcznym resecie kill switch (reset_halt) – pamiętaj, by ustawić je z powrotem na false")
    comp = {s: _completed(df, now) for s, df in bars.items()}
    S["todo"] = [t for t in S["todo"] if now - t["ts"] < 7 * 86400][-60:]
    S.setdefault("live", [])
    _process_pending(S, comp, cfg, now)
    _manage(S, comp, cfg, now)
    if cfg["live_fill"]:
        _live_fill(S, bars, cfg, now)
    eq = _equity(S)
    _curve(S, comp, eq)
    lim = _limits(S, cfg, eq, now)
    _new_orders(S, rows, cfg, eq, lim, now)
    if cfg["live_test"]:
        _live_signals(S, rows, cfg, now)
        _eval_live(S, comp, cfg, now)
    S.update(stats=stats(S), updated=int(now), cfg=cfg, limits=lim, equity=round(eq, 2), equity_live=round(_live_marks(S, bars, now), 2), live_stats=live_stats(S))
    return S
