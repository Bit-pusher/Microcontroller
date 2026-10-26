"""Smart Money Concepts (SMC) [LuxAlgo], computed bar by bar, plus trading rules derived from it.

This is a Python port of the market structure, order block, equal high/low and
trailing swing logic of LuxAlgo's Pine script (https://www.tradingview.com/script/CnB3fSph/).
The original is (c) LuxAlgo and licensed CC BY-NC-SA 4.0
(https://creativecommons.org/licenses/by-nc-sa/4.0/); this port is distributed
under the same license: attribution, non-commercial use only, share alike.
check_smc.py compares it object by object with what the original drew on
TradingView.

The indicator only reports events (BOS / CHoCH, new and broken order blocks,
equal highs and lows); it has no entry or exit logic. RULES below derive
positions from those events. Every event is known at the close of its bar: a
swing point is only confirmed `size` bars after it formed, as in the original.
Fair value gaps and higher timeframe levels are not ported (not used here).
"""
import math

import numpy as np
import pandas as pd

EPS = 1e-10          # Pine compares floats with an absolute tolerance of 1e-10
BULLISH, BEARISH = 1, -1
BULLISH_LEG, BEARISH_LEG = 1, 0


def gt(a, b):
    return a - b > EPS


def lt(a, b):
    return b - a > EPS


def eq(a, b):
    return not gt(a, b) and not lt(a, b)


def isna(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


def pine_round(x):
    return int(math.floor(x + 0.5))


class Pivot:
    __slots__ = ("current", "last", "crossed", "bar_time", "bar_index")

    def __init__(self):
        self.current, self.last, self.crossed, self.bar_time, self.bar_index = math.nan, math.nan, False, None, None


def _rma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1] = np.mean(x[:n])
        for i in range(n, len(x)):
            out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def compute(o, h, l, c, t, swing_length=50, internal_length=5, equal_length=3, equal_threshold=0.1,
            ob_filter="Atr", mitigation="High/Low", confluence=False, internal_obs=True, swing_obs=False,
            equal_highs_lows=True):
    """Run the indicator over all bars. Returns per-bar states and the drawn objects."""
    n = len(c)
    o, h, l, c = (np.asarray(a, float) for a in (o, h, l, c))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.fmax(np.fmax(h - l, np.abs(h - pc)), np.abs(l - pc))
    tr[0] = h[0] - l[0]
    atr = _rma(tr, 200)
    if ob_filter == "Atr":
        vol = atr
    else:                               # ta.cum(ta.tr) / bar_index
        tr_false = tr.copy()
        tr_false[0] = np.nan
        cum = np.nancumsum(tr_false)
        with np.errstate(divide="ignore", invalid="ignore"):
            vol = np.where(np.arange(n) > 0, cum / np.arange(n), np.nan)
    with np.errstate(invalid="ignore"):
        high_vol = ~np.isnan(vol) & ((h - l) - 2 * vol >= -EPS)
    p_high = np.where(high_vol, l, h)
    p_low = np.where(high_vol, h, l)
    sizes = {"swing": swing_length, "internal": internal_length, "equal": equal_length}
    roll_hi = {k: pd.Series(h).rolling(s).max().to_numpy() for k, s in sizes.items()}
    roll_lo = {k: pd.Series(l).rolling(s).min().to_numpy() for k, s in sizes.items()}

    pivots = {k: (Pivot(), Pivot()) for k in sizes}           # (high, low)
    leg_value = {k: 0 for k in sizes}
    leg_prev = {k: None for k in sizes}
    trend = {"internal": 0, "swing": 0}
    cross_prev = {}
    trailing = {"top": math.nan, "bottom": math.nan, "bar_time": None, "bar_index": None,
                "top_time": None, "bottom_time": None}
    obs = {"internal": [], "swing": []}
    bull_bar = bear_bar = True

    out = {
        "bias_before": np.zeros(n, int), "internal_bias": np.zeros(n, int), "swing_bias": np.zeros(n, int),
        "internal_event": np.zeros(n, int), "swing_event": np.zeros(n, int),        # +-1 BOS, +-2 CHoCH
        "trail_top": np.full(n, np.nan), "trail_bottom": np.full(n, np.nan),
        "ob_bull": [None] * n, "ob_bear": [None] * n,                              # newest unmitigated internal OB
    }
    lines, labels, eq_lines, eq_labels = [], [], [], []

    def store_ob(kind, p, bias, i):
        frm = p.bar_index
        if frm is None or frm >= i:
            return
        src = p_high if bias == BEARISH else p_low
        extreme = src[frm:i].max() if bias == BEARISH else src[frm:i].min()
        idx = frm
        while idx < i - 1 and not eq(src[idx], extreme):
            idx += 1
        lst = obs[kind]
        if len(lst) >= 100:
            lst.pop()
        lst.insert(0, {"high": p_high[idx], "low": p_low[idx], "time": t[idx], "bias": bias, "created": i})

    for i in range(n):
        out["bias_before"][i] = trend["internal"]
        # trailing extremes (strong / weak highs and lows, premium / discount zones)
        if not isna(trailing["top"]):
            trailing["top"] = max(h[i], trailing["top"])
            if trailing["top"] == h[i]:
                trailing["top_time"] = t[i]
        if not isna(trailing["bottom"]):
            trailing["bottom"] = min(l[i], trailing["bottom"])
            if trailing["bottom"] == l[i]:
                trailing["bottom_time"] = t[i]

        # swing points: a bar `size` bars ago that is above (below) all bars since
        for kind in ("swing", "internal", "equal"):
            if kind == "equal" and not equal_highs_lows:
                continue
            size = sizes[kind]
            j = i - size
            new_high = j >= 0 and gt(h[j], roll_hi[kind][i])
            new_low = j >= 0 and lt(l[j], roll_lo[kind][i])
            if new_high:
                leg_value[kind] = BEARISH_LEG
            elif new_low:
                leg_value[kind] = BULLISH_LEG
            prev, leg_prev[kind] = leg_prev[kind], leg_value[kind]
            if prev is None or leg_value[kind] == prev:
                continue
            ph, pl = pivots[kind]
            if leg_value[kind] - prev == 1:                     # start of a bullish leg: swing low
                p, level = pl, l[j]
                if kind == "equal" and not isna(p.current) and not isna(atr[i]) and lt(abs(p.current - level), equal_threshold * atr[i]):
                    eq_lines.append((p.bar_time, p.current, t[j], level, "EQL"))
                    eq_labels.append(("EQL", pine_round(0.5 * (p.bar_index + i - size)), level))
            else:                                               # start of a bearish leg: swing high
                p, level = ph, h[j]
                if kind == "equal" and not isna(p.current) and not isna(atr[i]) and lt(abs(p.current - level), equal_threshold * atr[i]):
                    eq_lines.append((p.bar_time, p.current, t[j], level, "EQH"))
                    eq_labels.append(("EQH", pine_round(0.5 * (p.bar_index + i - size)), level))
            p.last, p.current, p.crossed, p.bar_time, p.bar_index = p.current, level, False, t[j], j
            if kind == "swing":
                key = "bottom" if p is pl else "top"
                trailing[key] = level
                trailing["bar_time"], trailing["bar_index"] = t[j], j
                trailing[key + "_time"] = t[j]

        # structure breaks: internal first, then swing (as in the original)
        if confluence:
            body_top, body_bottom = max(c[i], o[i]), min(c[i], o[i] - l[i])   # sic: min(close, open - low)
            bull_bar = gt(h[i] - body_top, body_bottom)
            bear_bar = lt(h[i] - body_top, body_bottom)
        for kind in ("internal", "swing"):
            ph, pl = pivots[kind]
            for p, bias, site in ((ph, BULLISH, kind + "+"), (pl, BEARISH, kind + "-")):
                level, previous = p.current, cross_prev.get(site, math.nan)
                cross_prev[site] = level
                if kind == "internal":
                    sh, sl = pivots["swing"]
                    other = sh if bias == BULLISH else sl
                    extra = (not isna(level) and not isna(other.current) and not eq(level, other.current)
                             and (bull_bar if bias == BULLISH else bear_bar))
                else:
                    extra = True
                if i == 0 or isna(level) or isna(previous) or p.crossed or not extra:
                    continue
                crossed = (gt(c[i], level) and not gt(c[i - 1], previous)) if bias == BULLISH else \
                          (lt(c[i], level) and not lt(c[i - 1], previous))
                if not crossed:
                    continue
                choch = trend[kind] == -bias
                p.crossed = True
                trend[kind] = bias
                out[kind + "_event"][i] = bias * (2 if choch else 1)
                lines.append((p.bar_time, level, t[i], "dsh" if kind == "internal" else "sol", bias))
                labels.append(("CHoCH" if choch else "BOS", pine_round(0.5 * (p.bar_index + i)), level,
                               "ldn" if bias == BULLISH else "lup"))
                if (kind == "internal" and internal_obs) or (kind == "swing" and swing_obs):
                    store_ob(kind, p, bias, i)

        # order block mitigation (Pine's for...in re-reads the size: removing skips the next block)
        bear_src = c[i] if mitigation == "Close" else h[i]
        bull_src = c[i] if mitigation == "Close" else l[i]
        for kind in ("internal", "swing"):
            lst = obs[kind]
            k = 0
            while k < len(lst):
                ob = lst[k]
                if (ob["bias"] == BEARISH and gt(bear_src, ob["high"])) or (ob["bias"] == BULLISH and lt(bull_src, ob["low"])):
                    lst.pop(k)
                k += 1

        out["internal_bias"][i], out["swing_bias"][i] = trend["internal"], trend["swing"]
        out["trail_top"][i], out["trail_bottom"][i] = trailing["top"], trailing["bottom"]
        out["ob_bull"][i] = next((ob for ob in obs["internal"] if ob["bias"] == BULLISH), None)
        out["ob_bear"][i] = next((ob for ob in obs["internal"] if ob["bias"] == BEARISH), None)

    out.update({"lines": lines, "labels": labels, "eq_lines": eq_lines, "eq_labels": eq_labels,
                "internal_obs": obs["internal"], "swing_obs": obs["swing"], "trailing": trailing,
                "swing_trend": trend["swing"]})
    return out


# ---------------------------------------------------------------- trading rules derived from the events
def _ohlct(b):
    return (b["bid_o"].to_numpy(float), b["bid_h"].to_numpy(float), b["bid_l"].to_numpy(float),
            b["bid_c"].to_numpy(float), b["time"].to_numpy())


def rule_swing_structure(s):
    """Swing structure trend: long after a bullish swing BOS/CHoCH, short after a bearish one."""
    return s["swing_bias"].astype(float)


def rule_internal_structure(s):
    """Internal structure trend (the indicator's candle colour)."""
    return s["internal_bias"].astype(float)


def rule_aligned_structure(s):
    """Internal structure in the direction of the swing structure, flat when they disagree."""
    ib, sb = s["internal_bias"], s["swing_bias"]
    return np.where(ib == sb, ib, 0).astype(float)


def rule_order_block_retest(s, h, l, c, allow_short=True):
    """Enter when price returns into the newest unmitigated internal order block in the direction of the
    swing structure; exit when the block breaks (the indicator's own mitigation) or the internal structure
    turns against the position. Each order block is traded at most once."""
    n = len(c)
    pos = np.zeros(n)
    p, stop = 0.0, math.nan
    used = set()
    for i in range(n):
        if p > 0 and (l[i] < stop - EPS or s["internal_event"][i] < 0):
            p = 0.0
        elif p < 0 and (h[i] > stop + EPS or s["internal_event"][i] > 0):
            p = 0.0
        if p == 0:
            ob = s["ob_bull"][i]
            if s["swing_bias"][i] == BULLISH and ob and ob["created"] < i and id(ob) not in used \
                    and l[i] <= ob["high"] and c[i] >= ob["low"]:
                p, stop = 1.0, ob["low"]
                used.add(id(ob))
            ob = s["ob_bear"][i]
            if p == 0 and allow_short and s["swing_bias"][i] == BEARISH and ob and ob["created"] < i \
                    and id(ob) not in used and h[i] >= ob["low"] and c[i] <= ob["high"]:
                p, stop = -1.0, ob["high"]
                used.add(id(ob))
        pos[i] = p
    return pos


def rule_discount_choch(s, c, allow_short=True):
    """Internal CHoCH in the direction of the swing structure, taken only in the discount half of the
    swing range (longs) or the premium half (shorts); exit on the next opposite internal break."""
    n = len(c)
    pos = np.zeros(n)
    p = 0.0
    for i in range(n):
        ev, sb = s["internal_event"][i], s["swing_bias"][i]
        mid = 0.5 * (s["trail_top"][i] + s["trail_bottom"][i])
        if (p > 0 and ev < 0) or (p < 0 and ev > 0):
            p = 0.0
        if p == 0 and not math.isnan(mid):
            if ev == 2 and sb == BULLISH and c[i] < mid:
                p = 1.0
            elif allow_short and ev == -2 and sb == BEARISH and c[i] > mid:
                p = -1.0
        pos[i] = p
    return pos


def state(b):
    """Indicator state on the bid prices of a bar frame (as in MT5, charts show bid)."""
    return compute(*_ohlct(b))


def positions(b, rule, long_only=False, s=None):
    """Target position per bar (+1 long, -1 short, 0 flat) of one of RULES; pass s to reuse state(b)."""
    s = state(b) if s is None else s
    _, h, l, c, _ = _ohlct(b)
    if rule == "swing":
        pos = rule_swing_structure(s)
    elif rule == "internal":
        pos = rule_internal_structure(s)
    elif rule == "aligned":
        pos = rule_aligned_structure(s)
    elif rule == "order_block":
        pos = rule_order_block_retest(s, h, l, c, allow_short=not long_only)
    elif rule == "discount":
        pos = rule_discount_choch(s, c, allow_short=not long_only)
    else:
        raise ValueError(rule)
    return np.maximum(pos, 0.0) if long_only else pos


RULES = [  # (key, name)
    ("swing", "SMC Swing-Struktur"),
    ("internal", "SMC Interne Struktur"),
    ("aligned", "SMC Intern + Swing gleichgerichtet"),
    ("order_block", "SMC Order-Block-Retest"),
    ("discount", "SMC CHoCH im Discount/Premium"),
]
