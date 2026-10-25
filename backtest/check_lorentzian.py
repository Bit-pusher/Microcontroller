"""Check the Lorentzian Classification implementation against TradingView exports.

The AI Edge port repository publishes CSV exports of the original Pine
indicator (features, kernel estimate, prediction, direction, buy and sell
signals). This script downloads those data files into cache/ and compares them
bar by bar with tradingview.py. Only data is downloaded, no code.

usage: python3 check_lorentzian.py
"""
import os
import urllib.request

import numpy as np
import pandas as pd

import backtest as bt
import tradingview as tv

BASE = ("https://raw.githubusercontent.com/artificial-intelligence-edge/lorentzian-classification/"
        "main/tests/parity/baselines/")
EXPORTS = [  # (file, Pine "Include Full History" setting of the export)
    ("pine_coinbase_btcusd_1d_limited_history.csv", False),
    ("pine_btcusd_h1_trimmed_limited_history.csv", False),
    ("pine_oanda_eurusd_1d_full_history.csv", True),
    ("pine_tastyfx_eurusd_1d_full_history.csv", True),
]
FEATURES = ["F1_RSI", "F2_WT", "F3_CCI", "F4_ADX", "F5_RSI9"]


def tick_scale(raw):
    """Pine rounds prices to the symbol's tick; the export's decimals give it."""
    dec = 0
    for col in ("open", "high", "low", "close"):
        for s in raw[col].dropna():
            if "." in s:
                dec = max(dec, len(s.split(".", 1)[1].rstrip("0")))
    return float(10 ** dec) if dec else 0.0


def check(name, full_history):
    path = os.path.join(bt.CACHE, name)
    if not os.path.exists(path):
        os.makedirs(bt.CACHE, exist_ok=True)
        with urllib.request.urlopen(BASE + name, timeout=120) as resp, open(path, "wb") as f:
            f.write(resp.read())
    raw, d = pd.read_csv(path, dtype=str), pd.read_csv(path)
    o, h, l, c = (d[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    prep = tv._lc_prepare(o, h, l, c, tick_scale(raw))
    sig = tv.lorentzian_signals(prep, len(d) - 1, full_history)
    feats, _, kernel, _ = prep
    worst = 0.0
    for k, col in enumerate(FEATURES + ["Kernel Regression Estimate"]):
        ref = d[col].to_numpy(float) if col in d else np.full(len(d), np.nan)
        ok = ~np.isnan(ref)
        mine = feats[:, k] if k < len(FEATURES) else kernel
        if ok.any():
            worst = max(worst, float(np.max(np.abs(mine[ok] - ref[ok]) / np.maximum(1.0, np.abs(ref[ok])))))
    bad = {
        "prediction": int((sig["prediction"] != d["Prediction"].to_numpy()).sum()),
        "direction": int((sig["direction"] != d["Direction"].to_numpy()).sum()),
        "buy": int((sig["buy"] != d["Buy"].notna().to_numpy()).sum()),
        "sell": int((sig["sell"] != d["Sell"].notna().to_numpy()).sum()),
    }
    print(f"{name}: {len(d)} bars, {int(sig['buy'].sum())} buys, {int(sig['sell'].sum())} sells, "
          f"feature/kernel max rel. diff {worst:.1e}, mismatches {bad}")
    return worst < 1e-9 and not any(bad.values())


if __name__ == "__main__":
    results = [check(name, full) for name, full in EXPORTS]
    print("all exports match" if all(results) else "MISMATCH")
