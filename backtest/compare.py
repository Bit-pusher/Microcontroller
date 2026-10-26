"""Compare well-known indicator rules with the AI-SuperTrend KNN under the same protocol.

Same markets, costs and execution model as backtest.py, and the same
in-sample / out-of-sample windows that backtest.py used to pick its rule.
Every rule uses its textbook parameters; nothing is tuned. One rule is chosen
on the mean in-sample Sharpe across the four markets and then reported on the
out-of-sample window.

usage: python3 compare.py      (needs results/results.json from backtest.py)
"""
import json
import os

import numpy as np
import pandas as pd

import backtest as bt

MARKETS = {  # market: (source file, cost per side or None for the real spread)
    "EURUSD": ("EURUSD_H1", None),
    "NZDUSD": ("NZDUSD_H1", None),
    "XAUUSD": ("XAUUSD_H1", None),
    "SPY": ("SPY_H1", bt.SPY_COST_PER_SIDE),
}
FX_DAY_END = 17            # FX/CFD trading days end at 17:00 New York time (DST aware)


# ---------------------------------------------------------------- bars
def daily_bars(market):
    if market == "SPY":
        return bt.load_bars("SPY_D1", 24)
    bars = bt.load_bars(MARKETS[market][0], 1)
    ny = pd.to_datetime(bars["time"], unit="s", utc=True).dt.tz_convert("America/New_York")
    day = (ny + pd.Timedelta(hours=24 - FX_DAY_END)).dt.normalize()
    day = day - pd.to_timedelta((day.dt.dayofweek == 5).astype(int), unit="D")   # Saturday stubs belong to Friday
    agg = {"time": "first", "bid_o": "first", "bid_h": "max", "bid_l": "min", "bid_c": "last",
           "ask_o": "first", "ask_h": "max", "ask_l": "min", "ask_c": "last"}
    return bars.groupby(day).agg(agg).reset_index(drop=True)


def intraday_bars(market, hours):
    return bt.load_bars(MARKETS[market][0], hours)


# ---------------------------------------------------------------- indicators (on bid prices, like MT5)
def sma(s, n):
    return s.rolling(n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def hold_state(long_entry, long_exit, short_entry, short_exit):
    """Position from entry/exit conditions known at each bar close."""
    le, lx, se, sx = (np.asarray(a, dtype=bool) for a in (long_entry, long_exit, short_entry, short_exit))
    pos = np.zeros(len(le))
    p = 0.0
    for i in range(len(le)):
        if p > 0 and lx[i]:
            p = 0.0
        elif p < 0 and sx[i]:
            p = 0.0
        if p <= 0 and le[i]:
            p = 1.0
        elif p >= 0 and se[i]:
            p = -1.0
        pos[i] = p
    return pos


def sign_or_flat(x):
    return np.nan_to_num(np.sign(np.asarray(x, dtype=float)))


def rule_sma200(b):
    c = b["bid_c"]
    return sign_or_flat(c - sma(c, 200))


def rule_golden_cross(b):
    c = b["bid_c"]
    return sign_or_flat(sma(c, 50) - sma(c, 200))


def rule_donchian(entry, exit_):
    def rule(b):
        h, l, c = b["bid_h"], b["bid_l"], b["bid_c"]
        hi_e, lo_e = h.rolling(entry).max().shift(1), l.rolling(entry).min().shift(1)
        hi_x, lo_x = h.rolling(exit_).max().shift(1), l.rolling(exit_).min().shift(1)
        return hold_state(c > hi_e, c < lo_x, c < lo_e, c > hi_x)
    return rule


def rule_tsmom(b):
    c = b["bid_c"]
    return sign_or_flat(c / c.shift(252) - 1.0)


def rule_macd(b):
    c = b["bid_c"]
    macd = ema(c, 12) - ema(c, 26)
    out = sign_or_flat(macd - ema(macd, 9))
    out[:35] = 0.0
    return out


def rule_rsi2(b):
    c = b["bid_c"]
    r, trend, fast = rsi(c, 2), sma(c, 200), sma(c, 5)
    return hold_state((r < 10) & (c > trend), c > fast, (r > 90) & (c < trend), c < fast)


def rule_bollinger(b):
    c = b["bid_c"]
    mid, sd = sma(c, 20), c.rolling(20).std(ddof=0)
    return hold_state(c < mid - 2 * sd, c >= mid, c > mid + 2 * sd, c <= mid)


def rule_supertrend(b, key):
    ind = bt.run_indicator(b, key, {"factor": 3.0})
    return -ind["direction"].to_numpy()


# (name, timeframe label, bars loader, rule, reference)
RULES = [
    ("SMA 200 Trendfilter", "D1", daily_bars, rule_sma200, "Faber 2007, 10-Monats-Durchschnitt"),
    ("Golden Cross SMA 50/200", "D1", daily_bars, rule_golden_cross, "klassischer Kreuzungsfilter"),
    ("Donchian 20/10", "D1", daily_bars, rule_donchian(20, 10), "Turtle-System 1"),
    ("Donchian 55/20", "D1", daily_bars, rule_donchian(55, 20), "Turtle-System 2"),
    ("Momentum 12 Monate", "D1", daily_bars, rule_tsmom, "Moskowitz/Ooi/Pedersen 2012"),
    ("MACD 12/26/9", "D1", daily_bars, rule_macd, "Appel"),
    ("SuperTrend 10/3", "D1", daily_bars, None, "SuperTrend ohne KNN"),
    ("RSI(2) mit SMA-200-Filter", "D1", daily_bars, rule_rsi2, "Connors"),
    ("Bollinger 20/2 Rückkehr", "H1", lambda m: intraday_bars(m, 1), rule_bollinger, "Rückkehr zur Mitte"),
    ("Bollinger 20/2 Rückkehr", "H4", lambda m: intraday_bars(m, 4), rule_bollinger, "Rückkehr zur Mitte"),
]


# ---------------------------------------------------------------- evaluation
def windows():
    dev = json.load(open(os.path.join(bt.RESULTS, "results.json")))["development"]
    out = {}
    for m, p in dev["periods"].items():
        out[m] = (pd.Timestamp(p["start"]).timestamp(), pd.Timestamp(p["split"]).timestamp())
    return out, dev


def daily_returns(bars, ret, a, b):
    t = pd.to_datetime(bars["time"].to_numpy()[a:b], unit="s")
    return pd.Series(1.0 + ret[a:b], index=t).groupby(t.normalize()).prod() - 1.0


def evaluate(pos_by_market, bars_by_market, win, costs=None):
    """costs: cost per side by market, None for the real spread (default: MARKETS)."""
    costs = costs or {m: c for m, (_, c) in MARKETS.items()}
    row = {"is": {}, "oos": {}, "daily": {"is": {}, "oos": {}}}
    for m, pos in pos_by_market.items():
        bars = bars_by_market[m]
        times = bars["time"].to_numpy()
        t0, ts = win[m]
        start, split = int(np.searchsorted(times, t0)), int(np.searchsorted(times, ts))
        ret, held, trades = bt.simulate(bars, pos, start, costs[m])
        for part, (a, b) in (("is", (start, split)), ("oos", (split, len(bars)))):
            mt = bt.metrics(bars, ret, held, trades, a, b)
            row[part][m] = {k: mt[k] for k in ("cagr", "sharpe", "max_dd", "trades_per_year", "exposure")}
            if part == "oos":
                row[part][m]["equity_weekly"] = mt["equity_weekly"]
            row["daily"][part][m] = daily_returns(bars, ret, a, b)
    for part in ("is", "oos"):
        row[part + "_mean_sharpe"] = float(np.mean([row[part][m]["sharpe"] for m in pos_by_market]))
        # equal-weight portfolio of the markets, rebalanced daily
        port = pd.concat(row["daily"][part], axis=1, sort=True).fillna(0.0).mean(axis=1)
        years = (port.index[-1] - port.index[0]).days / 365.25
        per_year = len(port) / years
        sharpe = port.mean() / port.std() * np.sqrt(per_year) if port.std() > 0 else 0.0
        eq = (1 + port).cumprod()
        row[part + "_portfolio"] = {"sharpe": float(sharpe), "t": float(sharpe * np.sqrt(years)),
                                    "cagr": float(eq.iloc[-1] ** (1 / years) - 1),
                                    "max_dd": float((eq / eq.cummax() - 1).min()), "years": round(years, 1)}
    del row["daily"]
    return row


def main():
    win, dev = windows()
    rows = []
    for name, tf, loader, rule, ref in RULES:
        bars_by_market = {m: loader(m) for m in MARKETS}
        base = {}
        for m, b in bars_by_market.items():
            base[m] = rule(b) if rule else rule_supertrend(b, f"{m}_D1_classic")
        for side in ("Long+Short", "nur Long"):
            pos = base if side == "Long+Short" else {m: np.maximum(p, 0.0) for m, p in base.items()}
            r = evaluate(pos, bars_by_market, win)
            r.update({"name": f"{name} ({tf}, {side})", "rule": name, "tf": tf, "side": side, "ref": ref})
            rows.append(r)
            print(f"{r['name']:45s} IS {r['is_mean_sharpe']:5.2f}  OOS {r['oos_mean_sharpe']:5.2f}  "
                  f"portfolio OOS {r['oos_portfolio']['sharpe']:5.2f}  "
                  + " ".join(f"{m} {r['oos'][m]['sharpe']:5.2f}" for m in MARKETS))

    # AI-SuperTrend KNN rule chosen in backtest.py, same windows
    sel = dev["variants"][0]["variant"]
    bars_by_market = {}
    pos = {}
    for m, (source, _) in MARKETS.items():
        hours = 24 if m == "SPY" else 4
        src = "SPY_D1" if m == "SPY" else source
        b = bt.load_bars(src, hours)
        ind = bt.run_indicator(b, f"{src}_{hours}h", {"factor": sel["factor"], "thr": sel["thr"]})
        bars_by_market[m] = b
        pos[m] = np.maximum(bt.STRATEGIES[sel["rule"]](ind), 0.0)
    r = evaluate(pos, bars_by_market, win)
    r.update({"name": "AI-SuperTrend KNN (gewählte Regel)", "rule": "AI-SuperTrend KNN", "tf": "H4/D1",
              "side": "nur Long", "ref": "backtest.py"})
    rows.append(r)

    bh_pos = {m: np.ones(len(daily_bars(m))) for m in MARKETS}
    bh = evaluate(bh_pos, {m: daily_bars(m) for m in MARKETS}, win)
    bh.update({"name": "Buy & Hold", "rule": "Buy & Hold", "tf": "D1", "side": "nur Long", "ref": "Vergleich"})

    ranked = sorted(rows, key=lambda x: x["is_mean_sharpe"], reverse=True)
    best = ranked[0]
    rank_corr = float(pd.Series([x["is_mean_sharpe"] for x in rows]).rank()
                      .corr(pd.Series([x["oos_mean_sharpe"] for x in rows]).rank()))
    print(f"\nchosen in-sample: {best['name']}  IS {best['is_mean_sharpe']:.2f}  OOS {best['oos_mean_sharpe']:.2f}  "
          f"portfolio OOS Sharpe {best['oos_portfolio']['sharpe']:.2f} (t {best['oos_portfolio']['t']:.1f})")
    print(f"AI-SuperTrend: OOS {r['oos_mean_sharpe']:.2f}, portfolio OOS {r['oos_portfolio']['sharpe']:.2f}")
    print(f"Buy & Hold: OOS {bh['oos_mean_sharpe']:.2f}, portfolio OOS {bh['oos_portfolio']['sharpe']:.2f}")
    print(f"rank correlation IS/OOS over {len(rows)} rules: {rank_corr:.2f}")
    with open(os.path.join(bt.RESULTS, "compare.json"), "w") as f:
        json.dump({"rules": ranked, "buy_hold": bh, "chosen": best["name"], "rank_corr": rank_corr,
                   "windows": dev["periods"]}, f, indent=1, default=float)


if __name__ == "__main__":
    main()
