"""Download real hourly/daily market data from the QuantConnect Lean repository.

Lean ships sample data (Oanda bid/ask quote bars for FX and CFDs, trade bars
for US equities) under Data/. This script converts it to one CSV per market:
time (unix seconds), bid_o, bid_h, bid_l, bid_c, ask_o, ask_h, ask_l, ask_c.
Equity data has no quotes, so bid == ask == trade price there.
"""
import csv
import io
import os
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

BASE = "https://raw.githubusercontent.com/QuantConnect/Lean/master/Data/"
MARKETS = {
    "EURUSD_H1": ("forex/oanda/hour/eurusd.zip", "quote"),
    "NZDUSD_H1": ("forex/oanda/hour/nzdusd.zip", "quote"),
    "XAUUSD_H1": ("cfd/oanda/hour/xauusd.zip", "quote"),
    "SPY_H1": ("equity/usa/hour/spy.zip", "trade"),
    "SPY_D1": ("equity/usa/daily/spy.zip", "trade"),
}
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def parse_time(s):
    return int(datetime.strptime(s, "%Y%m%d %H:%M").replace(tzinfo=timezone.utc).timestamp())


def convert(raw, kind):
    rows = []
    for rec in csv.reader(io.StringIO(raw)):
        if not rec:
            continue
        t = parse_time(rec[0])
        if kind == "quote":   # time, bid OHLC, bid size, ask OHLC, ask size
            bid = [float(v) for v in rec[1:5]]
            ask = [float(v) for v in rec[6:10]]
        else:                 # time, OHLC in 1/10000 dollars, volume
            bid = ask = [float(v) / 10000.0 for v in rec[1:5]]
        rows.append([t, *bid, *ask])
    return rows


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, (path, kind) in MARKETS.items():
        out = os.path.join(OUT_DIR, name + ".csv")
        if os.path.exists(out) and "--force" not in sys.argv:
            print(f"{name}: exists")
            continue
        with urllib.request.urlopen(BASE + path, timeout=120) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            raw = zf.read(zf.namelist()[0]).decode("ascii")
        rows = convert(raw, kind)
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "bid_o", "bid_h", "bid_l", "bid_c", "ask_o", "ask_h", "ask_l", "ask_c"])
            w.writerows(rows)
        first = datetime.fromtimestamp(rows[0][0], timezone.utc).date()
        last = datetime.fromtimestamp(rows[-1][0], timezone.utc).date()
        print(f"{name}: {len(rows)} bars {first} .. {last}")


if __name__ == "__main__":
    main()
