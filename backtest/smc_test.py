"""Smart Money Concepts [LuxAlgo]: the trading rules of smc.py under the same protocol as before.

Two universes, each with its own pre-declared variants (5 rules x 2 timeframes
x Long+Short / nur Long = 20) and its own in-sample choice:
- FX, gold and SPY (fetch_data.py): H4 (SPY H1) and D1 bars, real spread,
  in-sample / out-of-sample windows of backtest.py (compare.windows()).
- Crypto (fetch_crypto.py): six Binance pairs, H4 and D1, 0.1% per side,
  windows of crypto.py.
The indicator runs with its default inputs (swing length 50, internal length
5, ATR order block filter, High/Low mitigation). Execution as everywhere: the
signal is known at the bar close, the fill is at the next bar's open.

usage: python3 smc_test.py
"""
import json
import os

import numpy as np
import pandas as pd

import backtest as bt
import compare as cmp
import crypto
import smc
import tradingview as tv

def universe_fx():
    win, _ = cmp.windows()
    bars = {(m, tf): tv.market_bars(m, tf) for m in cmp.MARKETS for tf in ("H4/H1", "D1")}
    return list(cmp.MARKETS), ("H4/H1", "D1"), bars, win, None


def universe_crypto():
    bars = {(s, tf): crypto.load(s, tf) for s in crypto.SYMBOLS for tf in ("H4", "D1")}
    return crypto.SYMBOLS, ("H4", "D1"), bars, crypto.windows(), {s: crypto.COST_PER_SIDE for s in crypto.SYMBOLS}


def run(label, markets, tfs, bars, win, costs):
    rows = []
    for tf in tfs:
        states = {m: smc.state(bars[(m, tf)]) for m in markets}
        for key, name in smc.RULES:
            for side in ("Long+Short", "nur Long"):
                pos = {m: smc.positions(bars[(m, tf)], key, side == "nur Long", states[m]) for m in markets}
                r = cmp.evaluate(pos, {m: bars[(m, tf)] for m in markets}, win, costs)
                r.update({"rule": name, "tf": tf, "side": side, "name": f"{name} ({tf}, {side})",
                          "oos_exposure": float(np.mean([r["oos"][m]["exposure"] for m in markets])),
                          "oos_trades_per_year": float(np.mean([r["oos"][m]["trades_per_year"] for m in markets]))})
                rows.append(r)
                print(f"{label:6s} {r['name']:52s} IS {r['is_mean_sharpe']:5.2f}  OOS {r['oos_mean_sharpe']:5.2f}  "
                      f"portfolio OOS {r['oos_portfolio']['sharpe']:5.2f} (t {r['oos_portfolio']['t']:4.1f})  "
                      f"exp {r['oos_exposure']:4.0%} tr/y {r['oos_trades_per_year']:5.1f}  "
                      + " ".join(f"{m[:3]} {r['oos'][m]['sharpe']:5.2f}" for m in markets), flush=True)
    d1 = tfs[-1]
    bh = cmp.evaluate({m: np.ones(len(bars[(m, d1)])) for m in markets}, {m: bars[(m, d1)] for m in markets}, win, costs)
    bh.update({"rule": "Buy & Hold", "tf": d1, "side": "nur Long", "name": "Buy & Hold"})
    ranked = sorted(rows, key=lambda x: x["is_mean_sharpe"], reverse=True)
    best = ranked[0]
    rank_corr = float(pd.Series([x["is_mean_sharpe"] for x in rows]).rank()
                      .corr(pd.Series([x["oos_mean_sharpe"] for x in rows]).rank()))
    beat = sum(r["oos_portfolio"]["sharpe"] > bh["oos_portfolio"]["sharpe"] for r in rows)
    print(f"\n{label}: chosen in-sample {best['name']}  IS {best['is_mean_sharpe']:.2f}  OOS {best['oos_mean_sharpe']:.2f}  "
          f"portfolio OOS {best['oos_portfolio']['sharpe']:.2f} (t {best['oos_portfolio']['t']:.1f}), "
          f"buy & hold portfolio OOS {bh['oos_portfolio']['sharpe']:.2f}; {beat}/{len(rows)} variants beat it; "
          f"rank correlation IS/OOS {rank_corr:.2f}\n", flush=True)
    return {"variants": ranked, "buy_hold": bh, "chosen": best["name"], "rank_corr": rank_corr,
            "beat_buy_hold": beat}


def main():
    out = {"fx_gold_spy": run("FX", *universe_fx()), "crypto": run("crypto", *universe_crypto())}
    with open(os.path.join(bt.RESULTS, "smc.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)


if __name__ == "__main__":
    main()
