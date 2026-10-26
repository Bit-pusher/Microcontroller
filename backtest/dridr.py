"""DR / IDR (Defining Range / Implied Defining Range) and trading rules derived from it.

The concept is TheMas7er's (November 2022). On TradingView it is drawn by
"DR/IDR V1.5" (TheMas7er and bmistiaen, MPL-2.0) and LuxAlgo's "DR/IDR
Candles"; the definitions below follow the V1.5 source. On 5-minute bars:
- DR: high and low of the bars opening in the first hour of a session, wicks
  included. Regular session (RDR) 09:30-10:30 New York, lines until 16:00;
  after-hours session (ADR) 19:30-20:30, lines until 02:00; overnight session
  (ODR) 03:00-04:00, lines until 08:30.
- IDR: highest and lowest candle body (open / close) of the same hour.
- Published rules: a 5-minute close above the DR high after the hour means the
  DR low will likely hold as the low of the session (the V1 description says
  "80 %"); a close below the DR low, the DR high will likely hold. A close
  beyond the IDR is an early indication of the same.
- Levels: "standard deviations" in steps of 0.5 x the IDR range beyond the IDR.
  V1.5 draws them from the regular session's IDR only; here every session uses
  its own IDR.
The scripts only draw these levels and have no entry or exit logic. RULES
below derive intraday trades from them; stats() measures the rules themselves.

Execution: a signal is known at the close of its 5-minute bar; a market order
fills at the next bar's open, a limit order at its price (or a better open),
a stop at its price (or a worse open). When a bar touches both the stop and the
target, the stop is assumed to come first. Every position is closed at the
close of the last bar of the session. One trade per session and day.
"""
import itertools
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
INDICES = os.path.join(HERE, "data", "indices")
SYMBOLS = {"SPX500": "SPX500_USD", "NAS100": "NAS100_USD", "US2000": "US2000_USD"}
SESSIONS = {  # name: (DR start, DR end, end of the lines), minutes after midnight New York
    "RDR": (9 * 60 + 30, 10 * 60 + 30, 16 * 60),
    "ADR": (19 * 60 + 30, 20 * 60 + 30, 2 * 60),        # lines until 02:00 the next morning
    "ODR": (3 * 60, 4 * 60, 8 * 60 + 30),
}
MIN_DR_BARS = 10                 # of 12: days with gaps in the defining hour are skipped


def prepare(b):
    """Add the New York date and minute of day to bars with UTC times."""
    ny = pd.to_datetime(b["time"], unit="s", utc=True).dt.tz_convert("America/New_York")
    return b.assign(date=ny.dt.tz_localize(None).dt.normalize(), minute=(ny.dt.hour * 60 + ny.dt.minute).astype(int))


def load(market):
    return prepare(pd.read_csv(os.path.join(INDICES, f"{SYMBOLS[market]}_M5.csv")))


def sessions(b, name):
    """Per day: DR / IDR levels and the bars of the session after the defining hour. A session belongs
    to the day its defining hour starts on (the ADR runs past midnight)."""
    a, e, end = SESSIONS[name]
    hour, span = (e - a) % 1440, (end - a) % 1440
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    m = b["minute"].to_numpy()
    rel = (m - a) % 1440                                   # minutes since the start of the defining hour
    day = b["date"] - pd.to_timedelta((m < a).astype(int), unit="D")
    out = []
    for date, idx in pd.Series(np.arange(len(b))).groupby(day.to_numpy()).indices.items():
        ri = rel[idx]
        dr = idx[ri < hour]
        tr = idx[(ri >= hour) & (ri < span)]
        if len(dr) < MIN_DR_BARS or len(tr) == 0:
            continue
        out.append({
            "date": pd.Timestamp(date),
            "dr_hi": h[dr].max(), "dr_lo": l[dr].min(),
            "idr_hi": np.maximum(o[dr], c[dr]).max(), "idr_lo": np.minimum(o[dr], c[dr]).min(),
            "o": o[tr], "h": h[tr], "l": l[tr], "c": c[tr],
        })
    return out


def first(mask, start=0):
    """Index of the first True at or after start, or None."""
    k = np.flatnonzero(mask[start:])
    return int(k[0]) + start if len(k) else None


def confirmation(d, level="dr"):
    """(bar, side) of the first close beyond the DR (level 'dr') or the IDR ('idr'), or (None, 0)."""
    hi, lo = (d["dr_hi"], d["dr_lo"]) if level == "dr" else (d["idr_hi"], d["idr_lo"])
    up, dn = first(d["c"] > hi), first(d["c"] < lo)
    if up is None and dn is None:
        return None, 0
    if dn is None or (up is not None and up < dn):
        return up, 1
    return dn, -1


def shuffled(d, rng):
    """Placebo day: the session's bars after the defining hour in random order, each keeping its own
    shape (high, low, close relative to its open) and its opening gap. Same DR, same volatility,
    no sequence left."""
    o, h, l, c = d["o"], d["h"], d["l"], d["c"]
    gap = np.r_[0.0, o[1:] - c[:-1]]
    order = rng.permutation(len(o))
    no, nh, nl, nc = (np.empty(len(o)) for _ in range(4))
    price = o[0]
    for j, k in enumerate(order):
        if j:
            price = nc[j - 1] + gap[k]
        no[j], nh[j], nl[j], nc[j] = price, price + h[k] - o[k], price + l[k] - o[k], price + c[k] - o[k]
    return {**d, "o": no, "h": nh, "l": nl, "c": nc}


def stats(days, rng=None):
    """How often the published rules held: after the first close beyond the DR (IDR), the opposite DR
    side is not traded through until the end of the session (from the confirming bar on).
    With rng, on placebo days (shuffled)."""
    rows = []
    for d in days:
        if rng is not None:
            d = shuffled(d, rng)
        row = {"date": d["date"], "range": (d["dr_hi"] - d["dr_lo"]) / d["dr_lo"]}
        for level in ("dr", "idr"):
            k, side = confirmation(d, level)
            row[level + "_side"] = side
            if side:
                row[level + "_held"] = bool(d["l"][k:].min() >= d["dr_lo"]) if side > 0 else \
                    bool(d["h"][k:].max() <= d["dr_hi"])
        rows.append(row)
    return pd.DataFrame(rows)


def trade(d, entry, stop, target, long_only):
    """Simulate one session; returns (side, entry price, exit price) or None."""
    k, side = confirmation(d, "idr" if entry == "idr" else "dr")
    if side == 0 or (long_only and side < 0) or k + 1 >= len(d["o"]):
        return None
    o, h, l, c = d["o"], d["h"], d["l"], d["c"]
    rng = d["idr_hi"] - d["idr_lo"]
    if side > 0:
        sl = d["dr_lo"] if stop == "dr" else 0.5 * (d["dr_hi"] + d["dr_lo"])
        tp = d["idr_hi"] + target * rng if target else None
        limit = d["idr_hi"]
    else:
        sl = d["dr_hi"] if stop == "dr" else 0.5 * (d["dr_hi"] + d["dr_lo"])
        tp = d["idr_lo"] - target * rng if target else None
        limit = d["idr_lo"]
    s = side            # work in "long" coordinates: x * s rises when the trade wins
    if entry == "retrace":
        fill = first(l <= limit, k + 1) if s > 0 else first(h >= limit, k + 1)
        if fill is None:
            return None
        if tp is not None:
            gone = first(h >= tp, k + 1) if s > 0 else first(l <= tp, k + 1)
            if gone is not None and gone < fill:
                return None                                    # target reached without a retracement
        if (o[fill] - sl) * s <= 0:
            return None                                        # opened beyond the stop: setup invalid
        px = min(limit, o[fill]) if s > 0 else max(limit, o[fill])
        if (px - sl) * s <= 0 or (tp is not None and (tp - px) * s <= 0):
            return None
        if (l[fill] <= sl) if s > 0 else (h[fill] >= sl):
            return side, px, sl                                # stopped in the fill bar
        j0 = fill + 1
    else:
        px = o[k + 1]
        if (px - sl) * s <= 0 or (tp is not None and (tp - px) * s <= 0):
            return None
        j0 = k + 1
    if j0 >= len(o):
        return side, px, c[-1]
    hit_sl = first(l <= sl, j0) if s > 0 else first(h >= sl, j0)
    hit_tp = None if tp is None else (first(h >= tp, j0) if s > 0 else first(l <= tp, j0))
    if hit_sl is not None and (hit_tp is None or hit_sl <= hit_tp):
        return side, px, (min(sl, o[hit_sl]) if s > 0 else max(sl, o[hit_sl]))
    if hit_tp is not None:
        return side, px, (max(tp, o[hit_tp]) if s > 0 else min(tp, o[hit_tp]))
    return side, px, c[-1]


# (key, entry, stop, target): pre-declared rule grid, each for both sessions and both sides
ENTRIES = {"confirm": "DR-Bestätigung", "idr": "IDR-Bestätigung", "retrace": "Rücklauf an die IDR"}
STOPS = {"dr": "Stop DR-Gegenseite", "mid": "Stop DR-Mitte"}
TARGETS = {None: "bis Sessionende", 0.5: "Ziel 0,5 SD", 1.0: "Ziel 1 SD"}
RULES = [{"session": s, "entry": e, "stop": st, "target": t, "long_only": lo}
         for s, e, st, t, lo in itertools.product(SESSIONS, ENTRIES, STOPS, TARGETS, (False, True))]


def rule_name(r):
    return (f"{r['session']}: {ENTRIES[r['entry']]}, {STOPS[r['stop']]}, {TARGETS[r['target']]}, "
            f"{'nur Long' if r['long_only'] else 'Long+Short'}")


def daily_returns(days, rule, cost_per_side):
    """Return per day (0 without a trade) and the list of trades (date, side, return)."""
    ret, trades = {}, []
    for d in days:
        t = trade(d, rule["entry"], rule["stop"], rule["target"], rule["long_only"])
        r = 0.0
        if t is not None:
            side, px, ex = t
            r = side * (ex / px - 1.0) - 2 * cost_per_side
            trades.append((d["date"], side, r))
        ret[d["date"]] = r
    return pd.Series(ret).sort_index(), trades
