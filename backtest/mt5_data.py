"""Read the export of mt5/HistoryExport.mq5 into the bar format of the backtests.

The export is in broker server time. IC Markets, like most MT5 brokers, runs its
server on New York time + 7 hours (UTC+2, during US summer time UTC+3), so that
the trading day ends at 17:00 New York = 00:00 server. check_clock() tests this
on the data instead of trusting it: the week has to open at about 17:00 New
York on Sunday, and on US index CFDs the cash open at 09:30 New York has to be
the strongest rise in quote updates per minute.

M1 bars carry bid prices and the smallest spread of the minute; ask prices are
bid + that spread, a lower bound of the real ask.

usage: python3 -I mt5_data.py <export folder> [symbol ...]
   e.g. data/mt5_export/ICMarketsSC-MT5-2; writes data/mt5/<symbol>_H1.csv
   (time UTC, bid / ask OHLC, like fetch_data.py) and <symbol>_M5.csv (time
   UTC, bid OHLC, ticks, spread in price units, for dridr.py)
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "data", "mt5")
NY_OFFSET_HOURS = 7                 # server time = New York time + 7 h
US_INDICES = ("US500", "USTEC", "US30", "US2000")


def server_to_utc(seconds):
    """Server times (seconds since 1970) to UTC seconds, for a server on New York time + 7 h. In the hour
    New York repeats in autumn the summer offset is taken; that hour is a Sunday night with no trading."""
    ny = pd.to_datetime(np.asarray(seconds, dtype="int64"), unit="s") - pd.Timedelta(hours=NY_OFFSET_HOURS)
    utc = ny.tz_localize("America/New_York", ambiguous=np.ones(len(ny), bool),
                         nonexistent="shift_forward").tz_convert("UTC")
    return np.asarray((utc - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1), dtype="int64")


def read_specs(folder):
    return pd.read_csv(os.path.join(folder, "symbols.csv"), sep=";", index_col="symbol")


def read_m1(folder, symbol, point):
    """All M1 files of a symbol as one frame in UTC: bid and ask OHLC, ticks, spread in points."""
    files = sorted(glob.glob(os.path.join(folder, symbol, f"{symbol}_M1_*.csv")))
    if not files:
        raise FileNotFoundError(f"no M1 files for {symbol} in {folder}")
    m = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    m = m.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    spread = m["spread"].to_numpy() * point
    out = pd.DataFrame({"time": server_to_utc(m["time"]), "server_time": m["time"]})
    for k in ("o", "h", "l", "c"):
        col = {"o": "open", "h": "high", "l": "low", "c": "close"}[k]
        out["bid_" + k] = m[col].to_numpy()
        out["ask_" + k] = m[col].to_numpy() + spread
    out["ticks"] = m["tick_volume"].to_numpy()
    out["spread_pts"] = m["spread"].to_numpy()
    return out


def resample(m1, minutes):
    """Bars of `minutes` length aligned to UTC (bar start times), from M1 bars."""
    bucket = m1["time"] // (minutes * 60)
    agg = {"time": "first", "bid_o": "first", "bid_h": "max", "bid_l": "min", "bid_c": "last",
           "ask_o": "first", "ask_h": "max", "ask_l": "min", "ask_c": "last", "ticks": "sum"}
    out = m1.groupby(bucket).agg(agg).reset_index(drop=True)
    out["time"] = (out["time"] // (minutes * 60)) * minutes * 60
    return out


def check_clock(m1, symbol):
    """Evidence that the server runs on New York time + 7 h. Returns printable findings."""
    utc = pd.to_datetime(m1["time"], unit="s", utc=True)
    ny = utc.dt.tz_convert("America/New_York")
    offsets = sorted(set(((pd.to_datetime(m1["server_time"], unit="s") - utc.dt.tz_localize(None))
                          / pd.Timedelta(hours=1)).round(2)))
    out = {"server minus UTC (hours)": offsets}
    # first bar of each week, in New York time
    week = ny.dt.tz_localize(None).dt.to_period("W-SAT")
    first = ny.groupby(week.to_numpy()).first()
    opens = first.dt.strftime("%a %H:%M").value_counts()
    out["week opens (New York)"] = opens.head(3).to_dict()
    if symbol.startswith(US_INDICES):
        nym = ny.dt.hour * 60 + ny.dt.minute
        weekday = ny.dt.dayofweek < 5
        ticks = m1["ticks"][weekday]                  # quote updates per minute
        prof = ticks.groupby(nym[weekday].to_numpy()).mean().reindex(range(1440)).interpolate()
        before = prof.rolling(15).mean()
        after = prof[::-1].rolling(15).mean()[::-1]
        jump = after / before.shift(1)
        # with a wrong clock the cash open would show up an hour earlier or later
        ratios = {f"{m // 60:02d}:30": round(float(jump[m]), 1) for m in (8 * 60 + 30, 9 * 60 + 30, 10 * 60 + 30)}
        verdict = "ok" if max(ratios, key=ratios.get) == "09:30" else "CHECK THE CLOCK"
        out["rise in quote updates at 08:30 / 09:30 / 10:30 New York"] = f"{ratios} {verdict}"
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    folder = sys.argv[1]
    specs = read_specs(folder)
    symbols = sys.argv[2:] or [s for s in specs.index if glob.glob(os.path.join(folder, s, f"{s}_M1_*.csv"))]
    os.makedirs(OUT_DIR, exist_ok=True)
    for s in symbols:
        point = float(specs.loc[s, "point"])
        m1 = read_m1(folder, s, point)
        first, last = (pd.to_datetime(m1["time"].iloc[k], unit="s") for k in (0, -1))
        print(f"{s}: {len(m1)} M1 bars, {first} .. {last} UTC, spread median "
              f"{m1['spread_pts'].median() * point:g} ({m1['spread_pts'].median():g} points)")
        for k, v in check_clock(m1, s).items():
            print(f"   {k}: {v}")
        resample(m1, 60).drop(columns="ticks").to_csv(os.path.join(OUT_DIR, f"{s}_H1.csv"), index=False)
        m5 = resample(m1, 5)
        pd.DataFrame({"time": m5["time"], "open": m5["bid_o"], "high": m5["bid_h"], "low": m5["bid_l"],
                      "close": m5["bid_c"], "ticks": m5["ticks"], "spread": m5["ask_o"] - m5["bid_o"]}
                     ).to_csv(os.path.join(OUT_DIR, f"{s}_M5.csv"), index=False)


if __name__ == "__main__":
    main()
