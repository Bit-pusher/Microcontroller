"""Download Binance spot candles (via the static-klines mirror on GitHub) for crypto.py.

static-klines commits Binance klines to its repository in calendar windows
(.klines-cache/<SYMBOL>/<interval>/<start>.json). This script stitches the
windows into data/crypto/<SYMBOL>_<interval>.csv in the same column layout as
fetch_data.py. Binance publishes trade prices only, so bid == ask; crypto.py
charges trading costs per side instead of a spread.
"""
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

BASE = "https://raw.githubusercontent.com/finom/static-klines/main/.klines-cache/"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "crypto")


def window_starts(interval, today):
    """Calendar windows used by static-klines: 4h per quarter from 2017-07, 1d per two years from 2016."""
    out = []
    if interval == "4h":
        y, m = 2017, 7
        while date(y, m, 1) <= today:
            out.append(date(y, m, 1))
            m += 3
            if m > 12:
                y, m = y + 1, m - 12
    elif interval == "1d":
        y = 2016
        while date(y, 1, 1) <= today:
            out.append(date(y, 1, 1))
            y += 2
    else:
        raise ValueError(interval)
    return out


def fetch(symbol, interval, today):
    rows = {}
    for start in window_starts(interval, today):
        url = f"{BASE}{symbol}/{interval}/{start.isoformat()}.json"
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                klines = json.load(resp)
        except urllib.error.HTTPError as err:
            if err.code == 404:     # window not published (yet)
                continue
            raise
        for k in klines:            # [open time ms, open, high, low, close, volume, ...]
            o, h, l, c = (float(v) for v in k[1:5])
            rows[int(k[0]) // 1000] = [o, h, l, c, o, h, l, c]
    return [[t, *rows[t]] for t in sorted(rows)]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    for symbol in SYMBOLS:
        for interval in ("4h", "1d"):
            out = os.path.join(OUT_DIR, f"{symbol}_{interval}.csv")
            if os.path.exists(out) and "--force" not in sys.argv:
                print(f"{symbol} {interval}: exists")
                continue
            rows = fetch(symbol, interval, today)
            with open(out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["time", "bid_o", "bid_h", "bid_l", "bid_c", "ask_o", "ask_h", "ask_l", "ask_c"])
                w.writerows(rows)
            first = datetime.fromtimestamp(rows[0][0], timezone.utc).date()
            last = datetime.fromtimestamp(rows[-1][0], timezone.utc).date()
            print(f"{symbol} {interval}: {len(rows)} bars {first} .. {last}")


if __name__ == "__main__":
    main()
