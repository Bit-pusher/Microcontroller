// Runs ScalpingVideoEA/ScalpingCore.mqh, compiled as C++, on 1-minute bars. The simulated broker fills and
// exits orders like backtest/scalping.py: market orders at the next open, stops at their price or a worse open
// (first in a bar), targets and resting limits at their price, the day end at the close of the forex day's last
// bar; a Fibonacci fill bar can only stop out. Writes one line per trade.
// usage: zcat ../data/m1/EURUSD_M1.csv.gz | ea_runner strategy tf tokyo rsi_rule fib_ema > trades.csv
//        strategy 0 day plan, 1 Tokyo, 2 box, 3 RSI, 4 Fibonacci; tf 1 or 5; tokyo 0 (19-04) or 1 (20-03)
#include "ea_shim.h"
#include "../../ScalpingVideoEA/ScalpingCore.mqh"
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

struct Order {
  int state = 0;                      // 0 none, 1 market waiting for the next open, 2 resting limit, 3 open
  int side = 0;
  double stop = 0, rr = 0, target = 0, price = 0, cancel = 0, entry = 0;
  long entry_i = -1;
  bool fill_bar_stop_only = false;
};

static const char* KIND[SC_COMPONENTS] = {"tokyo", "box", "rsi", "fib"};

class Sim : public CScalpBroker {
 public:
  std::vector<double> O, H, L, C;
  std::vector<int> minute;
  std::vector<long> day;
  Order q[SC_COMPONENTS];
  std::deque<std::pair<int, long>> ev[SC_COMPONENTS];

  bool Market(const int comp, const int side, const double stop, const double rr, const double target) override {
    Order& o = q[comp];
    if (o.state != 0) { fprintf(stderr, "Market while busy (component %d)\n", comp); exit(5); }
    o = Order();
    o.state = 1; o.side = side; o.stop = stop; o.rr = rr; o.target = target;
    o.fill_bar_stop_only = comp == SC_C_FIB;
    return true;
  }
  bool Limit(const int comp, const int side, const double price, const double stop, const double target,
             const double cancel) override {
    Order& o = q[comp];
    if (o.state != 0) { fprintf(stderr, "Limit while busy (component %d)\n", comp); exit(5); }
    o = Order();
    o.state = 2; o.side = side; o.price = price; o.stop = stop; o.target = target; o.cancel = cancel;
    o.fill_bar_stop_only = true;
    return true;
  }
  void Cancel(const int comp) override { if (q[comp].state == 1 || q[comp].state == 2) q[comp].state = 0; }
  int Status(const int comp) override {
    return q[comp].state == 0 ? SC_ST_NONE : q[comp].state == 3 ? SC_ST_OPEN : SC_ST_PENDING;
  }
  int PopEvent(const int comp, long& bar) override {
    if (ev[comp].empty()) return SC_EV_NONE;
    auto e = ev[comp].front();
    ev[comp].pop_front();
    bar = e.second;
    return e.first;
  }

  // the broker's part of 1-minute bar x, before the core sees its close
  void Process(long x) {
    const long n = (long)C.size();
    const bool last_of_day = x + 1 >= n || day[x + 1] != day[x];
    for (int comp = 0; comp < SC_COMPONENTS; comp++) {
      Order& o = q[comp];
      if (o.state == 1) {
        o.entry = O[x];
        o.entry_i = x;
        if (o.rr > 0) o.target = o.entry + o.side * o.rr * ((o.entry - o.stop) * o.side);
        o.state = 3;
        ev[comp].push_back({SC_EV_FILLED, x});
      } else if (o.state == 2) {
        if (minute[x] >= SC_NO_ENTRY_FROM && minute[x] < SC_NO_ENTRY_TO) {
          o.state = 0;
          ev[comp].push_back({SC_EV_VOID, x});
        } else if (o.side < 0 ? L[x] < o.cancel : H[x] > o.cancel) {
          o.state = 0;
          ev[comp].push_back({SC_EV_CANCELLED, x});
        } else if (o.side < 0 ? H[x] >= o.price : L[x] <= o.price) {
          o.entry = o.price;
          o.entry_i = x;
          o.state = 3;
          ev[comp].push_back({SC_EV_FILLED, x});
        }
      }
      if (o.state == 3) {
        bool done = false;
        double px = 0;
        const char* why = "";
        if (o.side > 0 ? L[x] <= o.stop : H[x] >= o.stop) {
          px = o.side > 0 ? std::min(o.stop, O[x]) : std::max(o.stop, O[x]);
          why = "stop"; done = true;
        } else if (!(o.fill_bar_stop_only && x == o.entry_i) && (o.side > 0 ? H[x] >= o.target : L[x] <= o.target)) {
          px = o.target; why = "target"; done = true;
        } else if (last_of_day) {
          px = C[x]; why = "day end"; done = true;
        }
        if (done) {
          printf("%s,%d,%ld,%.10g,%.10g,%.10g,%ld,%.10g,%s\n", KIND[comp], o.side, o.entry_i, o.entry, o.stop,
                 o.target, x, px, why);
          o.state = 0;
          ev[comp].push_back({SC_EV_CLOSED, x});
        }
      } else if (o.state == 2 && last_of_day) {
        o.state = 0;
        ev[comp].push_back({SC_EV_EXPIRED, x});
      }
    }
  }
};

static Sim g_sim;
static CScalpCore g_core;

int main(int argc, char** argv) {
  if (argc < 6) { fprintf(stderr, "usage: ea_runner strategy tf tokyo rsi_rule fib_ema < bars.csv\n"); return 2; }
  g_core.Init(atoi(argv[1]), atoi(argv[2]), atoi(argv[3]), atoi(argv[4]) != 0, atoi(argv[5]) != 0);
  std::vector<long> T;
  std::string line;
  std::getline(std::cin, line);                                 // header: time,open,high,low,close,...
  while (std::getline(std::cin, line)) {
    std::stringstream ss(line);
    std::string f[5];
    for (int i = 0; i < 5; i++) std::getline(ss, f[i], ',');
    T.push_back(atol(f[0].c_str()));
    g_sim.O.push_back(atof(f[1].c_str())); g_sim.H.push_back(atof(f[2].c_str()));
    g_sim.L.push_back(atof(f[3].c_str())); g_sim.C.push_back(atof(f[4].c_str()));
  }
  const long n = (long)T.size();
  std::vector<long> ny(n);
  for (long i = 0; i < n; i++) {
    ny[i] = ScNewYork(T[i]);
    g_sim.minute.push_back(g_core.Minute(ny[i]));
    g_sim.day.push_back(g_core.Day(ny[i]));
  }
  printf("kind,side,entry_i,entry,stop,target,exit_i,exit,reason\n");
  for (long i = 0; i < n; i++) {
    g_sim.Process(i);
    SScBar bar, next;
    bar.clock = T[i]; bar.ny = ny[i];
    bar.open = g_sim.O[i]; bar.high = g_sim.H[i]; bar.low = g_sim.L[i]; bar.close = g_sim.C[i];
    const bool has_next = i + 1 < n;
    const long j = has_next ? i + 1 : i;
    next.clock = T[j]; next.ny = ny[j];
    next.open = g_sim.O[j]; next.high = g_sim.H[j]; next.low = g_sim.L[j]; next.close = g_sim.C[j];
    g_core.OnBar(g_sim, bar, next, has_next);
  }
  return 0;
}
