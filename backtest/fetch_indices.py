"""Minute data of US index CFDs for dridr.py: S&P 500, Nasdaq 100, Russell 2000 (Oanda, 2005-2020).

FutureSharks/financial-data commits Oanda 1-minute candles (UTC, midpoint
prices, tick count as volume) as monthly CSV files. This script makes a sparse,
blob-filtered clone of only those three folders (data, no code is used) and
writes 5-minute bars to data/indices/<SYMBOL>_M5.csv: time (UTC seconds, bar
start), open, high, low, close, ticks. Minutes without a price change are
missing from the source; a 5-minute bar exists when any of its minutes does.

usage: python3 fetch_indices.py [path of an existing clone]
"""
import glob
import os
import subprocess
import sys

import pandas as pd

REPO = "https://github.com/FutureSharks/financial-data"
SYMBOLS = ["SPX500_USD", "NAS100_USD", "US2000_USD"]
FOLDER = "pyfinancialdata/data/currencies/oanda"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data", "indices")


def clone(path):
    if os.path.exists(path):
        return                                  # an existing checkout holding the three folders
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO, path], check=True,
                   env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"})
    subprocess.run(["git", "-C", path, "sparse-checkout", "set", *(f"{FOLDER}/{s}" for s in SYMBOLS)], check=True)


def build(path, symbol):
    files = glob.glob(os.path.join(path, FOLDER, symbol, "*", "*.csv"))
    m1 = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    m1["time"] = pd.to_datetime(m1["time"], utc=True)
    m1 = m1.drop_duplicates("time").sort_values("time").set_index("time")
    m5 = m1.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])
    m5 = m5.rename(columns={"volume": "ticks"})
    m5.insert(0, "time", (m5.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1))
    return m5.reset_index(drop=True)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "financial-data")
    clone(path)
    os.makedirs(OUT_DIR, exist_ok=True)
    for symbol in SYMBOLS:
        out = os.path.join(OUT_DIR, f"{symbol}_M5.csv")
        m5 = build(path, symbol)
        m5.to_csv(out, index=False)
        first, last = (pd.to_datetime(m5["time"].iloc[k], unit="s").date() for k in (0, -1))
        print(f"{symbol}: {len(m5)} bars {first} .. {last}")


if __name__ == "__main__":
    main()
