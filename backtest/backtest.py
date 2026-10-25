"""Backtest of trading rules built on the AI-SuperTrend KNN indicator.

The indicator values come from the MQL5 source itself (AI_SuperTrend_KNN.mq5,
compiled through harness/ with a C++ compiler), computed on bid prices like an
MT5 chart. Execution model:
- the rule decides a target position (-1, 0, +1) at the close of bar t,
- the order fills at the open of bar t+1 (no look-ahead),
- every fill pays half the bid/ask spread of that bar's open (FX, gold) or a
  fixed cost per side (SPY, which has trade prices only),
- positions are 1x the account equity, compounded; no swaps, no dividends.

usage: python3 backtest.py            (writes results/results.json)
"""
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(HERE, "cache")
RESULTS = os.path.join(HERE, "results")
HARNESS = os.path.join(HERE, "harness")
INDICATOR = os.path.join(HERE, "..", "AI_SuperTrend_KNN.mq5")

SPY_COST_PER_SIDE = 0.0002   # 2 bp: spread + commission for an ETF
DEFAULTS = {}                # Pine defaults: ATR 10, factor 2, K 10, threshold 0.9, ...

SERIES = [  # (name, source file, timeframe in hours)
    ("EURUSD H1", "EURUSD_H1", 1),
    ("NZDUSD H1", "NZDUSD_H1", 1),
    ("XAUUSD H1", "XAUUSD_H1", 1),
    ("SPY H1", "SPY_H1", 1),
    ("EURUSD H4", "EURUSD_H1", 4),
    ("NZDUSD H4", "NZDUSD_H1", 4),
    ("XAUUSD H4", "XAUUSD_H1", 4),
    ("SPY D1", "SPY_D1", 24),
]

STRATEGIES = {
    "Buy & Hold": lambda ind: np.ones(len(ind)),
    # plain SuperTrend, always in the market (benchmark without the KNN)
    "SuperTrend": lambda ind: -ind["direction"].to_numpy(),
    # the indicator's confirmed state (Major Long/Short arrows), always in the market
    "KNN State": lambda ind: ind["state"].to_numpy(),
    # only while the confirmed state and the SuperTrend agree (coloured trend fill)
    "KNN Trend": lambda ind: np.where(ind["state"] == -ind["direction"], ind["state"], 0.0),
}


# ---------------------------------------------------------------- indicator
def build_runner():
    exe = os.path.join(HARNESS, "runner")
    src_time = max(os.path.getmtime(p) for p in [INDICATOR, os.path.join(HARNESS, "runner.cpp"),
                                                 os.path.join(HARNESS, "shim.h"), os.path.join(HARNESS, "convert.py")])
    if os.path.exists(exe) and os.path.getmtime(exe) >= src_time:
        return exe
    cpp = subprocess.run([sys.executable, os.path.join(HARNESS, "convert.py"), INDICATOR],
                         check=True, capture_output=True, text=True).stdout
    with open(os.path.join(HARNESS, "indicator.cpp"), "w") as f:
        f.write(cpp)
    subprocess.run(["g++", "-std=c++17", "-O2", "-o", exe, "runner.cpp"], cwd=HARNESS, check=True)
    os.remove(os.path.join(HARNESS, "indicator.cpp"))
    return exe


def load_bars(source, hours):
    bars = pd.read_csv(os.path.join(DATA, source + ".csv"))
    if hours in (1, 24):
        return bars
    bucket = bars["time"] // (hours * 3600)
    agg = {"time": "first", "bid_o": "first", "bid_h": "max", "bid_l": "min", "bid_c": "last",
           "ask_o": "first", "ask_h": "max", "ask_l": "min", "ask_c": "last"}
    return bars.groupby(bucket).agg(agg).reset_index(drop=True)


def run_indicator(bars, key, params):
    os.makedirs(CACHE, exist_ok=True)
    tag = hashlib.md5((key + json.dumps(params, sort_keys=True) + str(os.path.getmtime(INDICATOR))).encode()).hexdigest()[:12]
    out = os.path.join(CACHE, f"{key}_{tag}.csv")
    if not os.path.exists(out):
        src = os.path.join(CACHE, f"{key}_bars.csv")
        bars[["time", "bid_o", "bid_h", "bid_l", "bid_c"]].to_csv(src, index=False)
        args = [f"{k}={v}" for k, v in params.items()]
        subprocess.run([build_runner(), src, out, *args], check=True)
    ind = pd.read_csv(out)
    assert (ind["time"].to_numpy() == bars["time"].to_numpy()).all()
    return ind


# ---------------------------------------------------------------- simulation
def simulate(bars, target, start, cost_per_side):
    """Per-bar returns of a target position series decided at bar closes."""
    mid_o = ((bars["bid_o"] + bars["ask_o"]) / 2).to_numpy()
    mid_c = ((bars["bid_c"] + bars["ask_c"]) / 2).to_numpy()
    half = cost_per_side if cost_per_side is not None else \
        ((bars["ask_o"] - bars["bid_o"]) / 2).to_numpy() / mid_o
    half = np.broadcast_to(half, mid_o.shape)

    target = np.asarray(target, dtype=float).copy()
    target[:start] = 0.0
    held = np.r_[0.0, target[:-1]]          # position during bar k (filled at its open)
    before = np.r_[0.0, held[:-1]]          # position from close k-1 to open k
    gap = np.r_[0.0, mid_o[1:] / mid_c[:-1] - 1.0]
    intra = mid_c / mid_o - 1.0
    cost = np.abs(held - before) * half
    ret = (1.0 + before * gap) * (1.0 + held * intra) - 1.0 - cost

    trades = []
    k = start + 1
    n = len(held)
    while k < n:
        side = held[k]
        if side == 0.0:
            k += 1
            continue
        j = k
        while j + 1 < n and held[j + 1] == side:
            j += 1
        entry = mid_o[k] * (1 + side * half[k])
        if j + 1 < n:                       # closed at the next open
            exit_ = mid_o[j + 1] * (1 - side * half[j + 1])
        else:                               # still open at the end: mark at the close
            exit_ = mid_c[j]
        trades.append((k, j, side, side * (exit_ / entry - 1.0)))
        k = j + 1
    return ret, held, trades


def metrics(bars, ret, held, trades, start, end=None):
    end = len(ret) if end is None else end
    trades = [x for x in trades if start <= x[0] < end]
    held = held[:end]
    t = pd.to_datetime(bars["time"].to_numpy()[start:end], unit="s")
    r = ret[start:end]
    equity = np.cumprod(1.0 + r)
    years = (t[-1] - t[0]).days / 365.25
    daily = pd.Series(1.0 + r, index=t).groupby(t.normalize()).prod() - 1.0
    per_year = len(daily) / years
    sharpe = daily.mean() / daily.std() * np.sqrt(per_year) if daily.std() > 0 else 0.0
    peak = np.maximum.accumulate(equity)
    max_dd = (equity / peak - 1.0).min()
    cagr = equity[-1] ** (1.0 / years) - 1.0
    tr = np.array([x[3] for x in trades])
    wins, losses = tr[tr > 0], tr[tr <= 0]
    side = np.array([x[2] for x in trades])
    yearly = pd.Series(1.0 + r, index=t).groupby(t.year).prod() - 1.0
    weekly = pd.Series(equity, index=t).resample("W").last().dropna()
    return {
        "start": str(t[0].date()), "end": str(t[-1].date()), "years": round(years, 2),
        "total_return": equity[-1] - 1.0, "cagr": cagr, "max_dd": max_dd,
        "mar": cagr / abs(max_dd) if max_dd < 0 else None,
        "sharpe": sharpe, "sharpe_t": sharpe * np.sqrt(years),
        "trades": len(tr), "trades_per_year": len(tr) / years,
        "win_rate": len(wins) / len(tr) if len(tr) else None,
        "profit_factor": wins.sum() / -losses.sum() if len(losses) and losses.sum() < 0 else None,
        "avg_trade": tr.mean() if len(tr) else None,
        "avg_bars": float(np.mean([x[1] - x[0] + 1 for x in trades])) if trades else None,
        "exposure": float(np.mean(held[start:] != 0)),
        "long_trades": int((side > 0).sum()), "short_trades": int((side < 0).sum()),
        "long_sum": float(tr[side > 0].sum()) if len(tr) else 0.0,
        "short_sum": float(tr[side < 0].sum()) if len(tr) else 0.0,
        "yearly": {int(y): float(v) for y, v in yearly.items()},
        "equity_weekly": [[str(d.date()), round(float(v), 5)] for d, v in weekly.items()],
    }


def first_knn_bar(ind):
    active = (ind["prob_up"] + ind["prob_down"]).to_numpy() > 0
    return int(np.argmax(active))


def evaluate(name, source, hours, params, with_curves=True):
    bars = load_bars(source, hours)
    ind = run_indicator(bars, f"{source}_{hours}h", params)
    start = first_knn_bar(ind)
    cost = SPY_COST_PER_SIDE if source.startswith("SPY") else None
    out = {}
    for sname, rule in STRATEGIES.items():
        ret, held, trades = simulate(bars, rule(ind), start, cost)
        m = metrics(bars, ret, held, trades, start)
        gross, gheld, gtrades = simulate(bars, rule(ind), start, 0.0)
        m["cagr_gross"] = metrics(bars, gross, gheld, gtrades, start)["cagr"]
        if not with_curves:
            m.pop("equity_weekly")
        out[sname] = m
    return {"series": name, "bars": len(bars), "first_knn_bar": start, "strategies": out}


def long_only(pos):
    return np.maximum(pos, 0.0)


# ---------------------------------------------------------------- development
# One rule for all markets is chosen on the first 60% of a common period
# (in-sample) and then reported on the remaining 40% (out-of-sample).
DEV_MARKETS = [  # (name, source, fast timeframe, slow timeframe) in hours
    ("EURUSD", "EURUSD_H1", 1, 4),
    ("NZDUSD", "NZDUSD_H1", 1, 4),
    ("XAUUSD", "XAUUSD_H1", 1, 4),
    ("SPY", None, 1, 24),
]
IS_FRACTION = 0.6


def dev_source(market, source, hours):
    if market == "SPY":
        return "SPY_D1" if hours == 24 else "SPY_H1"
    return source


def dev_variants():
    for tf in ("fast", "slow"):
        for side in ("both", "long"):
            for factor in (2.0, 3.0):
                yield {"rule": "SuperTrend", "tf": tf, "side": side, "factor": factor, "thr": None}
                for rule in ("KNN State", "KNN Trend"):
                    for thr in (0.8, 0.9, 0.95):
                        yield {"rule": rule, "tf": tf, "side": side, "factor": factor, "thr": thr}


def variant_name(v):
    thr = "" if v["thr"] is None else f", thr {v['thr']}"
    tf = "H1" if v["tf"] == "fast" else "H4/D1"
    return f"{v['rule']} ({tf}, {'long only' if v['side'] == 'long' else 'long+short'}, factor {v['factor']:g}{thr})"


def develop():
    # common period per market: starts when the KNN of the slowest timeframe is warm
    prepared = {}
    for market, source, fast, slow in DEV_MARKETS:
        per_tf = {}
        for tf, hours in (("fast", fast), ("slow", slow)):
            src = dev_source(market, source, hours)
            bars = load_bars(src, hours)
            per_tf[tf] = (src, hours, bars)
        warm = []
        for tf, (src, hours, bars) in per_tf.items():
            ind = run_indicator(bars, f"{src}_{hours}h", {})
            warm.append(int(bars["time"].iloc[first_knn_bar(ind)]))
        t0 = max(warm)
        t_end = min(int(b["time"].iloc[-1]) for _, _, b in per_tf.values())
        t_split = int(t0 + IS_FRACTION * (t_end - t0))
        prepared[market] = (per_tf, t0, t_split)

    rows = []
    for v in dev_variants():
        row = {"variant": v, "name": variant_name(v), "is": {}, "oos": {}}
        for market, (per_tf, t0, t_split) in prepared.items():
            src, hours, bars = per_tf[v["tf"]]
            params = {"factor": v["factor"]} if v["thr"] is None else {"factor": v["factor"], "thr": v["thr"]}
            ind = run_indicator(bars, f"{src}_{hours}h", params)
            pos = STRATEGIES[v["rule"]](ind)
            if v["side"] == "long":
                pos = long_only(pos)
            times = bars["time"].to_numpy()
            start = int(np.searchsorted(times, t0))
            split = int(np.searchsorted(times, t_split))
            cost = SPY_COST_PER_SIDE if src.startswith("SPY") else None
            ret, held, trades = simulate(bars, pos, start, cost)
            for part, (a, b) in (("is", (start, split)), ("oos", (split, len(bars)))):
                m = metrics(bars, ret, held, trades, a, b)
                row[part][market] = {k: m[k] for k in ("start", "end", "cagr", "sharpe", "max_dd", "trades", "exposure")}
                if part == "oos" and v["rule"] != "SuperTrend":
                    row[part][market]["equity_weekly"] = m["equity_weekly"]
        for part in ("is", "oos"):
            row[part + "_mean_sharpe"] = float(np.mean([row[part][mk]["sharpe"] for mk in prepared]))
        rows.append(row)

    rows.sort(key=lambda r: r["is_mean_sharpe"], reverse=True)
    is_s = np.array([r["is_mean_sharpe"] for r in rows])
    oos_s = np.array([r["oos_mean_sharpe"] for r in rows])
    rank_corr = float(pd.Series(is_s).rank().corr(pd.Series(oos_s).rank()))

    # buy & hold over the same windows (fast timeframe data)
    bh = {}
    for market, (per_tf, t0, t_split) in prepared.items():
        src, hours, bars = per_tf["fast"]
        times = bars["time"].to_numpy()
        start, split = int(np.searchsorted(times, t0)), int(np.searchsorted(times, t_split))
        cost = SPY_COST_PER_SIDE if src.startswith("SPY") else None
        ret, held, trades = simulate(bars, np.ones(len(bars)), start, cost)
        bh[market] = {part: {k: metrics(bars, ret, held, trades, a, b)[k] for k in ("cagr", "sharpe", "max_dd")}
                      for part, (a, b) in (("is", (start, split)), ("oos", (split, len(bars))))}
        bh[market]["oos"]["equity_weekly"] = metrics(bars, ret, held, trades, split, len(bars))["equity_weekly"]

    for r in rows[1:]:   # keep curves of the selected rule only
        for mk in r["oos"].values():
            mk.pop("equity_weekly", None)
    periods = {mk: {"start": str(pd.to_datetime(t0, unit="s").date()), "split": str(pd.to_datetime(ts, unit="s").date())}
               for mk, (_, t0, ts) in prepared.items()}
    return {"periods": periods, "variants": rows, "rank_corr_is_oos": rank_corr, "buy_hold": bh}


def fmt(v, pct=True, digits=1):
    if v is None:
        return "-"
    return f"{v * 100:.{digits}f}%" if pct else f"{v:.2f}"


def main():
    os.makedirs(RESULTS, exist_ok=True)
    results = {"main": [], "sensitivity": []}
    for name, source, hours in SERIES:
        res = evaluate(name, source, hours, DEFAULTS)
        results["main"].append(res)
        print(f"\n== {name}: {res['bars']} bars, test {res['strategies']['SuperTrend']['start']} .. "
              f"{res['strategies']['SuperTrend']['end']}")
        print(f"{'strategy':12s} {'CAGR':>7s} {'gross':>7s} {'MaxDD':>7s} {'Sharpe':>6s} {'t':>5s} "
              f"{'trades':>6s} {'win':>6s} {'PF':>5s} {'expo':>5s}")
        for sname, m in res["strategies"].items():
            print(f"{sname:12s} {fmt(m['cagr']):>7s} {fmt(m['cagr_gross']):>7s} {fmt(m['max_dd']):>7s} "
                  f"{m['sharpe']:6.2f} {m['sharpe_t']:5.1f} {m['trades']:6d} {fmt(m['win_rate'], digits=0):>6s} "
                  f"{fmt(m['profit_factor'], pct=False):>5s} {fmt(m['exposure'], digits=0):>5s}")

    # robustness: the rule must not depend on one lucky parameter set
    for name, source, hours in SERIES[:4]:
        for factor in (2.0, 3.0):
            for thr in (0.8, 0.9, 0.95):
                res = evaluate(name, source, hours, {"factor": factor, "thr": thr}, with_curves=False)
                results["sensitivity"].append({"series": name, "factor": factor, "thr": thr,
                                               **{s: {k: res["strategies"][s][k] for k in ("cagr", "sharpe", "max_dd", "trades")}
                                                  for s in ("SuperTrend", "KNN State", "KNN Trend")}})
    print("\n== sensitivity (Sharpe): factor / threshold")
    for row in results["sensitivity"]:
        print(f"{row['series']:10s} f={row['factor']} thr={row['thr']}: "
              + "  ".join(f"{s} {row[s]['sharpe']:5.2f}" for s in ("SuperTrend", "KNN State", "KNN Trend")))

    dev = develop()
    results["development"] = dev
    markets = list(dev["periods"])
    print("\n== development: one rule for all markets, chosen in-sample")
    for mk, p in dev["periods"].items():
        print(f"{mk}: in-sample {p['start']} .. {p['split']}, out-of-sample {p['split']} .. end")
    print(f"{'rank':>4s} {'IS Sharpe':>9s} {'OOS Sharpe':>10s}  variant   (OOS Sharpe per market: {', '.join(markets)})")
    for i, r in enumerate(dev["variants"][:10] + dev["variants"][-3:]):
        rank = i + 1 if i < 10 else len(dev["variants"]) - 12 + i
        print(f"{rank:4d} {r['is_mean_sharpe']:9.2f} {r['oos_mean_sharpe']:10.2f}  {r['name']}   "
              + " ".join(f"{r['oos'][mk]['sharpe']:5.2f}" for mk in markets))
    print(f"rank correlation in-sample vs out-of-sample Sharpe over {len(dev['variants'])} variants: "
          f"{dev['rank_corr_is_oos']:.2f}")
    print("buy & hold OOS Sharpe: " + ", ".join(f"{mk} {dev['buy_hold'][mk]['oos']['sharpe']:.2f}" for mk in markets))

    with open(os.path.join(RESULTS, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=float)
    print(f"\nwritten {os.path.join(RESULTS, 'results.json')}")


if __name__ == "__main__":
    main()
