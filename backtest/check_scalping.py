"""Checks of scalping.py on hand-made price paths with known results.

usage: python3 check_scalping.py
"""
import numpy as np
import pandas as pd

import scalping as sc


def frame(start_utc, rows):
    """1-minute bars from start_utc; rows of (open, high, low, close) or a single price."""
    rows = [(r, r, r, r) if np.isscalar(r) else r for r in rows]
    t0 = pd.Timestamp(start_utc, tz="UTC")
    times = [(t0 + pd.Timedelta(minutes=k) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
             for k in range(len(rows))]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"]).assign(time=times)
    return sc.prepare(df)


def setup(start_utc, rows, thr=3.0):
    m = frame(start_utc, rows)
    m1 = sc.M1(m)
    b = sc.Bars(m, m1, 1)
    return m, m1, b, sc.zigzag(b.h, b.l, np.full(b.n, thr))


def same(a, b):
    if isinstance(b, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(b, (float, int, np.floating)) and not isinstance(b, bool):
        return bool(np.isclose(a, b))
    return a == b


def check(name, got, want):
    ok = same(got, want)
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (expected {want})"))
    return ok


def trade_tuple(t):
    return None if t is None else (t["side"], t["entry"], t["stop"], t["target"], t["exit"], t["reason"])


def main():
    ok = True
    # zigzag turning at 3 points against the running extreme
    rows = [(10, 10, 9, 10), (12, 12, 11, 12), (15, 15, 14, 15), (13, 13, 12, 13), (11, 11, 10, 11),
            (9, 9, 8, 9), (12, 12, 11, 12), (14, 14, 13, 14), (10, 10, 9, 10)]
    _, _, _, sw = setup("2017-01-10 10:00", rows)
    ok &= check("zigzag kinds / bars / prices / confirmations",
                (list(sw[0]), list(sw[1]), list(sw[2]), list(sw[3])), ([1, -1, 1], [2, 5, 7], [15, 8, 14], [3, 6, 8]))

    # exits: stop wins a tie, a gap through the stop fills at the open, a target at its price (also after a
    # gap), else the day end
    for name, bar1, want in (("tie -> stop", (100.5, 102.5, 98.5, 101), (1, 99.0, "stop")),
                             ("gap through stop", (98, 98.5, 97, 98), (1, 98.0, "stop")),
                             ("target", (100.5, 102.5, 100, 102), (1, 102.0, "target")),
                             ("gap through target", (102.5, 103, 102.2, 102.8), (1, 102.0, "target")),
                             ("day end", (100.5, 101, 99.5, 100.8), (1, 100.8, "day end"))):
        _, m1, _, _ = setup("2017-01-10 10:00", [(100, 101, 99.5, 100.5), bar1])
        ok &= check(f"exit, {name}", tuple(sc.exit_trade(m1, 1, 0, 99, 102, 1)), want)

    # Tokyo breakout, winter: the range 19:00-04:00 New York is 00:00-09:00 UTC; long on the 5-minute bar
    # closing above it, stop half the range below the entry, target twice the risk
    rows = []
    for k in range(9 * 60):
        rows.append((1.05, 1.0520 if k == 120 else 1.0505, 1.0480 if k == 300 else 1.0495, 1.05))
    rows += [(1.051, 1.0512, 1.0508, 1.051)] * 5 + [1.0515] * 4 + [(1.0515, 1.0530, 1.0514, 1.0530)]
    rows += [(1.0531, 1.0540, 1.0530, 1.0535)] + [(1.0535, 1.0540, 1.0530, 1.0535)] * 9
    rows += [(1.0540, 1.0575, 1.0538, 1.0570)] + [1.0570] * 5
    m, m1, _, _ = setup("2017-01-10 00:00", rows)
    m5 = sc.Bars(m, m1, 5)
    t = sc.tokyo_breakout(m1, m5)
    ok &= check("Tokyo breakout (winter)", trade_tuple(t[0]) if t else None,
                (1, 1.0531, 1.0511, 1.0571, 1.0571, "target"))
    # in summer the same New York hours are 23:00-08:00 UTC: shifting the data one hour earlier gives the same trade
    m, m1, _, _ = setup("2017-07-10 23:00", rows)
    t = sc.tokyo_breakout(m1, sc.Bars(m, m1, 5))
    ok &= check("Tokyo breakout (summer time)", trade_tuple(t[0]) if t else None,
                (1, 1.0531, 1.0511, 1.0571, 1.0571, "target"))

    # consolidation box: highs 110 then 109, lows 104 then 105 -> box 105-109; close above 109 -> long,
    # stop at the middle 107, target 1.5 x risk
    rows = [100, 105, 110, 107, 104, 107, 109, 106, 105, 108, 108.5, (108.5, 110, 108.4, 110),
            (110.2, 110.3, 110.1, 110.2), (110.2, 115.5, 110.2, 115)]
    _, m1, b, sw = setup("2017-01-10 10:00", rows)
    t = sc.box_breakout(m1, b, sw)
    ok &= check("box breakout", trade_tuple(t[0]) if t else None, (1, 110.2, 107.0, 115.0, 115.0, "target"))

    # RSI divergence: swing low 102 (RSI 25), lower low 101 (RSI 35), bullish candle -> long at the next open,
    # stop at the lower low, target 1.5 x risk
    rows = [110, 106, 102, 105, 104, 101, (101.2, 102.1, 101.1, 102), (102.1, 102.2, 102, 102.1),
            (102.1, 104, 102, 103.9)]
    _, m1, b, sw = setup("2017-01-10 10:00", rows)
    r = np.full(b.n, 50.0)
    r[2], r[5] = 25, 35
    t = sc.rsi_divergence(m1, b, sw, r)
    ok &= check("RSI divergence", trade_tuple(t[0]) if t else None, (1, 102.1, 101.0, 103.75, 103.75, "target"))
    r[5] = 24
    ok &= check("RSI divergence, second low outside 30-70: no trade", sc.rsi_divergence(m1, b, sw, r), [])
    ok &= check("... unless the rule is off", len(sc.rsi_divergence(m1, b, sw, np.where(np.arange(b.n) == 2, 25.0,
                                                                                         np.where(np.arange(b.n) == 5, 26.0, 50.0)),
                                                      sauce=False)), 1)

    # Fibonacci pullback: swing low 100, swing high 110, close below 100 (break of structure), low 95;
    # retracement past 33 % -> sell limit at 0.618 = 104.27, stop 110, target 95
    base = [103, 101, 100, 103, 107, 110, 107, 103, 99, 95, (95.5, 100.5, 95.2, 100)]
    rows = base + [(100, 104.5, 100, 104), (104, 104.2, 99, 99.5), (99.5, 99.6, 94.8, 95)]
    _, m1, b, sw = setup("2017-01-10 10:00", rows)
    t = sc.fib_pullback(m1, b, sw)
    ok &= check("Fibonacci pullback", trade_tuple(t[0]) if t else None, (-1, 104.27, 110.0, 95.0, 95.0, "target"))
    # through the limit and the stop in one bar: filled, then stopped
    rows = base + [(100, 111, 100, 110.5), (110.5, 111, 104, 105)]
    _, m1, b, sw = setup("2017-01-10 10:00", rows)
    t = sc.fib_pullback(m1, b, sw)
    ok &= check("Fibonacci, limit and stop in one bar", trade_tuple(t[0]) if t else None,
                (-1, 104.27, 110.0, 95.0, 110.0, "stop"))
    # a jump above the impulse start: the resting limit fills at its price, the stop at the worse open
    rows = base + [(110.5, 111, 110.2, 110.8), (110.8, 111, 104, 105)]
    _, m1, b, sw = setup("2017-01-10 10:00", rows)
    t = sc.fib_pullback(m1, b, sw)
    ok &= check("Fibonacci, open above the impulse start", trade_tuple(t[0]) if t else None,
                (-1, 104.27, 110.0, 95.0, 110.5, "stop"))
    # a new low before the fill cancels the order and the impulse 110 -> 93 is measured again (limit 103.506);
    # zigzag threshold 6 so that the bounce to 100.5 is no swing of its own. Before that, the long limit of the
    # impulse 100 -> 110 (103.82, resting below the close of 104) is filled by the jump to 99 and stopped there
    rows = [106, 100, 100, 106, 110, 104, 99, 95, (95.5, 100.5, 95.2, 100), (100, 100.2, 93, 93.5),
            (93.5, 99, 93.4, 98.9), (98.9, 104, 98.8, 103.8), (103.8, 103.9, 92.9, 93)]
    _, m1, b, sw = setup("2017-01-10 10:00", rows, thr=6.0)
    t = sc.fib_pullback(m1, b, sw)
    ok &= check("Fibonacci, impulse extended before the fill", tuple(trade_tuple(x) for x in t),
                ((1, 103.82, 100.0, 110.0, 99.0, "stop"), (-1, 93 + 0.618 * 17, 110.0, 93.0, 93.0, "target")))

    # R multiples and costs: risk 10 bp, 0.4 bp per side -> 0.08 R of costs
    df = sc.to_frame([{"side": 1, "entry": 100.0, "stop": 99.9, "exit": 100.15, "entry_i": 0, "kind": "x",
                       "reason": "target"}], m1, 0.00004)
    ok &= check("R before / after costs", (float(df.r_gross[0]), float(df.r_net[0])), (1.5, 1.42))
    print("ALL CHECKS PASSED" if ok else "CHECKS FAILED")


if __name__ == "__main__":
    main()
