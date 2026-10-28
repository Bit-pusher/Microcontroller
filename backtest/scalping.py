"""Scalping rules of the video "The ONLY 1 Minute Scalping Guide You'll Ever Need", made mechanical.

The video trades EURUSD on 1 and 5 minutes. It sorts the market into three states and gives each a method:
- sideways: breakout of a consolidation box (price failed to make a higher high and a lower low); a candle
  closing outside the box enters with the breakout, stop at the middle of the box, target 1.5 x the risk;
- trend: Fibonacci pullbacks; after an impulse that broke the previous swing, once price has retraced
  33 %, a limit order at the 0.618 retracement, stop at the start of the impulse, target at its end (1:1.6);
- end of a trend: RSI divergence; a lower low whose RSI is higher than at the previous swing low, the first
  RSI low below 30 and the second inside 30-70; enter on the first bullish candle, stop at the low, target
  1.5 x the risk (mirrored at tops).
Its daily plan combines them: the first 5-minute close outside the Tokyo session range sets the bias and is
traded itself (stop half the range, target twice the risk), then Fibonacci pullbacks in the bias direction
until an RSI divergence against the bias, which is the last trade of the day; at most four trades a day.

What the video leaves to the eye is fixed here:
- swings: a zigzag that turns when price moves SWING_ATR x ATR(14) against the running extreme (the video
  draws them by hand with the brush tool);
- the Tokyo session: 19:00-04:00 New York (the usual forex session clock), breakouts until 12:00 New York;
- RSI(14), EMA(200); no entries from 16:30 to 18:00 New York, every position is closed at 17:00 New York,
  the end of the forex day.
Execution on 1-minute bars: a signal at a bar close fills at the next bar's open, a limit order at its price
(or a better open), stops and targets at their price (or a worse open); a bar touching both counts as the
stop. A limit order's fill bar can stop the trade out but never reach the target.
"""
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "data", "fx")
SWING_ATR = 3.0
ATR_N, RSI_N, EMA_N = 14, 14, 200
TOKYO = {"19-04": (19 * 60, 4 * 60), "20-03": (20 * 60, 3 * 60)}   # New York minutes
BREAKOUT_UNTIL = 12 * 60
NO_ENTRY = (16 * 60 + 30, 18 * 60)
RR_BOX, RR_TOKYO, RR_DIV = 1.5, 2.0, 1.5
FIB_TRIGGER, FIB_ENTRY = 0.33, 0.618
DIV_WINDOW = 5                       # bars back from the bullish candle in which the lower low may lie


# ---------------------------------------------------------------------------------------------- data
def prepare(m):
    """New York minute of day, and the forex trading day (17:00 to 17:00 New York, named by its end)."""
    ny = pd.to_datetime(m["time"], unit="s", utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    return m.assign(minute=(ny.dt.hour * 60 + ny.dt.minute).to_numpy(),
                    day=(ny + pd.Timedelta(hours=7)).dt.normalize().to_numpy())


def load(symbol):
    return prepare(pd.read_csv(os.path.join(FX, f"{symbol}_M1.csv.gz")))


class M1:
    """1-minute arrays, plus the index of the last bar of each bar's trading day."""

    def __init__(self, m):
        self.o, self.h, self.l, self.c = (m[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.minute = m["minute"].to_numpy()
        self.day = m["day"].to_numpy()
        starts = np.flatnonzero(np.r_[True, self.day[1:] != self.day[:-1]])
        ends = np.r_[starts[1:], len(self.day)] - 1
        self.day_end = np.repeat(ends, np.diff(np.r_[starts, len(self.day)]))
        self.n = len(self.c)
        self.entry_ok = ~((self.minute >= NO_ENTRY[0]) & (self.minute < NO_ENTRY[1]))


class Bars:
    """Bars of `minutes` built from 1-minute bars; first / last hold the 1-minute indices of each bar."""

    def __init__(self, m, m1, minutes):
        if minutes == 1:
            self.first = self.last = np.arange(m1.n)
            self.o, self.h, self.l, self.c = m1.o, m1.h, m1.l, m1.c
        else:
            b = (m["time"].to_numpy() // (60 * minutes))
            self.first = np.flatnonzero(np.r_[True, b[1:] != b[:-1]])
            self.last = np.r_[self.first[1:], len(b)] - 1
            self.o, self.c = m1.o[self.first], m1.c[self.last]
            self.h = np.maximum.reduceat(m1.h, self.first)
            self.l = np.minimum.reduceat(m1.l, self.first)
        self.n = len(self.c)
        self.minutes = minutes


# ---------------------------------------------------------------------------------------------- indicators
def wilder(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy(copy=True)


def atr(b, n=ATR_N):
    pc = np.r_[b.c[0], b.c[:-1]]
    tr = np.maximum(b.h - b.l, np.maximum(np.abs(b.h - pc), np.abs(b.l - pc)))
    out = wilder(tr, n)
    out[:n] = np.nan
    return out


def rsi(c, n=RSI_N):
    d = np.diff(c, prepend=c[0])
    up, dn = wilder(np.maximum(d, 0), n), wilder(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(dn > 0, 100 - 100 / (1 + up / dn), 100.0)
    out[:n] = np.nan
    return out


def ema(c, n=EMA_N):
    out = pd.Series(c).ewm(span=n, adjust=False).mean().to_numpy(copy=True)
    out[:n] = np.nan
    return out


def zigzag(h, l, thr):
    """Alternating swing points of a zigzag that turns once price moves thr[i] against the running extreme.
    Returns kind (+1 high, -1 low), idx (bar of the extreme), price, conf (bar at whose close it is known)."""
    kind, idx, price, conf = [], [], [], []
    d, ext, ext_i = 1, h[0], 0
    for i in range(1, len(h)):
        t = thr[i]
        if not t > 0:
            continue
        if d == 1:
            if h[i] > ext:
                ext, ext_i = h[i], i
            elif ext - l[i] >= t:
                kind.append(1); idx.append(ext_i); price.append(ext); conf.append(i)
                d, ext, ext_i = -1, l[i], i
        else:
            if l[i] < ext:
                ext, ext_i = l[i], i
            elif h[i] - ext >= t:
                kind.append(-1); idx.append(ext_i); price.append(ext); conf.append(i)
                d, ext, ext_i = 1, h[i], i
    return np.array(kind, int), np.array(idx, int), np.array(price, float), np.array(conf, int)


# ---------------------------------------------------------------------------------------------- execution
def exit_trade(m1, side, start, stop, target, end):
    """First stop or target from 1-minute bar `start` to `end` (inclusive); the stop wins a tie.
    Returns (exit index, exit price, reason); at `end` the trade closes at that bar's close."""
    if start > end:
        return end, m1.c[end], "day end"
    h, l, o = m1.h[start:end + 1], m1.l[start:end + 1], m1.o[start:end + 1]
    s = np.flatnonzero(l <= stop if side > 0 else h >= stop)
    t = np.flatnonzero(h >= target if side > 0 else l <= target)
    if len(s) and (not len(t) or s[0] <= t[0]):
        k = s[0]
        return start + k, (min(stop, o[k]) if side > 0 else max(stop, o[k])), "stop"
    if len(t):
        k = t[0]
        return start + k, (max(target, o[k]) if side > 0 else min(target, o[k])), "target"
    return end, m1.c[end], "day end"


def market_trade(m1, kind, side, e, stop, rr=None, target=None):
    """Enter at the open of 1-minute bar e; target either given or rr x the risk."""
    if e >= m1.n or not m1.entry_ok[e]:
        return None
    entry = m1.o[e]
    risk = (entry - stop) * side
    if not risk > 0:
        return None
    target = entry + side * rr * risk if target is None else target
    if (target - entry) * side <= 0:
        return None
    end = m1.day_end[e]
    x, px, why = exit_trade(m1, side, e, stop, target, end)
    return {"kind": kind, "side": side, "entry_i": e, "entry": entry, "stop": stop, "target": target,
            "exit_i": x, "exit": px, "reason": why}


# ---------------------------------------------------------------------------------------------- detectors
def tokyo_breakout(m1, m5, window="19-04"):
    """Daily bias trade: first 5-minute close outside the Tokyo range, stop half the range, target 2 x risk."""
    a, e = TOKYO[window]
    in_range = (m1.minute >= a) | (m1.minute < e)
    days = pd.Series(m1.day)
    hi = pd.Series(np.where(in_range, m1.h, -np.inf)).groupby(days).max()
    lo = pd.Series(np.where(in_range, m1.l, np.inf)).groupby(days).min()
    start_min = m1.minute[m5.first]
    ok = (start_min >= e) & (start_min < BREAKOUT_UNTIL)
    trades, done = [], set()
    for k in np.flatnonzero(ok):
        d = m1.day[m5.last[k]]
        if d in done:
            continue
        top, bottom = hi.get(d, -np.inf), lo.get(d, np.inf)
        if not (np.isfinite(top) and np.isfinite(bottom) and top > bottom):
            continue
        side = 1 if m5.c[k] > top else -1 if m5.c[k] < bottom else 0
        if side == 0:
            continue
        done.add(d)
        eidx = m5.last[k] + 1
        if eidx >= m1.n or m1.day[eidx] != d:
            continue
        half = 0.5 * (top - bottom)
        t = market_trade(m1, "tokyo", side, eidx, m1.o[eidx] - side * half, rr=RR_TOKYO)
        if t:
            t["range"] = top - bottom
            trades.append(t)
    return trades


def box_breakout(m1, b, sw):
    """Consolidation box: the last swing high below the one before and the last swing low above the one
    before. The first close outside it enters with the breakout, stop at the box middle, target 1.5 x risk."""
    kind, idx, price, conf = sw
    trades = []
    box = None
    highs, lows = [], []
    j = 0
    for k in range(b.n):
        while j < len(conf) and conf[j] <= k:
            (highs if kind[j] > 0 else lows).append(price[j])
            if len(highs) >= 2 and len(lows) >= 2 and highs[-1] <= highs[-2] and lows[-1] >= lows[-2]:
                box = (lows[-1], highs[-1], conf[j])
            j += 1
        if box is None or k <= box[2]:
            continue
        lo, hi, _ = box
        side = 1 if b.c[k] > hi else -1 if b.c[k] < lo else 0
        if side:
            box = None
            t = market_trade(m1, "box", side, b.last[k] + 1, 0.5 * (lo + hi), rr=RR_BOX)
            if t:
                trades.append(t)
    return trades


def rsi_divergence(m1, b, sw, r, sauce=True):
    """A lower low (within DIV_WINDOW bars before a bullish candle) below the last confirmed swing low, with a
    higher RSI there; with `sauce`, RSI below 30 at the swing low and inside 30-70 at the lower low. Enter on
    the bullish candle, stop at the lower low, target 1.5 x risk. Tops mirrored."""
    kind, idx, price, conf = sw
    trades, used = [], set()
    last = {1: None, -1: None}           # last confirmed swing high / low: (idx, price, conf)
    j = 0
    for k in range(DIV_WINDOW, b.n):
        while j < len(conf) and conf[j] <= k:
            last[kind[j]] = (idx[j], price[j], conf[j], j)
            j += 1
        bull, bear = b.c[k] > b.o[k], b.c[k] < b.o[k]
        if bull and last[-1] is not None:
            s_i, s_p, s_c, s_j = last[-1]
            p = k - DIV_WINDOW + int(np.argmin(b.l[k - DIV_WINDOW:k + 1]))
            if p > s_c and b.l[p] < s_p and s_j not in used and r[p] > r[s_i] and \
                    (not sauce or (r[s_i] < 30 <= r[p] <= 70)):
                t = market_trade(m1, "rsi", 1, b.last[k] + 1, b.l[p], rr=RR_DIV)
                if t:
                    used.add(s_j)
                    trades.append(t)
        if bear and last[1] is not None:
            s_i, s_p, s_c, s_j = last[1]
            p = k - DIV_WINDOW + int(np.argmax(b.h[k - DIV_WINDOW:k + 1]))
            if p > s_c and b.h[p] > s_p and s_j not in used and r[p] < r[s_i] and \
                    (not sauce or (r[s_i] > 70 >= r[p] >= 30)):
                t = market_trade(m1, "rsi", -1, b.last[k] + 1, b.h[p], rr=RR_DIV)
                if t:
                    used.add(s_j)
                    trades.append(t)
    return trades


def _fib_order(m1, side, start, impulse_end, impulse_start):
    """Pending limit at the 0.618 retracement from 1-minute bar `start` on. Returns the trade, or
    ("cancel", bar, new impulse end) when price extends the impulse first, or ("void", bar) when it breaks
    the impulse start, or None at the day end."""
    end = m1.day_end[start] if start < m1.n else m1.n - 1
    if start > end:
        return None
    rng = (impulse_start - impulse_end) * -side          # size of the impulse, positive
    limit = impulse_end + (FIB_ENTRY * rng if side < 0 else -FIB_ENTRY * rng)
    h, l, o = m1.h[start:end + 1], m1.l[start:end + 1], m1.o[start:end + 1]
    if side < 0:      # short: sell limit above, the impulse end is the low
        fill = np.flatnonzero(h >= limit)
        ext = np.flatnonzero(l < impulse_end)
        void = np.flatnonzero(h > impulse_start)
    else:
        fill = np.flatnonzero(l <= limit)
        ext = np.flatnonzero(h > impulse_end)
        void = np.flatnonzero(l < impulse_start)
    f = fill[0] if len(fill) else None
    x = ext[0] if len(ext) else None
    if x is not None and (f is None or x <= f):
        k = x
        new_end = l[: k + 1].min() if side < 0 else h[: k + 1].max()
        return ("cancel", start + k, new_end)
    if f is None:
        return None
    if len(void) and void[0] < f:
        return ("void", start + void[0])
    fi = start + f
    if not m1.entry_ok[fi]:
        return ("void", fi)
    entry = max(limit, o[f]) if side < 0 else min(limit, o[f])
    stop, target = impulse_start, impulse_end
    if (stop - entry) * -side <= 0:                       # opened beyond the stop
        return ("void", fi)
    if (m1.h[fi] >= stop) if side < 0 else (m1.l[fi] <= stop):
        xi, px, why = fi, stop, "stop"
    else:
        xi, px, why = exit_trade(m1, side, fi + 1, stop, target, m1.day_end[fi])
    return {"kind": "fib", "side": side, "entry_i": fi, "entry": entry, "stop": stop, "target": target,
            "exit_i": xi, "exit": px, "reason": why}


def _catch_up(st, side, b, upto):
    """Apply the bars after st["seen"] up to `upto` to an impulse state (bars skipped during a trade)."""
    a = st["seen"] + 1
    if a > upto:
        return
    if side < 0:
        if b.h[a:upto + 1].max() > st["start"]:
            st["done"] = True
        st["ext"] = min(st["ext"], b.l[a:upto + 1].min())
        st["bos"] = st["bos"] or bool((b.c[a:upto + 1] < st["prev"]).any())
    else:
        if b.l[a:upto + 1].min() < st["start"]:
            st["done"] = True
        st["ext"] = max(st["ext"], b.h[a:upto + 1].max())
        st["bos"] = st["bos"] or bool((b.c[a:upto + 1] > st["prev"]).any())
    st["seen"] = upto


def fib_pullback(m1, b, sw, ema_line=None, allow=None):
    """After a close beyond the swing before the last swing (break of structure), measure the impulse from that
    last swing to the running extreme; once price retraces 33 % of it, a limit at 0.618, stop at the impulse
    start, target at the impulse end. `ema_line`: trade only on its side; `allow(side, m1_index)`: extra filter.
    Each impulse gives at most one trade; one trade at a time."""
    kind, idx, price, conf = sw
    trades = []
    last = {1: None, -1: None}            # last confirmed swing high / low: (idx, price)
    states = {}                           # side -> impulse state; side -1: down impulse from a swing high
    j = 0
    k = 0
    while k < b.n:
        while j < len(conf) and conf[j] <= k:
            prev = last[-kind[j]]             # the swing before: its level is the structure to break
            last[kind[j]] = (idx[j], price[j])
            if prev is not None:
                side, si, sp, level = (-1 if kind[j] == 1 else 1), idx[j], price[j], prev[1]
                lo, hi, cl = b.l[si:k + 1], b.h[si:k + 1], b.c[si:k + 1]
                states[side] = {"start": sp, "prev": level, "seen": k, "created": k, "resume": -1,
                                "done": False,
                                "ext": lo.min() if side < 0 else hi.max(),
                                "bos": bool((cl < level).any()) if side < 0 else bool((cl > level).any())}
            j += 1
        nxt = k + 1
        for side, st in states.items():
            if k <= st["resume"]:
                continue
            _catch_up(st, side, b, k - 1)
            if st["done"] or st["created"] == k:
                continue
            st["seen"] = k
            if (b.h[k] > st["start"]) if side < 0 else (b.l[k] < st["start"]):
                st["done"] = True
                continue
            new_ext = (b.l[k] < st["ext"]) if side < 0 else (b.h[k] > st["ext"])
            if new_ext:
                st["ext"] = b.l[k] if side < 0 else b.h[k]
            if not st["bos"] and ((b.c[k] < st["prev"]) if side < 0 else (b.c[k] > st["prev"])):
                st["bos"] = True
            if not st["bos"] or new_ext or nxt > k + 1:
                continue
            rng = (st["start"] - st["ext"]) * -side
            retr = (b.h[k] - st["ext"]) if side < 0 else (st["ext"] - b.l[k])
            if not rng > 0 or retr < FIB_TRIGGER * rng:
                continue
            if ema_line is not None and not ((b.c[k] < ema_line[k]) if side < 0 else (b.c[k] > ema_line[k])):
                st["done"] = True
                continue
            if allow is not None and not allow(side, b.last[k]):
                continue
            res = _fib_order(m1, side, b.last[k] + 1, st["ext"], st["start"])
            if isinstance(res, dict):
                trades.append(res)
                st["done"] = True
                nxt = int(np.searchsorted(b.last, res["exit_i"])) + 1
            elif res is not None and res[0] == "cancel":       # the impulse went on: measure it again later
                st["ext"] = res[2]
                st["seen"] = st["resume"] = int(np.searchsorted(b.last, res[1]))
            else:
                st["done"] = True
        k = nxt
    return trades


# ---------------------------------------------------------------------------------------------- combination
def one_at_a_time(trades, per_day=None):
    """Keep trades in entry order that start after the previous kept one ended; at most per_day a day."""
    out, busy, count = [], -1, {}
    for t in sorted(trades, key=lambda x: x["entry_i"]):
        if t["entry_i"] <= busy:
            continue
        d = t.get("day")
        if per_day is not None and count.get(d, 0) >= per_day:
            continue
        out.append(t)
        busy = t["exit_i"]
        count[d] = count.get(d, 0) + 1
    return out


def day_plan(m1, m5, b1, sw1, r1, window="19-04", max_fib=3, max_trades=4):
    """The video's day: Tokyo breakout sets the bias and is traded; Fibonacci pullbacks (1 minute) in the bias
    direction until the first RSI divergence against it, which is traded as the last trade of the day."""
    tok = {m1.day[t["entry_i"]]: t for t in tokyo_breakout(m1, m5, window)}
    rsi_all = rsi_divergence(m1, b1, sw1, r1, sauce=True)
    counter = {}
    for t in sorted(rsi_all, key=lambda x: x["entry_i"]):
        d = m1.day[t["entry_i"]]
        if d in tok and t["side"] == -tok[d]["side"] and t["entry_i"] > tok[d]["entry_i"] and d not in counter:
            counter[d] = t
    fib_count = {}

    def allow(side, i):
        d = m1.day[i]
        if d not in tok or side != tok[d]["side"] or i <= tok[d]["entry_i"]:
            return False
        if d in counter and i >= counter[d]["entry_i"]:
            return False
        return fib_count.get(d, 0) < min(max_fib, max_trades - 1)

    fibs = []
    for t in fib_pullback(m1, b1, sw1, allow=allow):
        d = m1.day[t["entry_i"]]
        if fib_count.get(d, 0) < min(max_fib, max_trades - 1):
            fib_count[d] = fib_count.get(d, 0) + 1
            fibs.append(t)
    fibs = one_at_a_time(fibs)
    out = list(tok.values()) + fibs
    for d, t in counter.items():
        n_day = 1 + sum(1 for f in fibs if m1.day[f["entry_i"]] == d)
        busy = max([f["exit_i"] for f in fibs if m1.day[f["entry_i"]] == d], default=-1)
        if n_day < max_trades and t["entry_i"] > busy:
            out.append(t)
    return out


# ---------------------------------------------------------------------------------------------- evaluation
def to_frame(trades, m1, cost_per_side):
    """Trades with R multiples before and after costs (costs as a fraction of price, per side)."""
    if not trades:
        return pd.DataFrame(columns=["day", "side", "kind", "r_gross", "r_net", "risk_bp", "reason"])
    df = pd.DataFrame(trades)
    risk = (df["entry"] - df["stop"]).abs()
    df["r_gross"] = df["side"] * (df["exit"] - df["entry"]) / risk
    df["risk_bp"] = risk / df["entry"] * 1e4
    df["r_net"] = df["r_gross"] - 2 * cost_per_side * 1e4 / df["risk_bp"]
    df["day"] = m1.day[df["entry_i"].to_numpy()]
    return df
