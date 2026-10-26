"""Crypto: the rules from backtest.py, compare.py and tradingview.py on Binance spot data.

Six pairs listed on Binance before 2019 (BTC, ETH, BNB, XRP, ADA, LINK against
USDT), H4 and D1 candles from listing to October 2026 (fetch_crypto.py).
Execution as before: signal at the bar close, fill at the next bar's open.
Costs 0.1% per side, Binance's spot taker fee; the spread of these pairs is far
smaller. No funding or borrowing costs for short positions.

In-sample: from 400 days after listing (warm-up of all indicators, including
the AI-SuperTrend KNN on H4) to 2022-12-31. Out-of-sample: 2023-01-01 to the
end of the data. One variant is chosen on the mean in-sample Sharpe. The rules
chosen earlier on FX, gold and SPY are reported as well: crypto is a fully
out-of-sample test of those choices.

usage: python3 crypto.py      (after fetch_crypto.py)
"""
import json
import os

import numpy as np
import pandas as pd

import backtest as bt
import compare as cmp
import tradingview as tv

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
COST_PER_SIDE = 0.001
WARMUP_DAYS = 400
SPLIT = pd.Timestamp("2023-01-01", tz="UTC").timestamp()
CRYPTO = os.path.join(bt.DATA, "crypto")
EARLIER_PICKS = {  # rules chosen in-sample on FX / gold / SPY
    "AI-SuperTrend KNN State (H4, nur Long, Faktor 3, Schwelle 0.9)": "backtest.py",
    "SMA 200 Trendfilter (D1, nur Long)": "compare.py",
    "Lorentzian Classification (D1, nur Long)": "tradingview.py",
}


def load(symbol, tf):
    return pd.read_csv(os.path.join(CRYPTO, f"{symbol}_{'4h' if tf == 'H4' else '1d'}.csv"))


def windows():
    out = {}
    for s in SYMBOLS:
        first = int(load(s, "D1")["time"].iloc[0])
        out[s] = (first + WARMUP_DAYS * 86400, SPLIT)
    return out


def tsmom_12m(b):
    c = b["bid_c"]
    return cmp.sign_or_flat(c / c.shift(365) - 1.0)   # 12 months of daily bars in a 7-day market


def ai_supertrend(rule, params):
    def fn(b, key):
        ind = bt.run_indicator(b, key, params)
        return bt.STRATEGIES[rule](ind)
    return fn


# (family, name, timeframe, position function taking (bars, cache key))
RULES = [
    ("AI-SuperTrend", "SuperTrend 10/2", "H4", ai_supertrend("SuperTrend", {})),
    ("AI-SuperTrend", "KNN State", "H4", ai_supertrend("KNN State", {})),
    ("AI-SuperTrend", "KNN Trend", "H4", ai_supertrend("KNN Trend", {})),
    ("AI-SuperTrend", "KNN State (Faktor 3, Schwelle 0.9)", "H4", ai_supertrend("KNN State", {"factor": 3.0, "thr": 0.9})),
    ("Klassisch", "SMA 200 Trendfilter", "D1", lambda b, k: cmp.rule_sma200(b)),
    ("Klassisch", "Golden Cross SMA 50/200", "D1", lambda b, k: cmp.rule_golden_cross(b)),
    ("Klassisch", "Donchian 20/10", "D1", lambda b, k: cmp.rule_donchian(20, 10)(b)),
    ("Klassisch", "Donchian 55/20", "D1", lambda b, k: cmp.rule_donchian(55, 20)(b)),
    ("Klassisch", "Momentum 12 Monate", "D1", lambda b, k: tsmom_12m(b)),
    ("Klassisch", "MACD 12/26/9", "D1", lambda b, k: cmp.rule_macd(b)),
    ("Klassisch", "SuperTrend 10/3", "D1", lambda b, k: cmp.rule_supertrend(b, k)),
    ("Klassisch", "RSI(2) mit SMA-200-Filter", "D1", lambda b, k: cmp.rule_rsi2(b)),
    ("Klassisch", "Bollinger 20/2 Rückkehr", "H4", lambda b, k: cmp.rule_bollinger(b)),
]
for _name, _author, _fn, _src in tv.SCRIPTS:
    for _tf in ("H4", "D1"):
        RULES.append(("TradingView", _name, _tf, lambda b, k, f=_fn, n=_name: tv.positions_cached(n, f, k, "", b)))


def main():
    win = windows()
    costs = {s: COST_PER_SIDE for s in SYMBOLS}
    bars = {(s, tf): load(s, tf) for s in SYMBOLS for tf in ("H4", "D1")}
    rows = []
    for family, name, tf, fn in RULES:
        base = {s: fn(bars[(s, tf)], f"crypto_{s}_{tf}") for s in SYMBOLS}
        for side in ("Long+Short", "nur Long"):
            pos = base if side == "Long+Short" else {s: np.maximum(p, 0.0) for s, p in base.items()}
            r = cmp.evaluate(pos, {s: bars[(s, tf)] for s in SYMBOLS}, win, costs)
            r.update({"family": family, "rule": name, "tf": tf, "side": side, "name": f"{name} ({tf}, {side})"})
            rows.append(r)
            print(f"{family:13s} {r['name']:52s} IS {r['is_mean_sharpe']:5.2f}  OOS {r['oos_mean_sharpe']:5.2f}  "
                  f"portfolio OOS {r['oos_portfolio']['sharpe']:5.2f} (t {r['oos_portfolio']['t']:4.1f})", flush=True)

    bh = cmp.evaluate({s: np.ones(len(bars[(s, 'D1')])) for s in SYMBOLS}, {s: bars[(s, "D1")] for s in SYMBOLS}, win, costs)
    bh.update({"family": "Vergleich", "rule": "Buy & Hold", "tf": "D1", "side": "nur Long", "name": "Buy & Hold"})
    ranked = sorted(rows, key=lambda x: x["is_mean_sharpe"], reverse=True)
    best = ranked[0]
    rank_corr = float(pd.Series([x["is_mean_sharpe"] for x in rows]).rank()
                      .corr(pd.Series([x["oos_mean_sharpe"] for x in rows]).rank()))
    lookup = {
        "AI-SuperTrend KNN State (H4, nur Long, Faktor 3, Schwelle 0.9)": "KNN State (Faktor 3, Schwelle 0.9) (H4, nur Long)",
        "SMA 200 Trendfilter (D1, nur Long)": "SMA 200 Trendfilter (D1, nur Long)",
        "Lorentzian Classification (D1, nur Long)": "Lorentzian Classification (D1, nur Long)",
    }
    picks = {label: next(r for r in rows if r["name"] == lookup[label]) for label in EARLIER_PICKS}
    print(f"\nchosen in-sample: {best['name']}  IS {best['is_mean_sharpe']:.2f}  OOS {best['oos_mean_sharpe']:.2f}  "
          f"portfolio OOS {best['oos_portfolio']['sharpe']:.2f} (t {best['oos_portfolio']['t']:.1f})")
    for label, r in picks.items():
        print(f"earlier pick {label}: portfolio OOS {r['oos_portfolio']['sharpe']:.2f} (t {r['oos_portfolio']['t']:.1f})")
    print(f"buy & hold: portfolio IS {bh['is_portfolio']['sharpe']:.2f}, OOS {bh['oos_portfolio']['sharpe']:.2f}")
    print(f"rank correlation IS/OOS over {len(rows)} variants: {rank_corr:.2f}")
    with open(os.path.join(bt.RESULTS, "crypto.json"), "w") as f:
        json.dump({"variants": ranked, "buy_hold": bh, "chosen": best["name"], "rank_corr": rank_corr,
                   "earlier_picks": {k: v["name"] for k, v in picks.items()},
                   "windows": {s: [pd.to_datetime(a, unit="s").date().isoformat(), pd.to_datetime(b, unit="s").date().isoformat()]
                               for s, (a, b) in win.items()}}, f, indent=1, default=float)


if __name__ == "__main__":
    main()
