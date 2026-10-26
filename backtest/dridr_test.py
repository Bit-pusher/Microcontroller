"""DR / IDR: the published rules and the trading rules of dridr.py on S&P 500, Nasdaq 100 and Russell 2000.

Data: Oanda index CFDs, 5-minute bars 2005 to May 2020 (fetch_indices.py),
midpoint prices. Costs: 1 basis point per side, about what an ES / NQ futures
trader pays in spread and commission (0 and 2 basis points as sensitivity).
In-sample 2005-2014, out-of-sample 2015 to May 2020. One rule out of the
pre-declared grid in dridr.RULES (72 variants) is chosen on the mean in-sample
Sharpe ratio over the three markets, then reported out-of-sample.

usage: python3 dridr_test.py      (after fetch_indices.py)
"""
import json
import os

import numpy as np
import pandas as pd

import backtest as bt
import dridr as dr

SPLIT = pd.Timestamp("2015-01-01")
COST = 0.0001
SENSITIVITY = (0.0, 0.0001, 0.0002)
PLACEBO_SEEDS = (1, 2, 3)


def metrics(ret, trades):
    """ret: return per session day (0 without a trade); trades: (date, side, return)."""
    if len(ret) < 2:
        return None
    years = (ret.index[-1] - ret.index[0]).days / 365.25
    sd = ret.std()
    sharpe = float(ret.mean() / sd * np.sqrt(len(ret) / years)) if sd > 0 else 0.0
    eq = (1 + ret).cumprod()
    tr = np.array([r for _, _, r in trades])
    return {"sharpe": sharpe, "t": sharpe * np.sqrt(years), "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
            "max_dd": float((eq / eq.cummax() - 1).min()), "years": round(years, 1),
            "trades": len(tr), "trades_per_year": len(tr) / years,
            "win_rate": float((tr > 0).mean()) if len(tr) else None,
            "avg_trade_bp": float(tr.mean() * 1e4) if len(tr) else None,
            "profit_factor": float(tr[tr > 0].sum() / -tr[tr <= 0].sum()) if (tr <= 0).any() and tr[tr <= 0].sum() < 0 else None}


def split(ret, trades):
    out = {}
    for part, sel in (("is", ret.index < SPLIT), ("oos", ret.index >= SPLIT)):
        tr = [x for x in trades if (x[0] < SPLIT) == (part == "is")]
        out[part] = metrics(ret[sel], tr)
    return out


def portfolio(rets):
    port = pd.concat(rets, axis=1, sort=True).fillna(0.0).mean(axis=1)
    return {part: metrics(port[sel], []) for part, sel in (("is", port.index < SPLIT), ("oos", port.index >= SPLIT))}


def evaluate(days_by_market, rule, cost):
    row = {"rule": rule, "name": dr.rule_name(rule), "markets": {}}
    rets = {}
    for m, days in days_by_market.items():
        ret, trades = dr.daily_returns(days, rule, cost)
        rets[m] = ret
        row["markets"][m] = split(ret, trades)
    for part in ("is", "oos"):
        row[part + "_mean_sharpe"] = float(np.mean([row["markets"][m][part]["sharpe"] for m in days_by_market]))
    row["portfolio"] = portfolio(rets)
    return row


def benchmarks(bars_by_market, days, cost):
    """Buy & hold (daily closes of the regular session) and always long through each session's trading hours."""
    out = {}
    rets = {}
    for m, b in bars_by_market.items():
        rth = b[(b["minute"] >= 9 * 60 + 30) & (b["minute"] < 16 * 60)]
        close = rth.groupby("date")["close"].last()
        close.index = pd.to_datetime(close.index)
        rets[m] = close.pct_change().dropna()
    out["Buy & Hold"] = portfolio(rets)
    for s in dr.SESSIONS:
        rets = {}
        for m in bars_by_market:
            r = {d["date"]: d["c"][-1] / d["o"][0] - 1.0 - 2 * cost for d in days[(m, s)]}
            rets[m] = pd.Series(r).sort_index()
        out[f"{s}: immer Long im Handelsfenster"] = portfolio(rets)
    return out


def rule_stats(days_by_key):
    """Hit rates of the published rules, the same on placebo days, and what the plain breakout trade
    (DR close, stop at the opposite DR side, out at the session end, no costs) made when the rule held."""
    out = {}
    for (m, s), days in days_by_key.items():
        st = dr.stats(days)
        placebo = pd.concat([dr.stats(days, np.random.default_rng(seed)) for seed in PLACEBO_SEEDS])
        base = {"session": s, "entry": "confirm", "stop": "dr", "target": None, "long_only": False}
        _, trades = dr.daily_returns(days, base, 0.0)
        st["trade"] = st["date"].map(pd.Series({t[0]: t[2] for t in trades}))
        for part, is_part in (("is", lambda x: x["date"] < SPLIT), ("oos", lambda x: x["date"] >= SPLIT)):
            x, px = st[is_part(st)], placebo[is_part(placebo)]
            row = {"days": len(x), "median_dr_range_pct": float(x["range"].median() * 100)}
            for level in ("dr", "idr"):
                conf = x[x[level + "_side"] != 0]
                held = conf[level + "_held"].astype(bool)
                row[level + "_confirmed"] = len(conf) / len(x)
                row[level + "_held"] = float(held.mean())
                row[level + "_held_long"] = float(held[conf[level + "_side"] > 0].mean())
                row[level + "_held_short"] = float(held[conf[level + "_side"] < 0].mean())
                pconf = px[px[level + "_side"] != 0]
                row[level + "_held_placebo"] = float(pconf[level + "_held"].astype(bool).mean())
                if level == "dr":
                    row["trade_bp"] = float(conf["trade"].mean() * 1e4)
                    row["trade_bp_when_held"] = float(conf["trade"][held].mean() * 1e4)
                    row["trade_bp_when_broken"] = float(conf["trade"][~held].mean() * 1e4)
            out[f"{m} {s} {part}"] = row
    return out


def main():
    bars = {m: dr.load(m) for m in dr.SYMBOLS}
    days = {(m, s): dr.sessions(bars[m], s) for m in dr.SYMBOLS for s in dr.SESSIONS}

    st = rule_stats(days)
    print("published rule: after the first close beyond the DR (IDR), the opposite DR side holds until the session end")
    for k, r in st.items():
        print(f"  {k:18s} days {r['days']:5d}  DR range {r['median_dr_range_pct']:4.2f}%  "
              f"DR close {r['dr_confirmed']:4.0%} held {r['dr_held']:4.0%} (long {r['dr_held_long']:4.0%}, "
              f"short {r['dr_held_short']:4.0%}, placebo {r['dr_held_placebo']:4.0%})  "
              f"IDR close held {r['idr_held']:4.0%} (placebo {r['idr_held_placebo']:4.0%})  "
              f"trade {r['trade_bp']:5.1f}bp: held {r['trade_bp_when_held']:5.1f}bp, broken {r['trade_bp_when_broken']:6.1f}bp")

    rows = []
    for rule in dr.RULES:
        r = evaluate({m: days[(m, rule["session"])] for m in dr.SYMBOLS}, rule, COST)
        rows.append(r)
        p = r["portfolio"]["oos"]
        tr = np.mean([r["markets"][m]["oos"]["trades_per_year"] for m in dr.SYMBOLS])
        wr = np.mean([r["markets"][m]["oos"]["win_rate"] or 0 for m in dr.SYMBOLS])
        print(f"{r['name']:96s} IS {r['is_mean_sharpe']:5.2f}  OOS {r['oos_mean_sharpe']:5.2f}  "
              f"portfolio OOS {p['sharpe']:5.2f} (t {p['t']:4.1f})  trades/y {tr:5.1f}  win {wr:4.0%}", flush=True)

    ranked = sorted(rows, key=lambda x: x["is_mean_sharpe"], reverse=True)
    best = ranked[0]
    rank_corr = float(pd.Series([x["is_mean_sharpe"] for x in rows]).rank()
                      .corr(pd.Series([x["oos_mean_sharpe"] for x in rows]).rank()))
    bench = benchmarks(bars, days, COST)
    sens = {}
    for r in ranked[:5]:
        sens[r["name"]] = {}
        for cost in SENSITIVITY:
            e = evaluate({m: days[(m, r["rule"]["session"])] for m in dr.SYMBOLS}, r["rule"], cost)
            sens[r["name"]][f"{cost * 1e4:.0f}bp"] = {"is": e["portfolio"]["is"]["sharpe"], "oos": e["portfolio"]["oos"]["sharpe"]}
    gross = [evaluate({m: days[(m, r["rule"]["session"])] for m in dr.SYMBOLS}, r["rule"], 0.0)["portfolio"]["oos"]["sharpe"]
             for r in rows]

    print(f"\nchosen in-sample: {best['name']}  IS {best['is_mean_sharpe']:.2f}  OOS {best['oos_mean_sharpe']:.2f}  "
          f"portfolio OOS {best['portfolio']['oos']['sharpe']:.2f} (t {best['portfolio']['oos']['t']:.1f})")
    for k, v in bench.items():
        print(f"benchmark {k}: portfolio IS {v['is']['sharpe']:.2f}, OOS {v['oos']['sharpe']:.2f}")
    for k, v in sens.items():
        print(f"costs {k}: " + "  ".join(f"{c} IS {x['is']:.2f} OOS {x['oos']:.2f}" for c, x in v.items()))
    print(f"rank correlation IS/OOS over {len(rows)} variants: {rank_corr:.2f}")
    print(f"variants with positive OOS portfolio Sharpe: {sum(r['portfolio']['oos']['sharpe'] > 0 for r in rows)} "
          f"with costs, {sum(g > 0 for g in gross)} without costs (of {len(rows)})")
    os.makedirs(bt.RESULTS, exist_ok=True)
    with open(os.path.join(bt.RESULTS, "dridr.json"), "w") as f:
        json.dump({"rule_stats": st, "variants": ranked, "chosen": best["name"], "rank_corr": rank_corr,
                   "benchmarks": bench, "cost_sensitivity": sens, "oos_portfolio_sharpe_gross": dict(zip([r["name"] for r in rows], gross))},
                  f, indent=1, default=str)


if __name__ == "__main__":
    main()
