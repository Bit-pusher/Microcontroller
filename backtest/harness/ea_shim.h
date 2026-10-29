// The few MQL5 functions ScalpingVideoEA/ScalpingCore.mqh uses, so that it compiles as C++ unchanged.
#pragma once
#include <cmath>

inline double MathMax(double a, double b) { return a > b ? a : b; }
inline double MathMin(double a, double b) { return a < b ? a : b; }
inline double MathAbs(double x) { return std::fabs(x); }
