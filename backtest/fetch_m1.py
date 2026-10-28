"""Minute data for scalping.py: Oanda CFDs (EURUSD, GBPUSD, gold, S&P 500, Nasdaq 100, Russell 2000; 2005 to
May 2020, midpoint prices) and Bitstamp BTCUSD (2012 to January 2018, trade prices).

Same source and method as fetch_indices.py (FutureSharks/financial-data, a blob-filtered clone that checks out
only the needed folders; data, no code is used). Writes data/m1/<SYMBOL>_M1.csv.gz: time (UTC seconds, bar
start), open, high, low, close, ticks. Oanda leaves out minutes without a price change. Bitstamp lists every
minute and repeats the last price in minutes without trades; those flat minutes are left out here as well
(Bitstamp has no tick count, ticks stays empty).

usage: python3 fetch_m1.py [path of an existing clone]
"""
import glob
import os
import subprocess
import sys

import pandas as pd

import fetch_indices as fi

OANDA = ["EUR_USD", "GBP_USD", "XAU_USD", "SPX500_USD", "NAS100_USD", "US2000_USD"]
BITSTAMP = "pyfinancialdata/data/cryptocurrencies/bitstamp/BTC_USD"
OUT_DIR = os.path.join(fi.HERE, "data", "m1")


def bitstamp(path):
    files = sorted(glob.glob(os.path.join(path, BITSTAMP, "*.csv")))
    m1 = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    m1["time"] = pd.to_datetime(m1["date"], utc=True)
    m1 = m1.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    flat = (m1["open"] == m1["high"]) & (m1["low"] == m1["close"]) & (m1["open"] == m1["close"]) \
        & (m1["close"] == m1["close"].shift())
    m1 = m1[~flat]
    times = (m1["time"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    return pd.DataFrame({"time": times, "open": m1["open"], "high": m1["high"], "low": m1["low"],
                         "close": m1["close"], "ticks": pd.NA}).reset_index(drop=True), float(flat.mean())


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(fi.HERE, "data", "financial-data")
    if not os.path.exists(path):
        fi.clone(path)
    folders = [f"{fi.FOLDER}/{s}" for s in OANDA] + [BITSTAMP]
    subprocess.run(["git", "-C", path, "sparse-checkout", "add", *folders], check=False)   # only if sparse
    subprocess.run(["git", "-C", path, "checkout", "HEAD", "--", *folders], check=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    jobs = [(s.replace("_", ""), lambda s=s: (fi.build(path, s, minutes=1), None)) for s in OANDA]
    jobs.append(("BTCUSD", lambda: bitstamp(path)))
    for symbol, build in jobs:
        m1, flat = build()
        out = os.path.join(OUT_DIR, f"{symbol}_M1.csv.gz")
        m1.to_csv(out, index=False)
        first, last = (pd.to_datetime(m1["time"].iloc[k], unit="s").date() for k in (0, -1))
        note = "" if flat is None else f", {flat:.1%} flat minutes left out"
        print(f"{symbol}: {len(m1)} bars {first} .. {last}{note} -> {out}", flush=True)


if __name__ == "__main__":
    main()
