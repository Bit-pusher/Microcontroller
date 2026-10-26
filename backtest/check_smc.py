"""Check smc.py against what LuxAlgo's Smart Money Concepts drew on TradingView.

The parity test bench of the MQL5 port in GeneralTradingSarl/Smart-Money-Concepts
publishes a TradingView export (parity/tv_A.json): 5,044 AAPL 15-minute bars,
the original Pine script run on them with its default inputs (plus coloured
candles, so the internal trend of every bar is exported), and every label,
line and box the script drew. This script downloads that data file into
cache/ and compares it object by object with smc.compute(). Only data is
downloaded, no code.

usage: python3 check_smc.py
"""
import json
import os
import urllib.request
from collections import Counter

import numpy as np

import backtest as bt
import smc

URL = "https://raw.githubusercontent.com/GeneralTradingSarl/Smart-Money-Concepts/main/parity/tv_A.json"
GREEN, RED = "089981", "F23645"                   # swing bullish / bearish colour of the original
OB_BULL, OB_BEAR = "3179F5", "F77C80"             # internal order block colours
INTERNAL_OBS_SHOWN = 5


def abgr_to_rgb(v):
    """TradingView stores colours as 0xAABBGGRR."""
    return None if v is None else "%02X%02X%02X" % (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)


def price(v):
    return None if v is None else round(float(v), 6)


def load():
    path = os.path.join(bt.CACHE, "smc_tv_A.json")
    if not os.path.exists(path):
        os.makedirs(bt.CACHE, exist_ok=True)
        urllib.request.urlretrieve(URL, path)
    with open(path) as f:
        return json.load(f)


def tradingview_objects(d):
    """Drawn objects as comparable tuples; x coordinates map through d['indexes'] to bar times."""
    times = {b[0]: b[1] for b in d["chartBars"]}
    last = max(times)

    def when(x):
        i = d["indexes"][x]
        return "future" if i > last else times[i]

    out = {k: Counter() for k in ("structure lines", "structure labels", "equal lines", "equal labels",
                                  "strong/weak", "order blocks")}
    for ln in d["lines"]:
        if ln.get("y1") is None:
            continue                                   # placeholders of the `var line` declarations
        key = (when(ln["x1"]), price(ln["y1"]), when(ln["x2"]), price(ln["y2"]), abgr_to_rgb(ln["ci"]), ln["st"])
        if key[2] == "future":
            out["strong/weak"][("line",) + key[:2]] += 1
        elif ln["st"] == "dot":
            out["equal lines"][key] += 1
        else:
            out["structure lines"][key] += 1
    for lb in d["labels"]:
        if lb.get("y") is None:
            continue
        key = (lb["t"], when(lb["x"]), price(lb["y"]), abgr_to_rgb(lb["tci"]), lb["st"])
        if lb["t"] in ("EQH", "EQL"):
            out["equal labels"][key] += 1
        elif lb["t"] in ("BOS", "CHoCH"):
            out["structure labels"][key] += 1
        else:
            out["strong/weak"][("label", lb["t"], price(lb["y"]))] += 1
    for bx in d["boxes"]:
        if bx.get("y1") is None:
            continue
        out["order blocks"][(when(bx["x1"]), price(bx["y1"]), price(bx["y2"]), abgr_to_rgb(bx["bc"]))] += 1
    candles = np.array([abgr_to_rgb(b[6]) == GREEN for b in d["studyBars"]])
    return out, candles


def port_objects(d):
    bars = np.array([b[1:6] for b in d["chartBars"]], float)
    t = bars[:, 0].astype(np.int64)
    s = smc.compute(bars[:, 1], bars[:, 2], bars[:, 3], bars[:, 4], t)
    out = {k: Counter() for k in ("structure lines", "structure labels", "equal lines", "equal labels",
                                  "strong/weak", "order blocks")}
    colour = {smc.BULLISH: GREEN, smc.BEARISH: RED}
    for t1, y, t2, style, bias in s["lines"]:
        out["structure lines"][(int(t1), price(y), int(t2), price(y), colour[bias], style)] += 1
    for text, idx, y, style in s["labels"]:
        out["structure labels"][(text, int(t[idx]), price(y), GREEN if style == "ldn" else RED, style)] += 1
    for t1, y1, t2, y2, tag in s["eq_lines"]:
        out["equal lines"][(int(t1), price(y1), int(t2), price(y2), RED if tag == "EQH" else GREEN, "dot")] += 1
    for tag, idx, y in s["eq_labels"]:
        out["equal labels"][(tag, int(t[idx]), price(y), RED if tag == "EQH" else GREEN,
                             "ldn" if tag == "EQH" else "lup")] += 1
    tr = s["trailing"]
    out["strong/weak"][("line", int(tr["top_time"]), price(tr["top"]))] += 1
    out["strong/weak"][("line", int(tr["bottom_time"]), price(tr["bottom"]))] += 1
    out["strong/weak"][("label", "Strong High" if s["swing_trend"] == smc.BEARISH else "Weak High", price(tr["top"]))] += 1
    out["strong/weak"][("label", "Strong Low" if s["swing_trend"] == smc.BULLISH else "Weak Low", price(tr["bottom"]))] += 1
    for ob in s["internal_obs"][:INTERNAL_OBS_SHOWN]:
        out["order blocks"][(int(ob["time"]), price(ob["high"]), price(ob["low"]),
                             OB_BULL if ob["bias"] == smc.BULLISH else OB_BEAR)] += 1
    return out, s["bias_before"] == smc.BULLISH


def main():
    d = load()
    tv, tv_candles = tradingview_objects(d)
    port, port_candles = port_objects(d)
    ok = True
    for kind in tv:
        missing, extra = tv[kind] - port[kind], port[kind] - tv[kind]
        same = sum((tv[kind] & port[kind]).values())
        print(f"{kind:17s} TradingView {sum(tv[kind].values()):4d}  port {sum(port[kind].values()):4d}  identical {same:4d}")
        for k in list(missing)[:5]:
            print("   only TradingView:", k)
        for k in list(extra)[:5]:
            print("   only port:       ", k)
        ok &= not missing and not extra
    diff = np.flatnonzero(tv_candles != port_candles)
    print(f"candle colours    {len(tv_candles)} bars, {len(diff)} differ" + (f" (first at bar {diff[0]})" if len(diff) else ""))
    ok &= not len(diff)
    print("ALL IDENTICAL" if ok else "DIFFERENCES FOUND")


if __name__ == "__main__":
    main()
