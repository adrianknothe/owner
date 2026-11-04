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
         "reasons": ["trend"], "price": 100.0, "bar": ["2026-01-05", 100, 101, 99, 100, 1000],
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
    assert not S["pending"] and not S["positions"] and any(j["t"] == "cancel" for j in S["journal"])   # luka znana od otwarcia: anulowanie już w trakcie sesji
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X}, CFG, T("2026-01-07 08:00"))
    assert not S["pending"] and not S["positions"] and S["cash"] == 10000 and any(j["t"] == "cancel" for j in S["journal"])


def test_no_orders_from_unfinished_session():
    S = paper.new_state(CFG, T("2026-01-05 15:00"))
    paper.step(S, [row()], {"SPY": spy("2026-01-02")}, CFG, T("2026-01-05 15:00"))          # sygnał z dzisiejszej, niezakończonej sesji
    assert not S["pending"] and len(S["positions"]) == 1 and S["positions"][0]["src"] == "sygnał z sesji"   # sygnał z trwającej sesji: wejście od razu, nie zlecenie na jutro
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-05 21:30"))          # po zamknięciu: ta sama spółka nie dostaje drugiego zlecenia
    assert not S["pending"] and len(S["positions"]) == 1
    cfg2 = dict(CFG, live_trade=False)
    S2 = paper.new_state(cfg2, T("2026-01-05 15:00"))
    paper.step(S2, [row()], {"SPY": spy("2026-01-02")}, cfg2, T("2026-01-05 15:00"))
    assert not S2["pending"] and not S2["positions"]                                          # bez wejść z sesji: sygnał z niezakończonej sesji czeka
    paper.step(S2, [row()], {"SPY": spy("2026-01-05")}, cfg2, T("2026-01-05 21:30"))
    assert len(S2["pending"]) == 1


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





def test_start_date_waits_then_resets_once():
    cfg = dict(CFG, start_date="2026-01-06")
    S = paper.new_state(cfg, T("2026-01-04 10:00")); S["cash"] = 1234.0
    paper.step(S, [row()], {"SPY": spy("2026-01-02")}, cfg, T("2026-01-05 08:00"))
    assert S["waiting"] == "2026-01-06" and not S["pending"] and not S["positions"]
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, cfg, T("2026-01-06 08:00"))
    assert S["waiting"] is None and S["start"]["capital"] == 10000 and len(S["pending"]) == 1 and any("Start symulacji" in j["m"] for j in S["journal"])
    cash_after = S["cash"]; n_j = len(S["journal"])
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, cfg, T("2026-01-06 09:00"))
    assert S["cash"] == cash_after and len(S["pending"]) == 1 and len(S["journal"]) == n_j


def test_late_order_cannot_fill_at_todays_open():
    S = paper.new_state(CFG, T("2026-01-06 15:00"))
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 15:00"))      # sygnał po otwarciu sesji 06.01
    assert len(S["pending"]) == 1
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.0, 101, 99, 100), ("2026-01-07", 100.5, 104, 99, 103)])
    paper.step(S, [], {"SPY": spy("2026-01-07"), "XYZ": X}, CFG, T("2026-01-08 08:00"))
    f = [j for j in S["journal"] if j["t"] == "fill"]
    assert S["positions"] and abs(S["positions"][0]["entry"] - 100.5 * 1.0005) < 0.01, S["positions"]


def test_live_fill_intraday_then_confirmed_without_duplicate():
    S = paper.new_state(CFG, T("2026-01-06 08:00"))
    paper.step(S, [row()], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 08:00"))
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.1, 102, 99.8, 101)])
    paper.step(S, [], {"SPY": spy("2026-01-05"), "XYZ": X}, CFG, T("2026-01-06 15:00"))      # sesja trwa
    assert not S["pending"] and len(S["positions"]) == 1 and S["positions"][0]["prov"]
    p = S["positions"][0]; assert abs(p["entry"] - 100.1 * 1.0005) < 0.01 and p["live"] == 101 and S["equity_live"] > S["equity"] - 1
    X2 = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.1, 102, 99.8, 101.5)])
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X2}, CFG, T("2026-01-07 08:00"))    # sesja zakończona: ta sama pozycja, bez dubla
    assert len(S["positions"]) == 1 and not S["positions"][0]["prov"] and S["positions"][0]["hold"] == 1 and "live" not in S["positions"][0]
    assert sum(1 for j in S["journal"] if j["t"] == "fill") == 1


def test_live_signal_ab_comparison():
    S = paper.new_state(CFG, T("2026-01-06 08:00"))
    r = row(bar=["2026-01-06", 100, 101, 99, 100, 1000], price=100.0)
    paper.step(S, [r], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 15:00"))
    assert len(S["live"]) == 1 and S["live"][0]["px"] == 100.0 and not S["pending"]                # sygnał z trwającej sesji: tylko do testu A/B
    paper.step(S, [r], {"SPY": spy("2026-01-06")}, CFG, T("2026-01-06 16:00"))
    assert len(S["live"]) == 1                                                                      # bez duplikatu tej samej spółki
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100, 101, 99.5, 100.5), ("2026-01-07", 100.5, 107, 100, 106), ("2026-01-08", 106, 113, 105, 112)])
    paper.step(S, [], {"SPY": spy("2026-01-08"), "XYZ": X}, CFG, T("2026-01-09 08:00"))
    L = S["live"][0]
    assert L["a"]["st"] == "zamknięta" and L["b"]["st"] == "zamknięta" and L["a"]["ret"] > L["b"]["ret"] > 0   # wejście od razu (100.0) vs następne otwarcie (100.5)
    st = S["live_stats"]; assert st["cmp"] == 1 and st["a_better"] == 1 and st["avg_a"] > st["avg_b"]


def test_limit_order_fills_on_pullback_or_cancels():
    S = run_first()                                                            # zlecenie z sygnału 05.01, limit = 100.2*1.005 = 100.70
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 101.0, 103, 100.5, 102.5)])
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X}, CFG, T("2026-01-07 08:00"))      # otwarcie powyżej limitu, ale cena wróciła do limitu
    p = S["positions"][0]; assert abs(p["entry"] - 100.701) < 0.01 and p["hold"] == 1 and "stop" in p
    S = run_first()
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 102.0, 104, 101.0, 103)])    # cena nie wróciła: bez gonienia
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X}, CFG, T("2026-01-07 08:00"))
    assert not S["positions"] and not S["pending"] and any("nie wróciła" in j["m"] for j in S["journal"])


def test_live_entry_is_stopped_conservatively_on_signal_day():
    S = paper.new_state(CFG, T("2026-01-06 08:00"))
    r = row(bar=["2026-01-06", 100, 101, 99, 100, 1000], price=100.0)
    paper.step(S, [r], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 15:00"))
    assert len(S["positions"]) == 1 and abs(S["positions"][0]["entry"] - 100.05) < 0.01
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100, 107, 95, 104)])        # dołek poniżej stopa i cel w tej samej sesji: liczymy stop
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X}, CFG, T("2026-01-07 08:00"))
    assert not S["positions"] and S["closed"][0]["pnl"] < 0 and S["closed"][0]["exit"] < 97


def test_xtb_tickets_have_exact_fields():
    S = run_first()
    b = [x for x in S["todo"] if x["k"] == "buy"][0]
    assert b["x"] == "XYZ.US" and b["qty"] == 20 and b["lim"] == 100.7 and b["sl"] == 96.0 and b["t1"] == 106.0 and b["t2"] == 112.0 and b["usd"] == 2000.0 and b["pre"]
    X = bars([("2026-01-05", 100, 101, 99, 100), ("2026-01-06", 100.1, 107, 99.5, 106)])
    paper.step(S, [], {"SPY": spy("2026-01-06"), "XYZ": X}, CFG, T("2026-01-07 08:00"))
    mv = [x for x in S["todo"] if x["k"] == "move"][0]; sl = [x for x in S["todo"] if x["k"] == "sell"][0]
    assert mv["qty"] == 10 and abs(mv["sl"] - 100.15) < 0.01 and sl["qty"] == 10 and sl["left"] == 10 and sl["why"] == "cel 1"
    S2 = paper.new_state(CFG, T("2026-01-06 08:00"))
    paper.step(S2, [row(bar=["2026-01-06", 100, 101, 99, 100, 1000], price=100.0)], {"SPY": spy("2026-01-05")}, CFG, T("2026-01-06 15:00"))
    lv = [x for x in S2["todo"] if x["k"] == "buy"][0]; assert lv["live"] and lv["px"] == 100.0 and lv["qty"] >= 1


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); print("ok", k)
