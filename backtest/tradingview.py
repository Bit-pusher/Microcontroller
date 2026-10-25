"""Popular TradingView community scripts, tested like compare.py.

Each script's logic is translated from its published Pine source (copies on
GitHub, see SCRIPTS) with its default inputs. Signals become positions the way
the scripts' own strategy versions trade them: entering on a signal reverses
an open position. Same markets, costs and in-sample / out-of-sample windows as
backtest.py and compare.py; one variant is chosen on the mean in-sample Sharpe.

Lorentzian Classification is implemented here as well. Its Pine original picks
the training window from the chart's last bar, so the history shown on a chart
is not what was visible live. It is therefore computed in blocks of 2,000 bars,
each as a chart ending at the block's last bar; the training data always lies
before the bars being predicted.

usage: python3 tradingview.py      (after backtest.py and compare.py)
"""
import hashlib
import json
import math
import os

import numpy as np
import pandas as pd

import backtest as bt
import compare as cmp

NAN = np.nan


# ---------------------------------------------------------------- Pine helpers (index 0 = oldest bar, NaN = na)
def shift(x, k=1):
    out = np.full(len(x), NAN)
    out[k:] = x[:-k]
    return out


def sma(x, n):
    return pd.Series(x).rolling(n).mean().to_numpy()


def highest(x, n):
    return pd.Series(x).rolling(n, min_periods=1).max().to_numpy()


def lowest(x, n):
    return pd.Series(x).rolling(n, min_periods=1).min().to_numpy()


def stdev(x, n):
    return pd.Series(x).rolling(n).std(ddof=0).to_numpy()


def windows(x, n):
    return np.lib.stride_tricks.sliding_window_view(x, n)


def wma(x, n):
    out = np.full(len(x), NAN)
    if len(x) >= n:
        w = np.arange(1, n + 1, dtype=float)
        out[n - 1:] = windows(x, n) @ w / w.sum()
    return out


def linreg(x, n):
    """ta.linreg(x, n, 0): least squares line over the last n bars, value at the current bar."""
    out = np.full(len(x), NAN)
    if len(x) >= n:
        idx = np.arange(n, dtype=float)
        w = windows(x, n)
        slope = ((idx - idx.mean()) * (w - w.mean(axis=1, keepdims=True))).sum(axis=1) / ((idx - idx.mean()) ** 2).sum()
        out[n - 1:] = w.mean(axis=1) + slope * (n - 1 - idx.mean())
    return out


def _recursive(x, n, alpha):
    """ta.ema / ta.rma: seeded with the SMA of the first n values."""
    out = np.full(len(x), NAN)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) < n:
        return out
    start = valid[n - 1]
    out[start] = np.mean(x[valid[:n]])
    for i in range(start + 1, len(x)):
        out[i] = out[i - 1] if np.isnan(x[i]) else alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def ema(x, n):
    return _recursive(x, n, 2.0 / (n + 1))


def rma(x, n):
    return _recursive(x, n, 1.0 / n)


def true_range(h, l, c, first_bar=True):
    c1 = shift(c)
    tr = np.fmax(np.fmax(h - l, np.abs(h - c1)), np.abs(l - c1))
    tr[0] = h[0] - l[0] if first_bar else NAN   # ta.tr(true) vs ta.tr
    return tr


def atr(h, l, c, n):
    return rma(true_range(h, l, c), n)


def rsi(x, n):
    d = x - shift(x)
    up, dn = rma(np.where(np.isnan(d), NAN, np.maximum(d, 0)), n), rma(np.where(np.isnan(d), NAN, np.maximum(-d, 0)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / dn)))
    out[np.isnan(up) | np.isnan(dn)] = NAN
    return out


def crossover(a, b):
    with np.errstate(invalid="ignore"):
        return (a > b) & (shift(a) <= shift(b))


def crossunder(a, b):
    with np.errstate(invalid="ignore"):
        return (a < b) & (shift(a) >= shift(b))


def reverse_on(buy, sell):
    """strategy.entry semantics: a signal opens or reverses the position."""
    pos = np.zeros(len(buy))
    p = 0.0
    for i in range(len(buy)):
        if buy[i]:
            p = 1.0
        elif sell[i]:
            p = -1.0
        pos[i] = p
    return pos


def ohlc(b):
    return (b["bid_o"].to_numpy(float), b["bid_h"].to_numpy(float),
            b["bid_l"].to_numpy(float), b["bid_c"].to_numpy(float))


# ---------------------------------------------------------------- scripts
def ut_bot(b, key_value=1.0, atr_period=10):
    """UT Bot Alerts / UT Bot Strategy (QuantNomad): ATR trailing stop flip."""
    _, h, l, c = ohlc(b)
    n_loss = key_value * atr(h, l, c, atr_period)
    n = len(c)
    stop = np.full(n, NAN)
    pos = np.zeros(n)
    for i in range(n):
        prev = 0.0 if i == 0 or np.isnan(stop[i - 1]) else stop[i - 1]
        src, src1 = c[i], (c[i - 1] if i else NAN)
        if np.isnan(n_loss[i]):
            stop[i] = NAN
        elif src > prev and src1 > prev:
            stop[i] = max(prev, src - n_loss[i])
        elif src < prev and src1 < prev:
            stop[i] = min(prev, src + n_loss[i])
        elif src > prev:
            stop[i] = src - n_loss[i]
        else:
            stop[i] = src + n_loss[i]
        last = pos[i - 1] if i else 0.0
        pos[i] = 1.0 if src1 < prev and src > prev else -1.0 if src1 > prev and src < prev else last
    return pos


def chandelier_exit(b, length=22, mult=3.0):
    """Chandelier Exit (everget), close-based extremes."""
    _, h, l, c = ohlc(b)
    a = mult * atr(h, l, c, length)
    long_raw = highest(c, length) - a
    short_raw = lowest(c, length) + a
    n = len(c)
    long_stop, short_stop, pos = np.full(n, NAN), np.full(n, NAN), np.zeros(n)
    d = 1.0
    for i in range(n):
        lp = long_raw[i] if i == 0 or np.isnan(long_stop[i - 1]) else long_stop[i - 1]
        sp = short_raw[i] if i == 0 or np.isnan(short_stop[i - 1]) else short_stop[i - 1]
        c1 = c[i - 1] if i else NAN
        long_stop[i] = max(long_raw[i], lp) if c1 > lp and not np.isnan(long_raw[i]) else long_raw[i]
        short_stop[i] = min(short_raw[i], sp) if c1 < sp and not np.isnan(short_raw[i]) else short_raw[i]
        d = 1.0 if c[i] > sp else -1.0 if c[i] < lp else d
        pos[i] = d
    pos[np.isnan(a)] = 0.0
    return pos


def ssl_channel(b, length=10):
    """SSL Channel: close above the SMA of highs / below the SMA of lows."""
    _, h, l, c = ohlc(b)
    hi, lo = sma(h, length), sma(l, length)
    pos = np.zeros(len(c))
    p = 0.0
    for i in range(len(c)):
        p = 1.0 if c[i] > hi[i] else -1.0 if c[i] < lo[i] else p
        pos[i] = p
    return pos


def alpha_trend(b, coeff=1.0, period=14):
    """AlphaTrend (KivancOzbilgic) in its no-volume mode (RSI instead of MFI)."""
    _, h, l, c = ohlc(b)
    a = sma(true_range(h, l, c, first_bar=False), period)
    up_t, down_t = l - a * coeff, h + a * coeff
    bull = rsi(c, period) >= 50
    n = len(c)
    at = np.full(n, NAN)
    for i in range(n):
        prev = 0.0 if i == 0 or np.isnan(at[i - 1]) else at[i - 1]
        if bull[i]:
            at[i] = prev if up_t[i] < prev else up_t[i]
        else:
            at[i] = prev if down_t[i] > prev else down_t[i]
    at2 = shift(at, 2)
    buy, sell = crossover(at, at2), crossunder(at, at2)

    def bars_since(cond, lag):
        out = np.full(n, NAN)
        last = None
        for i in range(n):
            j = i - lag
            if j >= 0 and cond[j]:
                last = j
            if last is not None:
                out[i] = (i - lag) - last if lag else i - last
        return out
    k1, k2 = bars_since(buy, 0), bars_since(sell, 0)
    o1, o2 = bars_since(buy, 1), bars_since(sell, 1)
    with np.errstate(invalid="ignore"):
        return reverse_on(buy & (o1 > k2), sell & (o2 > k1))


def ott(b, length=2, percent=1.4):
    """Optimized Trend Tracker (KivancOzbilgic / Anil Ozeksi) with its default VAR average."""
    _, _, _, c = ohlc(b)
    n = len(c)
    c1 = shift(c)
    with np.errstate(invalid="ignore"):
        ud = np.where(c > c1, c - c1, 0.0)
        dd = np.where(c < c1, c1 - c, 0.0)
    s_ud, s_dd = pd.Series(ud).rolling(9).sum().to_numpy(), pd.Series(dd).rolling(9).sum().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        cmo = np.nan_to_num((s_ud - s_dd) / (s_ud + s_dd))
    alpha = 2.0 / (length + 1)
    mavg = np.zeros(n)
    for i in range(n):
        k = alpha * abs(cmo[i])
        mavg[i] = k * c[i] + (1 - k) * (mavg[i - 1] if i else 0.0)
    fark = mavg * percent * 0.01
    long_stop, short_stop, out = np.zeros(n), np.zeros(n), np.zeros(n)
    d = 1
    for i in range(n):
        ls, ss = mavg[i] - fark[i], mavg[i] + fark[i]
        lp = long_stop[i - 1] if i else ls
        sp = short_stop[i - 1] if i else ss
        long_stop[i] = max(ls, lp) if mavg[i] > lp else ls
        short_stop[i] = min(ss, sp) if mavg[i] < sp else ss
        d = 1 if d == -1 and mavg[i] > sp else -1 if d == 1 and mavg[i] < lp else d
        mt = long_stop[i] if d == 1 else short_stop[i]
        out[i] = mt * (200 + percent) / 200 if mavg[i] > mt else mt * (200 - percent) / 200
    ott2 = shift(out, 2)
    return reverse_on(crossover(mavg, ott2), crossunder(mavg, ott2))


def hull_suite(b, length=55):
    """Hull Suite (InSilico), strategy version by DashTrader: HMA above / below its value 2 bars ago."""
    _, _, _, c = ohlc(b)
    hull = wma(2 * wma(c, length // 2) - wma(c, length), int(round(math.sqrt(length))))
    with np.errstate(invalid="ignore"):
        return reverse_on(hull > shift(hull, 2), hull < shift(hull, 2))


def half_trend(b, amplitude=2):
    """HalfTrend (everget): trend state; the channel deviation only draws bands."""
    _, h, l, c = ohlc(b)
    n = len(c)
    high_price, low_price = highest(h, amplitude), lowest(l, amplitude)
    high_ma, low_ma = sma(h, amplitude), sma(l, amplitude)
    trend, next_trend = 0, 0
    max_low, min_high = l[0], h[0]
    pos = np.zeros(n)
    for i in range(n):
        prev_low = l[i - 1] if i else l[i]
        prev_high = h[i - 1] if i else h[i]
        if next_trend == 1:
            max_low = max(low_price[i], max_low)
            if high_ma[i] < max_low and c[i] < prev_low:
                trend, next_trend, min_high = 1, 0, high_price[i]
        else:
            min_high = min(high_price[i], min_high)
            if low_ma[i] > min_high and c[i] > prev_high:
                trend, next_trend, max_low = 0, 1, low_price[i]
        pos[i] = 1.0 if trend == 0 else -1.0
    return pos


def range_filter(b, period=100, mult=3.0):
    """Range Filter Buy and Sell 5min (guikroth, after DonovanWall)."""
    _, _, _, x = ohlc(b)
    n = len(x)
    rng = ema(ema(np.abs(x - shift(x)), period), period * 2 - 1) * mult
    filt = np.full(n, NAN)
    for i in range(n):
        prev = 0.0 if i == 0 or np.isnan(filt[i - 1]) else filt[i - 1]
        r = rng[i]
        if np.isnan(r):
            filt[i] = NAN
        elif x[i] > prev:
            filt[i] = prev if x[i] - r < prev else x[i] - r
        else:
            filt[i] = prev if x[i] + r > prev else x[i] + r
    up, down = np.zeros(n), np.zeros(n)
    f1 = shift(filt)
    for i in range(1, n):
        up[i] = up[i - 1] + 1 if filt[i] > f1[i] else 0 if filt[i] < f1[i] else up[i - 1]
        down[i] = down[i - 1] + 1 if filt[i] < f1[i] else 0 if filt[i] > f1[i] else down[i - 1]
    x1 = shift(x)
    with np.errstate(invalid="ignore"):
        long_cond = (x > filt) & (x != x1) & (up > 0) & ~np.isnan(x1)
        short_cond = (x < filt) & (x != x1) & (down > 0) & ~np.isnan(x1)
    cond_ini, prev_ini = np.full(n, NAN), NAN
    buy, sell = np.zeros(n, bool), np.zeros(n, bool)
    for i in range(n):
        cur = 1.0 if long_cond[i] else -1.0 if short_cond[i] else prev_ini
        buy[i] = long_cond[i] and prev_ini == -1
        sell[i] = short_cond[i] and prev_ini == 1
        cond_ini[i] = prev_ini = cur
    return reverse_on(buy, sell)


def squeeze_momentum(b, length=20, length_kc=20, mult_kc=1.5):
    """Squeeze Momentum Indicator (LazyBear): trade the squeeze release in the momentum's direction,
    exit when the momentum histogram crosses zero. As published, the BB width uses the KC factor."""
    _, h, l, c = ohlc(b)
    basis, dev = sma(c, length), mult_kc * stdev(c, length)
    ma = sma(c, length_kc)
    range_ma = sma(true_range(h, l, c, first_bar=False), length_kc)
    with np.errstate(invalid="ignore"):
        sqz_on = (basis - dev > ma - range_ma * mult_kc) & (basis + dev < ma + range_ma * mult_kc)
    val = linreg(c - ((highest(h, length_kc) + lowest(l, length_kc)) / 2 + sma(c, length_kc)) / 2, length_kc)
    pos = np.zeros(len(c))
    p = 0.0
    for i in range(1, len(c)):
        s = np.sign(val[i]) if not np.isnan(val[i]) else 0.0
        if p != 0 and s != p:
            p = 0.0
        if p == 0 and sqz_on[i - 1] and not sqz_on[i] and s != 0:
            p = s
        pos[i] = p
    return pos


def wavetrend(b, n1=10, n2=21, ob=53, os_=-53):
    """WaveTrend Oscillator (LazyBear): WT1/WT2 cross inside the overbought / oversold zone."""
    _, h, l, c = ohlc(b)
    ap = (h + l + c) / 3
    esa = ema(ap, n1)
    d = ema(np.abs(ap - esa), n1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ci = (ap - esa) / (0.015 * d)
    wt1 = ema(ci, n2)
    wt2 = sma(wt1, 4)
    with np.errstate(invalid="ignore"):
        return reverse_on(crossover(wt1, wt2) & (wt1 < os_), crossunder(wt1, wt2) & (wt1 > ob))


# ---------------------------------------------------------------- Lorentzian Classification
# Own implementation of jdehorty's "Machine Learning: Lorentzian Classification"
# (Pine, MPL-2.0) and its MLExtensions / KernelFunctions helpers, written after
# the parity-tested port by AI Edge and checked against TradingView exports
# (see check_lorentzian in the README). Default settings: 8 neighbours, 2,000
# bars back, features RSI 14, WT 10/11, CCI 20, ADX 20, RSI 9, volatility and
# regime filters, kernel filter (h 8, r 8, x 25), exits after 4 bars.
LC_NEIGHBORS, LC_MAX_BARS_BACK, LC_BLOCK = 8, 2000, 2000


def _lc_ema(x, n):
    """Pine ema as used by MLExtensions: SMA seed, na input leaves na."""
    out = np.full(len(x), NAN)
    a = 2.0 / (n + 1)
    for i in range(len(x)):
        if np.isnan(x[i]):
            continue
        if i > 0 and not np.isnan(out[i - 1]):
            out[i] = a * x[i] + (1 - a) * out[i - 1]
        elif i >= n - 1 and not np.isnan(x[i - n + 1:i + 1]).any():
            out[i] = x[i - n + 1:i + 1].mean()
    return out


def _lc_rma(x, n):
    out = np.full(len(x), NAN)
    a = 1.0 / n
    for i in range(len(x)):
        if np.isnan(x[i]):
            continue
        if i > 0 and not np.isnan(out[i - 1]):
            out[i] = a * x[i] + (1 - a) * out[i - 1]
        elif i >= n - 1 and not np.isnan(x[i - n + 1:i + 1]).any():
            out[i] = x[i - n + 1:i + 1].mean()
    return out


def _lc_normalize(x):
    """MLExtensions.normalize: running min/max since the first bar."""
    out = np.full(len(x), NAN)
    lo, hi = 1e11, -1e11
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        lo, hi = min(lo, v), max(hi, v)
        out[i] = (v - lo) / max(hi - lo, 1e-9)
    return out


def _lc_rsi(c, n):
    d = np.r_[NAN, np.diff(c)]
    gain = np.where(np.isnan(d), NAN, np.maximum(d, 0.0))
    loss = np.where(np.isnan(d), NAN, np.maximum(-d, 0.0))
    g, l_ = _lc_rma(gain, n), _lc_rma(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(l_ == 0, 100.0, 100.0 - 100.0 / (1.0 + g / l_))
    out[np.isnan(g) | np.isnan(l_)] = NAN
    return out


def _lc_features(o, h, l, c, price_scale=0.0):
    n = len(c)
    hlc3 = (h + l + c) / 3.0
    n_rsi = lambda length: _lc_ema(_lc_rsi(c, length), 1) / 100.0
    # WaveTrend
    e1 = _lc_ema(hlc3, 10)
    e2 = _lc_ema(np.abs(hlc3 - e1), 10)
    with np.errstate(divide="ignore", invalid="ignore"):
        ci = np.where(e2 != 0, (hlc3 - e1) / (0.015 * e2), 0.0)
    ci[np.isnan(e1) | np.isnan(e2)] = NAN
    wt1 = _lc_ema(ci, 11)
    wt = _lc_normalize(wt1 - sma(wt1, 4))
    # CCI
    avg = sma(c, 20)
    cci = np.full(n, NAN)
    for i in range(19, n):
        if not np.isnan(avg[i]):
            md = np.abs(c[i - 19:i + 1] - avg[i]).sum() / 20
            cci[i] = (c[i] - avg[i]) / (0.015 * md) if md != 0 else 0.0
    cci = _lc_normalize(_lc_ema(cci, 1))
    # ADX (prices quantised to the tick size, as Pine sees them)
    q = (lambda a, b: (np.round(a * price_scale) - np.round(b * price_scale)) / price_scale) if price_scale > 0 \
        else (lambda a, b: a - b)
    pc, ph, pl = np.r_[0.0, c[:-1]], np.r_[0.0, h[:-1]], np.r_[0.0, l[:-1]]
    tr = np.maximum(np.maximum(q(h, l), np.abs(q(h, pc))), np.abs(q(l, pc)))
    up, dn = q(h, ph), q(pl, l)
    dmp = np.where((up > dn) & (up > 0), up, 0.0)
    dmm = np.where((dn > up) & (dn > 0), dn, 0.0)

    def wilder(x, p):
        out = np.empty(n)
        for i in range(n):
            out[i] = x[i] if i == 0 else out[i - 1] - out[i - 1] / p + x[i]
        return out
    trs, ps, ms = wilder(tr, 20), wilder(dmp, 20), wilder(dmm, 20)
    with np.errstate(divide="ignore", invalid="ignore"):
        dip = np.where(trs != 0, ps / trs * 100, 0.0)
        dim = np.where(trs != 0, ms / trs * 100, 0.0)
        dx = np.where(dip + dim != 0, np.abs(dip - dim) / (dip + dim) * 100, 0.0)
    adx = _lc_rma(dx, 20) / 100.0
    return np.column_stack([n_rsi(14), wt, cci, adx, n_rsi(9)])


def _lc_kernel(src, weights):
    """Kernel regression over the last bars, summed in the same order as Pine's loop."""
    s, w = src.tolist(), weights.tolist()
    out = np.empty(len(s))
    for i in range(len(s)):
        cur = cum = 0.0
        for j in range(min(len(w), i + 1)):
            cur += s[i - j] * w[j]
            cum += w[j]
        out[i] = cur / cum if cum > 0 else s[i]
    return out


def _lc_prepare(o, h, l, c, price_scale=0.0):
    n = len(c)
    feats = _lc_features(o, h, l, c, price_scale)
    labels = np.zeros(n)
    labels[4:] = np.where(c[:-4] < c[4:], -1.0, np.where(c[:-4] > c[4:], 1.0, 0.0))
    j = np.arange(27, dtype=float)                       # 1 + startAtBar(25) + 1 terms
    yhat1 = _lc_kernel(c, (1.0 + j ** 2 / max(8.0 ** 2 * 2.0 * 8.0, 1e-10)) ** -8.0)
    # volatility filter: ATR(1) > ATR(10), true range with nz(close[1]) = 0 on the first bar
    pc = np.r_[0.0, c[:-1]]
    tr = np.maximum(np.maximum(h - l, np.abs(h - pc)), np.abs(l - pc))
    a1, a10 = _lc_rma(tr, 1), _lc_rma(tr, 10)
    vol = np.where(np.isnan(a1) | np.isnan(a10), True, a1 > a10)
    # regime filter (Kalman-like smoother of ohlc4)
    ohlc4 = (o + h + l + c) / 4.0
    v1, v2, kl = np.zeros(n), np.zeros(n), np.zeros(n)
    slope, ema_slope = np.zeros(n), np.zeros(n)
    v2[0], kl[0] = h[0] - l[0], ohlc4[0]
    for i in range(1, n):
        v1[i] = 0.2 * (ohlc4[i] - ohlc4[i - 1]) + 0.8 * v1[i - 1]
        v2[i] = 0.1 * (h[i] - l[i]) + 0.8 * v2[i - 1]
        om = abs(v1[i] / v2[i]) if v2[i] != 0 else 0.0
        al = (-(om ** 2) + math.sqrt(om ** 4 + 16.0 * om ** 2)) / 8.0
        kl[i] = al * ohlc4[i] + (1.0 - al) * kl[i - 1]
        slope[i] = abs(kl[i] - kl[i - 1])
        prev = ema_slope[i - 1]
        ema_slope[i] = slope[i] if prev == 0 and i < 200 else 2.0 / 201.0 * slope[i] + (1 - 2.0 / 201.0) * prev
    with np.errstate(divide="ignore", invalid="ignore"):
        regime = np.where(ema_slope != 0, (slope - ema_slope) / ema_slope >= -0.1, True)
    return feats, labels, yhat1, vol & regime


def _lc_predict(feats, labels, i, last_bar_index, state, full_history=False):
    """Approximate nearest neighbours with Lorentzian distance, as in the Pine loop."""
    size_loop = min(LC_MAX_BARS_BACK - 1, i)
    start = 0 if full_history else (last_bar_index - LC_MAX_BARS_BACK if last_bar_index >= LC_MAX_BARS_BACK else 0)
    idx = np.arange(start, size_loop + 1) if start <= size_loop else np.arange(start, size_loop - 1, -1)
    idx = idx[idx % 4 != 0]
    cur = feats[i]
    dist = np.zeros(len(idx))
    for f in range(5):
        dist += np.log(1.0 + np.abs(cur[f] - feats[idx, f]))
    dist[np.isnan(dist)] = -np.inf
    distances, predictions = state
    last = -1.0
    threshold_idx = round(LC_NEIGHBORS * 3.0 / 4.0)
    for d, lab in zip(dist.tolist(), labels[idx].tolist()):
        if d >= last:
            last = d
            distances.append(d)
            predictions.append(round(lab))
            if len(predictions) > LC_NEIGHBORS:
                last = distances[threshold_idx]
                distances.pop(0)
                predictions.pop(0)
    return int(sum(predictions))


def lorentzian_signals(prep, last_bar_index, full_history=False):
    """Pine signal logic for a chart whose last bar is last_bar_index."""
    feats, labels, yhat1, filt = prep
    n = last_bar_index + 1
    mbbi = last_bar_index - LC_MAX_BARS_BACK if last_bar_index >= LC_MAX_BARS_BACK else 0
    state = ([], [])
    prediction = np.zeros(n, int)
    direction = np.zeros(n, int)
    buy, sell, exit_buy, exit_sell = (np.zeros(n, bool) for _ in range(4))
    signal, bars_held = 0, 0
    for i in range(n):
        if i >= mbbi:
            prediction[i] = _lc_predict(feats, labels, i, last_bar_index, state, full_history)
        prev_signal = signal
        if prediction[i] > 0 and filt[i]:
            signal = 1
        elif prediction[i] < 0 and filt[i]:
            signal = -1
        direction[i] = signal
        changed = signal != prev_signal
        bars_held = 0 if changed else bars_held + 1
        held4, held_lt4 = bars_held == 4, 0 < bars_held < 4
        bullish = i >= 2 and yhat1[i - 1] < yhat1[i]
        bearish = i >= 2 and yhat1[i - 1] > yhat1[i]
        buy[i] = signal == 1 and changed and bullish
        sell[i] = signal == -1 and changed and bearish
        last_buy = i >= 4 and direction[i - 4] == 1
        last_sell = i >= 4 and direction[i - 4] == -1
        exit_buy[i] = ((held4 and last_buy) or (held_lt4 and sell[i] and last_buy)) and i >= 4 and buy[i - 4]
        exit_sell[i] = ((held4 and last_sell) or (held_lt4 and buy[i] and last_sell)) and i >= 4 and sell[i - 4]
    return {"prediction": prediction, "direction": direction, "buy": buy, "sell": sell,
            "exit_buy": exit_buy, "exit_sell": exit_sell}


def lorentzian(b):
    """Machine Learning: Lorentzian Classification (jdehorty), default settings.
    Each block of 2,000 bars is computed as a chart ending at the block's last bar."""
    prep = _lc_prepare(*ohlc(b))
    n = len(b)
    pos = np.zeros(n)
    end = n - 1
    while end >= 0:
        s = lorentzian_signals(prep, end)
        first = max(0, end - LC_BLOCK + 1)
        p = 0.0
        for i in range(max(0, end - LC_BLOCK), end + 1):
            if (p > 0 and s["exit_buy"][i]) or (p < 0 and s["exit_sell"][i]):
                p = 0.0
            if s["buy"][i]:
                p = 1.0
            elif s["sell"][i]:
                p = -1.0
            if i >= first:
                pos[i] = p
        end -= LC_BLOCK
    return pos


SCRIPTS = [  # (name, author, function, Pine source used)
    ("UT Bot Alerts", "QuantNomad", ut_bot,
     "https://github.com/sid-stefanescu/finscripts/blob/master/UT_Bot_Strategy_v4.0"),
    ("Chandelier Exit", "everget", chandelier_exit,
     "https://github.com/bnvnvnv/fmzstrategies/blob/master/Chandelier-Exit.md"),
    ("SSL Channel", "ErwinBeckers / everget", ssl_channel,
     "https://github.com/fmzquant/strategies/blob/master/SSL-Channel.md"),
    ("AlphaTrend", "KivancOzbilgic", alpha_trend,
     "https://github.com/fmzquant/strategies/blob/master/AlphaTrend.md"),
    ("Optimized Trend Tracker", "KivancOzbilgic", ott,
     "https://github.com/fmzquant/strategies/blob/master/Optimized-Trend-Tracker.md"),
    ("Hull Suite", "InSilico", hull_suite,
     "https://github.com/fmzquant/strategies/blob/master/Hull-Suite-Strategy.md"),
    ("HalfTrend", "everget", half_trend,
     "https://github.com/apurbapaul1998/HalfTrend-Indicator/blob/main/code"),
    ("Range Filter", "guikroth / DonovanWall", range_filter,
     "https://github.com/fmzquant/strategies/blob/master/Range-Filter-Buy-and-Sell.md"),
    ("Squeeze Momentum", "LazyBear", squeeze_momentum,
     "https://github.com/markshuang/PineScript/blob/master/Squeeze%20Momentum%20Indicator%5BLazyBear%5D"),
    ("WaveTrend Oscillator", "LazyBear", wavetrend,
     "https://github.com/czarcrab/tv-indicators-strategies/blob/master/WaveTrend%20Oscillator.tv"),
    ("Lorentzian Classification", "jdehorty", lorentzian,
     "https://github.com/artificial-intelligence-edge/lorentzian-classification"),
]


def market_bars(market, tf):
    if tf == "D1":
        return cmp.daily_bars(market)
    if market == "SPY":
        return bt.load_bars("SPY_H1", 1)
    return bt.load_bars(cmp.MARKETS[market][0], 4)


def positions_cached(name, fn, market, tf, b):
    os.makedirs(bt.CACHE, exist_ok=True)
    digest = hashlib.md5(pd.util.hash_pandas_object(b[["time", "bid_o", "bid_h", "bid_l", "bid_c"]], index=False)
                         .to_numpy().tobytes() + open(__file__, "rb").read()).hexdigest()[:12]
    path = os.path.join(bt.CACHE, f"tv_{name.replace(' ', '_')}_{market}_{tf.replace('/', '-')}_{digest}.npy")
    if os.path.exists(path):
        return np.load(path)
    pos = fn(b)
    np.save(path, pos)
    return pos


def main():
    win, _ = cmp.windows()
    rows = []
    for name, author, fn, source in SCRIPTS:
        for tf in ("H4/H1", "D1"):
            bars_by_market = {m: market_bars(m, tf) for m in cmp.MARKETS}
            base = {m: positions_cached(name, fn, m, tf, b) for m, b in bars_by_market.items()}
            for side in ("Long+Short", "nur Long"):
                pos = base if side == "Long+Short" else {m: np.maximum(p, 0.0) for m, p in base.items()}
                r = cmp.evaluate(pos, bars_by_market, win)
                r.update({"name": f"{name} ({tf}, {side})", "script": name, "author": author, "tf": tf,
                          "side": side, "source": source})
                rows.append(r)
                print(f"{r['name']:48s} IS {r['is_mean_sharpe']:5.2f}  OOS {r['oos_mean_sharpe']:5.2f}  "
                      f"portfolio OOS {r['oos_portfolio']['sharpe']:5.2f} (t {r['oos_portfolio']['t']:4.1f})  "
                      + " ".join(f"{m} {r['oos'][m]['sharpe']:5.2f}" for m in cmp.MARKETS), flush=True)
    ranked = sorted(rows, key=lambda x: x["is_mean_sharpe"], reverse=True)
    best = ranked[0]
    rank_corr = float(pd.Series([x["is_mean_sharpe"] for x in rows]).rank()
                      .corr(pd.Series([x["oos_mean_sharpe"] for x in rows]).rank()))
    print(f"\nchosen in-sample: {best['name']}  IS {best['is_mean_sharpe']:.2f}  OOS {best['oos_mean_sharpe']:.2f}  "
          f"portfolio OOS Sharpe {best['oos_portfolio']['sharpe']:.2f} (t {best['oos_portfolio']['t']:.1f})")
    print(f"rank correlation IS/OOS over {len(rows)} variants: {rank_corr:.2f}")
    with open(os.path.join(bt.RESULTS, "tradingview.json"), "w") as f:
        json.dump({"variants": ranked, "chosen": best["name"], "rank_corr": rank_corr}, f, indent=1, default=float)


if __name__ == "__main__":
    main()
