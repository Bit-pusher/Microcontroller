"""Minute data of EURUSD and GBPUSD for scalping.py (Oanda, 2005 to May 2020, midpoint prices).

Same source and method as fetch_indices.py (FutureSharks/financial-data, a
sparse clone of only the needed folders; data, no code is used). Writes
data/fx/<SYMBOL>_M1.csv.gz: time (UTC seconds, bar start), open, high, low,
close, ticks. Minutes without a price change are missing from the source.

usage: python3 fetch_fx_m1.py [path of an existing clone]
"""
import os
import subprocess
import sys

import pandas as pd

import fetch_indices as fi

SYMBOLS = ["EUR_USD", "GBP_USD"]
OUT_DIR = os.path.join(fi.HERE, "data", "fx")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(fi.HERE, "data", "financial-data")
    if not os.path.exists(path):
        fi.clone(path)
    subprocess.run(["git", "-C", path, "checkout", "HEAD", "--", *(f"{fi.FOLDER}/{s}" for s in SYMBOLS)], check=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    for symbol in SYMBOLS:
        m1 = fi.build(path, symbol, minutes=1)
        out = os.path.join(OUT_DIR, f"{symbol.replace('_', '')}_M1.csv.gz")
        m1.to_csv(out, index=False)
        first, last = (pd.to_datetime(m1["time"].iloc[k], unit="s").date() for k in (0, -1))
        print(f"{symbol}: {len(m1)} bars {first} .. {last} -> {out}")


if __name__ == "__main__":
    main()
