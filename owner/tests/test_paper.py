import calendar, copy, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import paper

T = lambda s: calendar.timegm(pd.Timestamp(s).timetuple())
CFG = paper._sane(dict(paper.DEFAULTS))


def bars(rows):
    return pd.DataFrame(rows, columns=["d", "Open", "High", "Low", "Close"]).assign(d=lambda x: pd.to_datetime(x.d)).set_index("d")


def spy(last="2026-01-08"):
    d = pd.date_range("2026-01-02", last, freq="B")
    return pd.DataFrame({"Open": 500.0, "High": 502.0, "Low": 498.0, "Close": 500.0}, index=d)


def row(**kw):
    r = {"symbol": "XYZ", "name": "Xyz Inc", "lv": 3, "vscore": 1.2, "conf": "wysoka", "cf": [5, 6, []], "dvol": 100.0, "mkt": "US", "etf": False, "sector": "IT", "earnings_days": None,
         "reasons": ["trend"], "bar": ["2026-01-05", 100, 101, 99, 100, 1000],
         "plan": {"setup": "Trend", "quality": 70, "entry": 100.0, "zlo": 99.5, "zhi": 100.2, "stop": 96.0, "t1": 106.0, "t2": 112.0, "state": "teraz", "up1": 6.0, "up2": 12.0, "dn": -4.0}}
    r.update(kw); return r


def run_first(**kw):
    S = paper.new_state(CFG, T("2026-01-06 08:00"))
    paper.step(S, [row(**kw)], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 08:00"))
    return S


def test_order_created_sized_and_limited():
    S = run_first()
    o = S["pending"][0]
    assert len(S["pending"]) == 1 and o["shares"] == 20                       # limit wagi 20% (2000/100) < limit ryzyka (23 szt.) < gotówka
    assert o["shares"] * (o["entry"] - o["stop"]) <= 10000 * 0.01 * 1.0001    # ryzyko do stopa <= 1% kapitału
    assert any(j["t"] == "order" for j in S["journal"]) and S["todo"][0]["x"] == "XYZ.US"


def test_full_winner_t1_half_then_t2():
    S = run_first(); sp = spy("2026-01-08")
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.1, 107, 99, 106), ("2026-01-07", 106, 113, 104, 110)])
    paper.step(S, [], {"SPY": sp, "XYZ": X}, CFG, T("2026-01-08 08:00"))
    assert not S["positions"] and not S["pending"] and len(S["closed"]) == 1
    c = S["closed"][0]; assert c["pnl"] > 0 and c["r"] > 0 and c["setup"] == "Trend"
    assert S["cash"] > 10000 and abs(S["equity"] - S["cash"]) < 0.01
    assert [j["t"] for j in S["journal"] if j["t"] in ("fill", "exit")] == ["fill", "exit", "exit"]


def test_stop_and_target_same_bar_is_a_stop():
    S = run_first()
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.1, 107, 95, 104)])
    paper.step(S, [], {"SPY": spy("2026-01-07"), "XYZ": X}, CFG, T("2026-01-07 08:00"))
    c = S["closed"][0]; assert c["pnl"] < 0 and -1.3 < c["r"] < -0.9


def test_gap_below_stop_cancels_and_partial_bar_ignored():
    S = run_first()
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 94, 95, 90, 91)])
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X}, CFG, T("2026-01-06 15:00"))      # dzisiejsza sesja niezakończona -> bez zmian
    assert len(S["pending"]) == 1 and not S["positions"]
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X}, CFG, T("2026-01-07 08:00"))
    assert not S["pending"] and not S["positions"] and S["cash"] == 10000 and any(j["t"] == "cancel" for j in S["journal"])


def test_no_orders_from_unfinished_session():
    S = paper.new_state(CFG, T("2026-01-05 15:00"))
    paper.step(S, [row()], {"SPY": spy("2026-01-02")}, CFG, T("2026-01-05 15:00"))          # sygnał z dzisiejszej, niezakończonej sesji
    assert not S["pending"]
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-05 21:30"))          # po zamknięciu – wolno
    assert len(S["pending"]) == 1


def test_idempotent_and_rejections_logged_once():
    r = row(earnings_days=3)
    S = paper.new_state(CFG, T("2026-01-06 08:00"))
    paper.step(S, [r], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 08:00"))
    a = json.dumps(S, sort_keys=True)
    paper.step(S, [r], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 08:00"))
    assert json.dumps(S, sort_keys=True) == a and not S["pending"]
    rej = [j for j in S["journal"] if j["t"] == "reject"]; assert len(rej) == 1 and "wyniki" in rej[0]["m"]
    S2 = run_first(); b = json.dumps(S2, sort_keys=True)
    paper.step(S2, [row()], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 08:00")); assert json.dumps(S2, sort_keys=True) == b


def test_risk_limits_and_kill_switch():
    S = paper.new_state(CFG, T("2026-01-06 08:00")); S["cash"] = 8000.0
    S["curve"] = [{"d": "2026-01-02", "e": 10000.0, "spy": 500.0, "cash": 10000, "n": 0}]
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 08:00"))
    assert S["halt"] and not S["pending"] and any("KILL SWITCH" in j["m"] for j in S["journal"])
    assert any("limity ryzyka" in j["m"] for j in S["journal"] if j["t"] == "reject")
    cfg2 = dict(CFG, reset_halt=True, max_drawdown_halt_pct=50.0, daily_loss_limit_pct=99.0, weekly_loss_limit_pct=99.0)
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, cfg2, T("2026-01-06 09:00"))
    assert S["halt"] is None and len(S["pending"]) == 1


def test_max_positions_sector_and_time_exit():
    cfg = dict(CFG, max_positions=1)
    S = paper.new_state(cfg, T("2026-01-06 08:00"))
    paper.step(S, [row(), row(symbol="ABC", sector="Energy")], {"SPY": spy("2026-01-05")}, cfg, T("2026-01-06 08:00"))
    assert len(S["pending"]) == 1 and any("maksymalną liczbę" in j["m"] for j in S["journal"])
    cfg = dict(CFG, max_hold_sessions=2)
    S = paper.new_state(cfg, T("2026-01-06 08:00"))
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, cfg, T("2026-01-06 08:00"))
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.1, 103, 99, 101), ("2026-01-07", 101, 104, 99, 102)])
    paper.step(S, [], {"SPY": spy("2026-01-07"), "XYZ": X}, cfg, T("2026-01-08 08:00"))
    assert len(S["closed"]) == 1 and any("wyjście czasowe" in j["m"] for j in S["journal"])


def test_stats_and_curve():
    S = run_first()
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.1, 107, 99, 106), ("2026-01-07", 106, 113, 104, 110)])
    paper.step(S, [], {"SPY": spy("2026-01-08"), "XYZ": X}, CFG, T("2026-01-08 08:00"))
    st = S["stats"]; assert st["n"] == 1 and st["win"] == 100 and st["ret"] > 0 and st["mdd"] <= 0 and len(S["curve"]) >= 1
    json.dumps(S, allow_nan=False)


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("ok", k)
