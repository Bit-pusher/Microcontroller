"""Compare the expert advisor's rules with the backtest: ScalpingVideoEA/ScalpingCore.mqh, compiled as C++
(harness/ea_runner.cpp, simulated fills like scalping.py), against scalping.py on the same minute bars, for all
13 variants of scalping_test.py. Every trade must agree in entry and exit bar, prices and exit reason.

usage: python3 check_ea.py [SYMBOL [FROM [TO]]]      e.g. python3 check_ea.py EURUSD 2015-01-01 2017-01-01
"""
import os
import subprocess
import sys

import numpy as np
import pandas as pd

import backtest as bt
import scalping as sc
import scalping_test as st

HARNESS = os.path.join(sc.HERE, "harness")
RUNNER = os.path.join(bt.CACHE, "ea_runner")
ARGS = {   # variant of scalping_test.py: strategy, timeframe, Tokyo window, RSI 70/30 rule, EMA filter
    "Tokio-Ausbruch, Spanne 19-04 NY (5m)": (1, 5, 0, 1, 1),
    "Tokio-Ausbruch, Spanne 20-03 NY (5m)": (1, 5, 1, 1, 1),
    "Box-Ausbruch (1m)": (2, 1, 0, 1, 1),
    "Box-Ausbruch (5m)": (2, 5, 0, 1, 1),
    "RSI-Divergenz mit 70/30-Regel (1m)": (3, 1, 0, 1, 1),
    "RSI-Divergenz ohne 70/30-Regel (1m)": (3, 1, 0, 0, 1),
    "RSI-Divergenz mit 70/30-Regel (5m)": (3, 5, 0, 1, 1),
    "RSI-Divergenz ohne 70/30-Regel (5m)": (3, 5, 0, 0, 1),
    "Fibonacci-Rücksetzer mit EMA 200 (1m)": (4, 1, 0, 1, 1),
    "Fibonacci-Rücksetzer ohne Filter (1m)": (4, 1, 0, 1, 0),
    "Fibonacci-Rücksetzer mit EMA 200 (5m)": (4, 5, 0, 1, 1),
    "Fibonacci-Rücksetzer ohne Filter (5m)": (4, 5, 0, 1, 0),
    "Tagesplan des Videos (Tokio + Fibonacci + RSI)": (0, 1, 0, 1, 0),
}
COLS = ["kind", "side", "entry_i", "entry", "stop", "target", "exit_i", "exit", "reason"]


def build():
    src = [os.path.join(HARNESS, f) for f in ("ea_runner.cpp", "ea_shim.h")] + \
          [os.path.join(sc.HERE, "..", "ScalpingVideoEA", "ScalpingCore.mqh")]
    if os.path.exists(RUNNER) and all(os.path.getmtime(RUNNER) > os.path.getmtime(f) for f in src):
        return
    os.makedirs(bt.CACHE, exist_ok=True)
    subprocess.run(["g++", "-O2", "-std=c++17", "-ffp-contract=off", "-o", RUNNER, src[0]], check=True)


def python_trades(m1, tf, name):
    t = st.VARIANTS[name](m1, tf)
    return pd.DataFrame(t, columns=COLS).sort_values(["entry_i", "kind"]).reset_index(drop=True)


def ea_trades(csv, name):
    out = subprocess.run([RUNNER, *map(str, ARGS[name])], stdin=open(csv), capture_output=True, text=True, check=True)
    lines = out.stdout.strip().split("\n")
    rows = [line.split(",") for line in lines[1:] if line]
    df = pd.DataFrame(rows, columns=COLS)
    for c in ("side", "entry_i", "exit_i"):
        df[c] = df[c].astype(int)
    for c in ("entry", "stop", "target", "exit"):
        df[c] = df[c].astype(float)
    return df.sort_values(["entry_i", "kind"]).reset_index(drop=True)


def compare(a, b):
    """Number of trades in a and b and the first rows that differ."""
    keys = ["kind", "side", "entry_i", "exit_i", "reason"]
    if len(a) == len(b) and (a[keys].to_numpy() == b[keys].to_numpy()).all():
        num = ["entry", "stop", "target", "exit"]
        close = np.isclose(a[num].to_numpy(float), b[num].to_numpy(float), rtol=1e-9, atol=0)
        bad = np.flatnonzero(~close.all(axis=1))
        return bad[:5]
    m = a.merge(b, on=["kind", "entry_i"], how="outer", suffixes=("_py", "_ea"), indicator=True)
    bad = m[(m["_merge"] != "both") | (m["exit_i_py"] != m["exit_i_ea"]) | (m["side_py"] != m["side_ea"])]
    return bad.head(5)


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    m = sc.load(symbol)
    if len(sys.argv) > 2:
        t = pd.to_datetime(m["time"], unit="s", utc=True)
        keep = t >= pd.Timestamp(sys.argv[2], tz="UTC")
        if len(sys.argv) > 3:
            keep &= t < pd.Timestamp(sys.argv[3], tz="UTC")
        m = m[keep].reset_index(drop=True)
    build()
    csv = os.path.join(bt.CACHE, f"ea_bars_{symbol}.csv")
    m[["time", "open", "high", "low", "close"]].to_csv(csv, index=False, float_format="%.10g")
    m = sc.prepare(pd.read_csv(csv))                  # the runner reads the same rounded prices
    m1 = sc.M1(m)
    tf = {}
    for minutes in (1, 5):
        b = sc.Bars(m, m1, minutes)
        tf[minutes] = {"b": b, "rsi": sc.rsi(b.c), "ema": sc.ema(b.c), "sw": sc.zigzag(b.h, b.l, sc.SWING_ATR * sc.atr(b))}
    print(f"{symbol}: {len(m)} bars")
    ok = True
    for name in ARGS:
        py, ea = python_trades(m1, tf, name), ea_trades(csv, name)
        bad = compare(py, ea)
        same = len(bad) == 0
        ok &= same
        print(f"{'ok  ' if same else 'FAIL'} {name}: {len(py)} trades in Python, {len(ea)} in the EA core", flush=True)
        if not same:
            print(bad.to_string() if isinstance(bad, pd.DataFrame) else pd.concat(
                [py.iloc[bad], ea.iloc[bad]], keys=["python", "ea"]).to_string())
    print("ALL VARIANTS IDENTICAL" if ok else "DIFFERENCES FOUND")


if __name__ == "__main__":
    main()
