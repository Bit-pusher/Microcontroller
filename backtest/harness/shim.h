// Minimal MQL5 runtime emulation so the indicator logic compiles with a C++ compiler.
#pragma once
#include <cmath>
#include <cfloat>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <string>
#include <vector>
#include <map>
#include <algorithm>
#include <type_traits>

typedef std::string string;
typedef unsigned int color;
typedef long long datetime;
typedef unsigned int uint;

#define RGBC(r,g,b) ((color)((r)|((g)<<8)|((b)<<16)))
#define EMPTY_VALUE DBL_MAX

template<typename T> struct Arr {
  std::vector<T> v;
  T& operator[](long i) { chk(i); return v[i]; }
  const T& operator[](long i) const { chk(i); return v[i]; }
  void chk(long i) const { if(i < 0 || i >= (long)v.size()) { fprintf(stderr, "ARRAY OUT OF RANGE %ld (size %zu)\n", i, v.size()); abort(); } }
};
template<typename T> int ArrayResize(Arr<T>& a, int n, int = 0) { a.v.resize(n); return n; }
template<typename T> int ArraySize(const Arr<T>& a) { return (int)a.v.size(); }
template<typename T> bool ArraySort(Arr<T>& a) { std::sort(a.v.begin(), a.v.end()); return true; }

enum ENUM_INDEXBUFFER_TYPE { INDICATOR_DATA, INDICATOR_COLOR_INDEX, INDICATOR_CALCULATIONS };
enum { PLOT_EMPTY_VALUE, PLOT_LINE_COLOR, PLOT_SHOW_DATA, PLOT_COLOR_INDEXES, PLOT_ARROW, PLOT_ARROW_SHIFT,
       INDICATOR_SHORTNAME, INDICATOR_DIGITS, CHART_COLOR_BACKGROUND,
       OBJPROP_SELECTABLE, OBJPROP_HIDDEN, OBJPROP_FONTSIZE, OBJPROP_FONT, OBJPROP_ANCHOR, OBJPROP_COLOR,
       OBJPROP_TEXT, OBJPROP_TIME, ANCHOR_UPPER, ANCHOR_LOWER };
enum { OBJ_TEXT = 101 };
enum { INIT_SUCCEEDED = 0, INIT_FAILED = 1, INIT_PARAMETERS_INCORRECT = 2 };
enum ENUM_TIMEFRAMES { PERIOD_H1 = 16385 };
inline std::string EnumToString(ENUM_TIMEFRAMES) { return "PERIOD_H1"; }
int _Digits = 5; std::string _Symbol = "TEST"; int _Period = PERIOD_H1;

// ---- buffer registry
std::vector<Arr<double>*> g_buffers; std::vector<int> g_bufferTypes;
bool SetIndexBuffer(int idx, Arr<double>& a, int type) {
  if((int)g_buffers.size() <= idx) { g_buffers.resize(idx + 1, nullptr); g_bufferTypes.resize(idx + 1, -1); }
  if(g_buffers[idx]) { fprintf(stderr, "buffer %d bound twice\n", idx); abort(); }
  g_buffers[idx] = &a; g_bufferTypes[idx] = type; return true;
}
template<class... A> bool PlotIndexSetInteger(A...) { return true; }
template<class... A> bool PlotIndexSetDouble(A...) { return true; }
template<class... A> bool IndicatorSetString(A...) { return true; }
template<class... A> bool IndicatorSetInteger(A...) { return true; }
inline long ChartGetInteger(long, int) { return 0; }
inline void ChartRedraw() {}
inline bool IsStopped() { return false; }
inline ulong GetMicrosecondCount() { return 4242; }

// ---- math
template<class A, class B> auto MathMax(A a, B b) -> typename std::common_type<A,B>::type { return a > b ? a : b; }
template<class A, class B> auto MathMin(A a, B b) -> typename std::common_type<A,B>::type { return a < b ? a : b; }
inline double MathAbs(double x) { return std::fabs(x); }
inline double MathPow(double x, double y) { return std::pow(x, y); }
inline double MathSqrt(double x) { return std::sqrt(x); }
inline double MathExp(double x) { return std::exp(x); }
inline double MathLog10(double x) { return std::log10(x); }
inline double MathRound(double x) { return std::round(x); }
inline double MathFloor(double x) { return std::floor(x); }
inline bool MathIsValidNumber(double x) { return std::isfinite(x); }

// ---- strings
inline std::string IntegerToString(long long v) { return std::to_string(v); }
inline std::string DoubleToString(double v, int d) { char b[64]; snprintf(b, sizeof b, "%.*f", d, v); return b; }
inline int StringLen(const std::string& s) { return (int)s.size(); }
inline std::string StringSubstr(const std::string& s, int start, int len = -1) { return len < 0 ? s.substr(start) : s.substr(start, len); }
inline int StringFind(const std::string& s, const std::string& sub, int start = 0) { auto p = s.find(sub, start); return p == std::string::npos ? -1 : (int)p; }
template<class T> T fmtArg(const T& x) { return x; }
inline const char* fmtArg(const std::string& s) { return s.c_str(); }
template<class... A> std::string StringFormat(const std::string& f, A... a) { char b[2048]; snprintf(b, sizeof b, f.c_str(), fmtArg(a)...); return b; }

// ---- messages
std::vector<std::string> g_alerts;
inline void Print(const std::string& s) { fprintf(stderr, "Print: %s\n", s.c_str()); }
inline void Alert(const std::string& s) { g_alerts.push_back(s); }
inline bool SendNotification(const std::string& s) { g_alerts.push_back("PUSH " + s); return true; }
inline bool SendMail(const std::string&, const std::string& s) { g_alerts.push_back("MAIL " + s); return true; }

// ---- chart objects (only what the indicator uses)
struct Obj { int type; long long time; double price; std::string text; long anchor; long clr; };
std::map<std::string, Obj> g_objects;
inline int ObjectFind(long, const std::string& n) { return g_objects.count(n) ? 0 : -1; }
inline bool ObjectCreate(long, const std::string& n, int type, int, long long time, double price) {
  if(g_objects.count(n)) return false; g_objects[n] = Obj{type, time, price, "", 0, 0}; return true; }
inline bool ObjectDelete(long, const std::string& n) { return g_objects.erase(n) > 0; }
inline int ObjectsDeleteAll(long, const std::string& prefix) {
  int c = 0; for(auto it = g_objects.begin(); it != g_objects.end();) { if(it->first.rfind(prefix, 0) == 0) { it = g_objects.erase(it); c++; } else ++it; } return c; }
inline bool ObjectMove(long, const std::string& n, int, long long time, double price) {
  auto it = g_objects.find(n); if(it == g_objects.end()) return false; it->second.time = time; it->second.price = price; return true; }
inline bool ObjectSetInteger(long, const std::string& n, int prop, long long v) {
  auto it = g_objects.find(n); if(it == g_objects.end()) return false;
  if(prop == OBJPROP_ANCHOR) it->second.anchor = v; if(prop == OBJPROP_COLOR) it->second.clr = v; return true; }
inline bool ObjectSetString(long, const std::string& n, int prop, const std::string& v) {
  auto it = g_objects.find(n); if(it == g_objects.end()) return false; if(prop == OBJPROP_TEXT) it->second.text = v; return true; }
inline int ObjectsTotal(long, int, int type) { int c = 0; for(auto& kv : g_objects) if(kv.second.type == type) c++; return c; }
inline std::string ObjectName(long, int pos, int, int type) {
  int c = 0; for(auto& kv : g_objects) if(kv.second.type == type) { if(c == pos) return kv.first; c++; } return ""; }
inline long long ObjectGetInteger(long, const std::string& n, int prop) {
  auto it = g_objects.find(n); if(it == g_objects.end()) return 0; return prop == OBJPROP_TIME ? it->second.time : 0; }
