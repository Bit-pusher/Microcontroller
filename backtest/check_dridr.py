"""Checks of dridr.py: hand-made days, and optionally TradingView exports of the original.

Without arguments: levels, time zone, sessions past midnight, confirmation and
trade execution on cases worked out by hand.

With CSV files: exports of tradingview/DR_IDR_V1.5_export.pine or
tradingview/DR_IDR_Candles_LuxAlgo_export.pine ("Export chart data" on a
5-minute chart). The original's levels at the last bar of every
defining hour are compared with dridr.sessions() on the exported bars, and its
session flag with the New York time windows used here.

usage: python3 check_dridr.py [export.csv ...]
"""
import sys

import numpy as np
import pandas as pd

import dridr as dr


def bars_for(date, start_utc, rows):
    """5-minute bars from start_utc on (rows: open, high, low, close)."""
    t0 = pd.Timestamp(f"{date} {start_utc}", tz="UTC")
    times = [(t0 + pd.Timedelta(minutes=5 * k) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
             for k in range(len(rows))]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"]).assign(time=times, ticks=1)


def day(c, h=None, l=None, o=None, dr=(110.0, 100.0), idr=(108.0, 102.0)):
    c = np.asarray(c, float)
    o = np.r_[c[0], c[:-1]] if o is None else np.asarray(o, float)
    h = np.maximum(o, c) if h is None else np.asarray(h, float)
    l = np.minimum(o, c) if l is None else np.asarray(l, float)
    return {"date": pd.Timestamp("2020-01-02"), "dr_hi": dr[0], "dr_lo": dr[1], "idr_hi": idr[0], "idr_lo": idr[1],
            "o": o, "h": h, "l": l, "c": c}


def same(got, want):
    if got is None or want is None:
        return got is want
    if isinstance(want, tuple):
        return len(got) == len(want) and all(g is w if w is None else bool(np.isclose(g, w)) for g, w in zip(got, want))
    return got == want


def check(name, got, want):
    ok = same(got, want)
    shown = tuple(None if v is None else float(v) for v in got) if isinstance(got, tuple) else got
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {shown}" + ("" if ok else f" (expected {want})"))
    return ok


def main():
    ok = True
    # time zone: 09:30 New York is 13:30 UTC in summer, 14:30 UTC in winter; the bar at 10:30 is not in the DR
    for date, start in (("2017-06-01", "13:25"), ("2017-01-03", "14:25")):
        rows = [(100, 101, 99, 100)] + [(100, 104 if k == 3 else 101, 96 if k == 7 else 99, 102 if k == 5 else 100)
                                        for k in range(12)] + [(100, 130, 70, 100), (100, 101, 99, 100)]
        b = dr.prepare(bars_for(date, start, rows))
        d = dr.sessions(b, "RDR")
        ok &= check(f"levels {date}", (d[0]["dr_hi"], d[0]["dr_lo"], d[0]["idr_hi"], d[0]["idr_lo"]),
                    (104.0, 96.0, 102.0, 100.0))
        ok &= check(f"session bars {date}", len(d[0]["c"]), 2)
    # the ADR runs past midnight: 19:30-20:30 New York defines it (23:30 UTC in summer), lines until 02:00
    rows = ([(100, 101, 99, 100)] + [(100, 103, 97, 101)] * 12 + [(100, 101, 99, 100)] * 66
            + [(100, 130, 70, 100)])
    d = dr.sessions(dr.prepare(bars_for("2017-06-05", "23:25", rows)), "ADR")
    ok &= check("ADR day", str(d[0]["date"].date()), "2017-06-05")
    ok &= check("ADR levels", (d[0]["dr_hi"], d[0]["dr_lo"], d[0]["idr_hi"], d[0]["idr_lo"]), (103.0, 97.0, 101.0, 100.0))
    ok &= check("ADR session bars (20:30-02:00)", len(d[0]["c"]), 66)
    # LuxAlgo's fixed UTC-5 clock: in summer its hour starts at 10:30 New York (14:30 UTC), in winter at 09:30
    rows = [(100, 101, 99, 100)] * 12 + [(100, 106, 94, 105)] + [(100, 101, 99, 100)] * 11 + [(100, 101, 99, 100)] * 6
    for date, start, want in (("2017-06-01", "13:30", (101.0, 99.0, 106.0, 94.0)),
                              ("2017-01-03", "14:30", (101.0, 99.0, 101.0, 99.0))):
        b = dr.prepare(bars_for(date, start, rows))
        ny, lux = dr.sessions(b, "RDR")[0], dr.sessions(b, "RDR (LuxAlgo)")[0]
        ok &= check(f"DR high/low New York vs LuxAlgo {date}", (ny["dr_hi"], ny["dr_lo"], lux["dr_hi"], lux["dr_lo"]), want)

    # first close beyond the DR decides; a close beyond the IDR comes earlier
    d = day([105, 109, 111, 99, 104])
    ok &= check("DR confirmation", dr.confirmation(d, "dr"), (2, 1))
    ok &= check("IDR confirmation", dr.confirmation(d, "idr"), (1, 1))
    ok &= check("no confirmation", dr.confirmation(day([105, 106, 104]), "dr"), (None, 0))

    # market entry at the next open, held to the session close
    ok &= check("confirm, session end", dr.trade(day([111, 112, 115, 113]), "confirm", "dr", None, False), (1, 111, 113))
    # stop at the DR low; a gap through the stop fills at the open
    ok &= check("stop", dr.trade(day([111, 112, 101, 99], l=[110, 111, 101, 99]), "confirm", "dr", None, False),
                (1, 111, 100))
    ok &= check("stop gap", dr.trade(day([111, 112, 97, 99], o=[109, 111, 98, 97]), "confirm", "dr", None, False),
                (1, 111, 98))
    # targets in IDR "standard deviations" (range 6): 0.5 SD = 111, 1 SD = 114
    ok &= check("target 1 SD", dr.trade(day([111, 112, 113, 115, 112]), "confirm", "dr", 1.0, False), (1, 111, 114))
    ok &= check("target already reached", dr.trade(day([111, 112, 113]), "confirm", "dr", 0.5, False), None)
    ok &= check("stop and target in one bar", dr.trade(day([111, 112, 112], h=[111, 112, 120], l=[110, 111, 90]),
                                                       "confirm", "dr", 1.0, False), (1, 111, 100))
    # stop at the DR middle (105)
    ok &= check("stop DR middle", dr.trade(day([111, 112, 104, 120]), "confirm", "mid", None, False), (1, 111, 105))
    # retracement: limit at the IDR high (108) after the confirmation, then target
    ok &= check("retrace fill + target", dr.trade(day([111, 112, 109, 110, 115], l=[110, 111, 107, 109, 110]),
                                                  "retrace", "dr", 1.0, False), (1, 108, 114))
    ok &= check("retrace to the IDR middle (105)", dr.trade(day([111, 112, 106, 110, 115], l=[110, 111, 104, 109, 110]),
                                                           "retrace_mid", "dr", None, False), (1, 105, 115))
    ok &= check("retrace, target first", dr.trade(day([111, 115, 107, 110]), "retrace", "dr", 1.0, False), None)
    ok &= check("retrace, stopped in fill bar", dr.trade(day([111, 112, 106], l=[110, 111, 99]), "retrace", "dr", None,
                                                         False), (1, 108, 100))
    ok &= check("retrace, opens beyond stop", dr.trade(day([111, 112, 98], o=[110, 111, 99]), "retrace", "dr", None,
                                                       False), None)
    # short side mirrors; long only skips it
    short = day([99, 98, 95, 96])
    ok &= check("short", dr.trade(short, "confirm", "dr", None, False), (-1, 99, 96))
    ok &= check("short target 0.5 SD (99)", dr.trade(day([99, 100, 97], h=[100, 100.5, 100]), "confirm", "dr", 0.5,
                                                     False), None)
    ok &= check("long only", dr.trade(short, "confirm", "dr", None, True), None)

    # the published rule: after a close above the DR high, does the DR low hold?
    s = dr.stats([day([111, 112, 101, 99], l=[110, 111, 101, 99]), day([111, 112, 115])])
    ok &= check("DR low broken / held", list(s["dr_held"]), [False, True])
    print("ALL CHECKS PASSED" if ok else "CHECKS FAILED")


def compare_export(path):
    """Levels of DR/IDR V1.5 on TradingView against dridr.sessions() on the same bars."""
    x = pd.read_csv(path)
    t = x["time"]
    if not pd.api.types.is_numeric_dtype(t):                 # "ISO time" export instead of UNIX
        t = (pd.to_datetime(t, utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    b = dr.prepare(pd.DataFrame({"time": t.astype("int64"), "open": x["open"], "high": x["high"],
                                 "low": x["low"], "close": x["close"]}))
    print(f"{path}: {len(b)} bars {pd.to_datetime(b['time'].iloc[0], unit='s').date()} .. "
          f"{pd.to_datetime(b['time'].iloc[-1], unit='s').date()}")
    dr.MIN_DR_BARS = 1                                       # compare every session, gaps included
    ok = True
    lux = "Rolling DR Maximum" in x.columns                  # LuxAlgo DR/IDR Candles (default UTC-5 clock)
    cols = (["Rolling DR Maximum", "Rolling DR Minimum", "Rolling IDR Maximum", "Rolling IDR Minimum"] if lux
            else ["DR high", "DR low", "IDR high", "IDR low"])
    code = {"RDR": 1, "ADR": 2, "ODR": 3, "RDR (LuxAlgo)": 1, "ODR (LuxAlgo)": 3}
    for name, (a, e, _) in (dr.LUX_SESSIONS if lux else dr.SESSIONS).items():
        m = b["minute_est" if lux else "minute"].to_numpy()
        in_hour = (m - a) % 1440 < (e - a) % 1440
        if "DR hour" in x.columns:
            flag = x["DR hour"].to_numpy() == code[name]
            ok &= check(f"{name} defining hour, bars flagged differently", int((flag != in_hour).sum()), 0)
        day = (b["date_est" if lux else "date"] - pd.to_timedelta((m < a).astype(int), unit="D")).to_numpy()
        last = pd.Series(np.arange(len(b))[in_hour]).groupby(day[in_hour]).last()
        days = dr.sessions(b, name)[1:]                      # the first session may start before the export
        bad = 0
        for d in days:
            k = last.get(d["date"].to_datetime64())
            if k is None:
                continue
            ours = np.array([d["dr_hi"], d["dr_lo"], d["idr_hi"], d["idr_lo"]])
            theirs = x.loc[k, cols].to_numpy(float)
            if not np.allclose(ours, theirs, rtol=0, atol=1e-9 * abs(ours[0])):
                bad += 1
                if bad <= 3:
                    print(f"     {d['date'].date()}: ours {ours}, TradingView {theirs}")
        ok &= check(f"{name} sessions ({len(days)}) with different DR/IDR", bad, 0)
    return ok


if __name__ == "__main__":
    main()
    if len(sys.argv) > 1:
        results = [compare_export(p) for p in sys.argv[1:]]
        print("EXPORTS MATCH" if all(results) else "EXPORTS DIFFER")
