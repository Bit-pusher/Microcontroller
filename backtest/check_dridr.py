"""Checks of dridr.py on hand-made days: levels, time zone, confirmation and trade execution.

No TradingView export of a DR/IDR script was available, so the definitions are
checked against cases worked out by hand instead.

usage: python3 check_dridr.py
"""
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


if __name__ == "__main__":
    main()
