"""The scalping rules of scalping.py on EURUSD and GBPUSD, 1 and 5 minutes, 2005 to May 2020.

Pre-declared variants (VARIANTS), each as the video sizes its trades: 1 % of the account at risk per trade,
so results are in R (multiples of the risk) and costs count relative to the stop distance. Costs per side
as a fraction of price: 0, 0.4 bp (the user's IC Markets Raw Spread account: 3.25 EUR commission per lot
and side plus about half a raw spread) and 0.75 bp (a retail spread account). In-sample 2005-2014,
out-of-sample 2015 to May 2020; one variant is chosen on the mean in-sample Sharpe ratio of both markets
at 0.4 bp.

usage: python3 scalping_test.py      (after fetch_fx_m1.py)
"""
import json
import os

import numpy as np
import pandas as pd

import backtest as bt
import scalping as sc

MARKETS = ["EURUSD", "GBPUSD"]
COSTS = {"0 bp": 0.0, "0,4 bp": 0.00004, "0,75 bp": 0.000075}
MAIN_COST = "0,4 bp"
RISK = 0.01
SPLIT = pd.Timestamp("2015-01-01")
PERIODS = {"is": (pd.Timestamp("2005-01-01"), SPLIT), "oos": (SPLIT, pd.Timestamp("2020-06-01"))}


def prepare_market(symbol):
    m = sc.load(symbol)
    m1 = sc.M1(m)
    tf = {}
    for minutes in (1, 5):
        b = sc.Bars(m, m1, minutes)
        a = sc.atr(b)
        tf[minutes] = {"b": b, "rsi": sc.rsi(b.c), "ema": sc.ema(b.c), "sw": sc.zigzag(b.h, b.l, sc.SWING_ATR * a)}
    return m1, tf


VARIANTS = {  # name: function(m1, tf) -> trades
    "Tokio-Ausbruch, Spanne 19-04 NY (5m)": lambda m1, tf: sc.tokyo_breakout(m1, tf[5]["b"], "19-04"),
    "Tokio-Ausbruch, Spanne 20-03 NY (5m)": lambda m1, tf: sc.tokyo_breakout(m1, tf[5]["b"], "20-03"),
    "Box-Ausbruch (1m)": lambda m1, tf: sc.one_at_a_time(sc.box_breakout(m1, tf[1]["b"], tf[1]["sw"])),
    "Box-Ausbruch (5m)": lambda m1, tf: sc.one_at_a_time(sc.box_breakout(m1, tf[5]["b"], tf[5]["sw"])),
    "RSI-Divergenz mit 70/30-Regel (1m)": lambda m1, tf: sc.one_at_a_time(
        sc.rsi_divergence(m1, tf[1]["b"], tf[1]["sw"], tf[1]["rsi"], sauce=True)),
    "RSI-Divergenz ohne 70/30-Regel (1m)": lambda m1, tf: sc.one_at_a_time(
        sc.rsi_divergence(m1, tf[1]["b"], tf[1]["sw"], tf[1]["rsi"], sauce=False)),
    "RSI-Divergenz mit 70/30-Regel (5m)": lambda m1, tf: sc.one_at_a_time(
        sc.rsi_divergence(m1, tf[5]["b"], tf[5]["sw"], tf[5]["rsi"], sauce=True)),
    "RSI-Divergenz ohne 70/30-Regel (5m)": lambda m1, tf: sc.one_at_a_time(
        sc.rsi_divergence(m1, tf[5]["b"], tf[5]["sw"], tf[5]["rsi"], sauce=False)),
    "Fibonacci-Rücksetzer mit EMA 200 (1m)": lambda m1, tf: sc.fib_pullback(m1, tf[1]["b"], tf[1]["sw"], tf[1]["ema"]),
    "Fibonacci-Rücksetzer ohne Filter (1m)": lambda m1, tf: sc.fib_pullback(m1, tf[1]["b"], tf[1]["sw"]),
    "Fibonacci-Rücksetzer mit EMA 200 (5m)": lambda m1, tf: sc.fib_pullback(m1, tf[5]["b"], tf[5]["sw"], tf[5]["ema"]),
    "Fibonacci-Rücksetzer ohne Filter (5m)": lambda m1, tf: sc.fib_pullback(m1, tf[5]["b"], tf[5]["sw"]),
    "Tagesplan des Videos (Tokio + Fibonacci + RSI)": lambda m1, tf: sc.day_plan(
        m1, tf[5]["b"], tf[1]["b"], tf[1]["sw"], tf[1]["rsi"]),
}


def daily(df, days, start, end):
    """Account returns per trading day at RISK per trade (trades counted on their entry day)."""
    x = df[(df["day"] >= start) & (df["day"] < end)]
    cal = np.union1d(days[(days >= start) & (days < end)], x["day"].to_numpy())
    return (x.groupby("day")["r_net"].sum() * RISK).reindex(cal, fill_value=0.0), x


def metrics(ret, x, start, end):
    years = (end - start).days / 365.25
    sd = ret.std()
    sharpe = float(ret.mean() / sd * np.sqrt(len(ret) / years)) if sd > 0 else 0.0
    eq = (1 + ret).cumprod()
    gains, losses = x["r_net"][x["r_net"] > 0].sum(), -x["r_net"][x["r_net"] <= 0].sum()
    return {"sharpe": sharpe, "t": sharpe * np.sqrt(years), "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
            "max_dd": float((eq / eq.cummax() - 1).min()), "trades_per_year": len(x) / years,
            "win_rate": float((x["r_gross"] > 0).mean()) if len(x) else None,
            "r_gross": float(x["r_gross"].mean()) if len(x) else None,
            "r_net": float(x["r_net"].mean()) if len(x) else None,
            "profit_factor": float(gains / losses) if losses > 0 else None,
            "risk_pips": float((x["risk_bp"] * x["entry"]).median()) if len(x) else None}   # pip = 0.0001


def main():
    raw = {}
    for symbol in MARKETS:
        m1, tf = prepare_market(symbol)
        counts = pd.Series(m1.day).value_counts()
        days = np.sort(counts.index[counts >= 60].to_numpy())     # without weekend stubs of a few quotes
        for name, fn in VARIANTS.items():
            trades = fn(m1, tf)
            raw[(symbol, name)] = (trades, m1, days)
            print(f"  {symbol} {name}: {len(trades)} trades", flush=True)
        print(f"{symbol}: {len(days)} trading days prepared", flush=True)

    rows = []
    for name in VARIANTS:
        row = {"name": name, "markets": {}, "portfolio": {}}
        for cost_name, cost in COSTS.items():
            port = {p: [] for p in PERIODS}
            for symbol in MARKETS:
                trades, m1, days = raw[(symbol, name)]
                df = sc.to_frame(trades, m1, cost)
                for p, (a, e) in PERIODS.items():
                    ret, x = daily(df, days, a, e)
                    row["markets"].setdefault(symbol, {}).setdefault(cost_name, {})[p] = metrics(ret, x, a, e)
                    port[p].append(ret)
            for p, (a, e) in PERIODS.items():
                pr = pd.concat(port[p], axis=1, sort=True).fillna(0.0).mean(axis=1)
                row["portfolio"].setdefault(cost_name, {})[p] = metrics(pr, pd.DataFrame(
                    {"r_net": [], "r_gross": [], "risk_bp": [], "entry": []}), a, e)
        row["is_mean_sharpe"] = float(np.mean([row["markets"][s][MAIN_COST]["is"]["sharpe"] for s in MARKETS]))
        row["oos_mean_sharpe"] = float(np.mean([row["markets"][s][MAIN_COST]["oos"]["sharpe"] for s in MARKETS]))
        rows.append(row)
        mk = row["markets"]
        print(f"{name:50s} IS {row['is_mean_sharpe']:6.2f}  OOS {row['oos_mean_sharpe']:6.2f}  "
              + "  ".join(f"{s}: {mk[s][MAIN_COST]['oos']['trades_per_year']:5.0f}/J win {mk[s][MAIN_COST]['oos']['win_rate'] or 0:4.0%} "
                          f"R {mk[s]['0 bp']['oos']['r_gross'] or 0:+.3f}/{mk[s][MAIN_COST]['oos']['r_net'] or 0:+.3f} "
                          f"stop {mk[s][MAIN_COST]['oos']['risk_pips'] or 0:5.1f} pips" for s in MARKETS), flush=True)

    ranked = sorted(rows, key=lambda r: r["is_mean_sharpe"], reverse=True)
    best = ranked[0]
    rank_corr = float(pd.Series([r["is_mean_sharpe"] for r in rows]).rank()
                      .corr(pd.Series([r["oos_mean_sharpe"] for r in rows]).rank()))
    print(f"\nchosen in-sample: {best['name']}  IS {best['is_mean_sharpe']:.2f}  OOS {best['oos_mean_sharpe']:.2f}")
    for cost_name in COSTS:
        pos = [r["name"] for r in rows if r["portfolio"][cost_name]["oos"]["sharpe"] > 0]
        print(f"costs {cost_name}: {len(pos)} of {len(rows)} variants with positive OOS portfolio Sharpe {pos}")
    print(f"rank correlation IS/OOS: {rank_corr:.2f}")
    os.makedirs(bt.RESULTS, exist_ok=True)
    with open(os.path.join(bt.RESULTS, "scalping.json"), "w") as f:
        json.dump({"variants": ranked, "chosen": best["name"], "rank_corr": rank_corr}, f, indent=1, default=str)


if __name__ == "__main__":
    main()
