"""The scalping rules of scalping.py on 1 and 5 minutes: FX (EURUSD, GBPUSD), gold, US index CFDs and Bitcoin.

Pre-declared variants (VARIANTS), each as the video sizes its trades: 1 % of the account at risk per trade,
so results are in R (multiples of the risk) and costs count relative to the stop distance. Each market group
(GROUPS) has three costs per side as a fraction of price:
- FX and gold: 0, 0.4 bp (the user's IC Markets Raw Spread account: 3.25 EUR commission per lot and side
  plus about half a raw spread) and 0.75 bp (a retail spread account);
- index CFDs: 0, 0.3 bp (half the IC Markets US500 spread of the probe run; no commission) and 1 bp (the
  cost of results 7);
- Bitcoin: 0, 1 bp (a tight CFD spread) and 5 bp (Binance futures taker fee).
In-sample until 2014, out-of-sample 2015 to May 2020 (Bitcoin: 2014-2015 and 2016 to January 2018). In
each group one variant is chosen on the mean in-sample Sharpe ratio of its markets at the middle cost.

usage: python3 scalping_test.py [group ...] [--cached]      (after fetch_m1.py; default: all groups)
"""
import json
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

import backtest as bt
import scalping as sc

FX_COSTS = {"0 bp": 0.0, "0,4 bp": 0.00004, "0,75 bp": 0.000075}
GROUPS = {   # markets, costs per side, the cost the variant is chosen at, in-sample start / split / end
    "fx": {"markets": ["EURUSD", "GBPUSD"], "costs": FX_COSTS, "main": "0,4 bp",
           "dates": ("2005-01-01", "2015-01-01", "2020-06-01")},
    "gold": {"markets": ["XAUUSD"], "costs": FX_COSTS, "main": "0,4 bp",
             "dates": ("2005-01-01", "2015-01-01", "2020-06-01")},
    "indices": {"markets": ["SPX500USD", "NAS100USD", "US2000USD"],
                "costs": {"0 bp": 0.0, "0,3 bp": 0.00003, "1 bp": 0.0001}, "main": "0,3 bp",
                "dates": ("2005-01-01", "2015-01-01", "2020-06-01")},
    "crypto": {"markets": ["BTCUSD"], "costs": {"0 bp": 0.0, "1 bp": 0.0001, "5 bp": 0.0005}, "main": "1 bp",
               "dates": ("2014-01-01", "2016-01-01", "2018-01-09")},
}
RISK = 0.01


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


def cache_path(symbol):
    return os.path.join(bt.CACHE, f"scalping_{symbol}.pkl")


def market_frames(symbol):
    """Trades of every variant on one market (before costs), and its trading days (60 bars or more).
    Saved to the cache, which `--cached` reads instead of computing again."""
    m1, tf = prepare_market(symbol)
    counts = pd.Series(m1.day).value_counts()
    days = np.sort(counts.index[counts >= 60].to_numpy())     # without weekend stubs of a few quotes
    frames = {}
    for name, fn in VARIANTS.items():
        frames[name] = sc.to_frame(fn(m1, tf), m1)
        print(f"  {symbol} {name}: {len(frames[name])} trades", flush=True)
    print(f"{symbol}: {len(days)} trading days", flush=True)
    os.makedirs(bt.CACHE, exist_ok=True)
    pd.to_pickle((frames, days), cache_path(symbol))
    return symbol, frames, days


def daily(df, days, start, end):
    """Account returns per trading day at RISK per trade (trades counted on their entry day)."""
    x = df[(df["day"] >= start) & (df["day"] < end)]
    cal = np.union1d(days[(days >= start) & (days < end)], x["day"].to_numpy())
    return (x.groupby("day")["r_net"].sum() * RISK).reindex(cal, fill_value=0.0), x


def metrics(ret, x, start, end):
    years = (end - start).days / 365.25
    sd = ret.std()
    sharpe = float(ret.mean() / sd * np.sqrt(len(ret) / years)) if sd > 0 else 0.0
    eq = (1 + ret.clip(lower=-1.0)).cumprod()                   # a day losing more than the account ends it
    gains, losses = x["r_net"][x["r_net"] > 0].sum(), -x["r_net"][x["r_net"] <= 0].sum()
    stop = x["risk_bp"] * x["entry"] / 1e4
    return {"sharpe": sharpe, "t": sharpe * np.sqrt(years), "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
            "max_dd": float((eq / eq.cummax() - 1).min()), "trades_per_year": len(x) / years,
            "win_rate": float((x["r_gross"] > 0).mean()) if len(x) else None,
            "r_gross": float(x["r_gross"].mean()) if len(x) else None,
            "r_net": float(x["r_net"].mean()) if len(x) else None,
            "profit_factor": float(gains / losses) if losses > 0 else None,
            "stop": float(stop.median()) if len(x) else None,                    # in price units
            "stop_bp": float(x["risk_bp"].median()) if len(x) else None}


def evaluate(group, g, data):
    a, split, e = (pd.Timestamp(d) for d in g["dates"])
    periods = {"is": (a, split), "oos": (split, e)}
    markets, main = g["markets"], g["main"]
    rows = []
    for name in VARIANTS:
        row = {"name": name, "markets": {}, "portfolio": {}}
        for cost_name in g["costs"]:
            port = {p: [] for p in periods}
            for symbol in markets:
                frames, days = data[symbol]
                df = sc.with_cost(frames[name], g["costs"][cost_name])
                for p, (pa, pe) in periods.items():
                    ret, x = daily(df, days, pa, pe)
                    row["markets"].setdefault(symbol, {}).setdefault(cost_name, {})[p] = metrics(ret, x, pa, pe)
                    port[p].append(ret)
            for p, (pa, pe) in periods.items():
                pr = pd.concat(port[p], axis=1, sort=True).fillna(0.0).mean(axis=1)
                row["portfolio"].setdefault(cost_name, {})[p] = metrics(pr, pd.DataFrame(
                    {"r_net": [], "r_gross": [], "risk_bp": [], "entry": []}), pa, pe)
        row["is_mean_sharpe"] = float(np.mean([row["markets"][s][main]["is"]["sharpe"] for s in markets]))
        row["oos_mean_sharpe"] = float(np.mean([row["markets"][s][main]["oos"]["sharpe"] for s in markets]))
        rows.append(row)
        mk = row["markets"]
        print(f"{name:50s} IS {row['is_mean_sharpe']:6.2f}  OOS {row['oos_mean_sharpe']:6.2f}  "
              + "  ".join(f"{s}: {mk[s][main]['oos']['trades_per_year']:5.0f}/J win {mk[s][main]['oos']['win_rate'] or 0:4.0%} "
                          f"R {mk[s]['0 bp']['oos']['r_gross'] or 0:+.3f}/{mk[s][main]['oos']['r_net'] or 0:+.3f} "
                          f"stop {mk[s][main]['oos']['stop_bp'] or 0:5.1f} bp" for s in markets), flush=True)

    ranked = sorted(rows, key=lambda r: r["is_mean_sharpe"], reverse=True)
    best = ranked[0]
    rank_corr = float(pd.Series([r["is_mean_sharpe"] for r in rows]).rank()
                      .corr(pd.Series([r["oos_mean_sharpe"] for r in rows]).rank()))
    print(f"\n{group}: chosen in-sample: {best['name']}  IS {best['is_mean_sharpe']:.2f}  OOS {best['oos_mean_sharpe']:.2f}")
    for cost_name in g["costs"]:
        pos = [r["name"] for r in rows if r["portfolio"][cost_name]["oos"]["sharpe"] > 0]
        print(f"costs {cost_name}: {len(pos)} of {len(rows)} variants with positive OOS portfolio Sharpe {pos}")
    print(f"rank correlation IS/OOS: {rank_corr:.2f}\n", flush=True)
    os.makedirs(bt.RESULTS, exist_ok=True)
    with open(os.path.join(bt.RESULTS, f"scalping_{group}.json"), "w") as f:
        json.dump({"group": group, "markets": markets, "costs": g["costs"], "main_cost": main,
                   "dates": g["dates"], "variants": ranked, "chosen": best["name"], "rank_corr": rank_corr},
                  f, indent=1, default=str)


def main():
    cached = "--cached" in sys.argv
    groups = [a for a in sys.argv[1:] if a != "--cached"] or list(GROUPS)
    symbols = [s for g in groups for s in GROUPS[g]["markets"]]
    data = {}
    if cached:
        data = {s: pd.read_pickle(cache_path(s)) for s in symbols if os.path.exists(cache_path(s))}
    todo = [s for s in symbols if s not in data]
    if todo:
        with Pool(min(4, len(todo))) as pool:
            for symbol, frames, days in pool.imap_unordered(market_frames, todo):
                data[symbol] = (frames, days)
    for g in groups:
        evaluate(g, GROUPS[g], data)


if __name__ == "__main__":
    main()
