//+------------------------------------------------------------------+
//|                                            AI_SuperTrend_KNN.mq5 |
//|               MQL5 port of the TradingView indicator             |
//|          "AI-SuperTrend (KNN Machine Learning)" by SatohK        |
//+------------------------------------------------------------------+
// This code is subject to the terms of the Mozilla Public License 2.0
// at https://mozilla.org/MPL/2.0/
// Original Pine Script (c) SatohK. This file is an MQL5 port of it.
//
// Port notes
// - Pine builds the medium/long horizon features from close[stride] and
//   close[2*stride]. Those series are the short horizon features shifted
//   by stride bars, so they are read from history instead of recomputed.
// - normalize() is (src - sma(src[1], n)) / max(stdev(src[1], n), 1e-5)
//   over the previous n valid values; it is evaluated with running sums,
//   so every bar costs O(1) instead of O(n) (windows that are almost
//   constant are recomputed exactly to avoid cancellation errors).
// - Neighbours whose features are still warming up are skipped.
// - MT5 has no transparency: the trend fill uses the trend colour blended
//   with the chart background, bar colouring uses a stepped gradient and
//   the prediction labels are single line text objects.
#property copyright   "Original Pine Script (c) SatohK - Mozilla Public License 2.0"
#property link        "https://mozilla.org/MPL/2.0/"
#property version     "1.00"
#property description "AI-SuperTrend (KNN Machine Learning) - MQL5 port."
#property description "The SuperTrend direction labels a distance weighted KNN classifier"
#property description "trained on normalized RSI, MA deviation and Choppiness features."

#property indicator_chart_window
#property indicator_buffers 71
#property indicator_plots   13

#property indicator_label1  "Up Fill Low;Up Fill Trend"
#property indicator_type1   DRAW_FILLING
#property indicator_label2  "Down Fill High;Down Fill Trend"
#property indicator_type2   DRAW_FILLING
#property indicator_label3  "AI Bar Open;AI Bar High;AI Bar Low;AI Bar Close"
#property indicator_type3   DRAW_COLOR_CANDLES
#property indicator_label4  "Up Trend"
#property indicator_type4   DRAW_LINE
#property indicator_width4  2
#property indicator_label5  "Down Trend"
#property indicator_type5   DRAW_LINE
#property indicator_width5  2
#property indicator_label6  "ST Long"
#property indicator_type6   DRAW_COLOR_ARROW
#property indicator_label7  "ST Short"
#property indicator_type7   DRAW_COLOR_ARROW
#property indicator_label8  "Major Long"
#property indicator_type8   DRAW_ARROW
#property indicator_width8  2
#property indicator_label9  "Major Short"
#property indicator_type9   DRAW_ARROW
#property indicator_width9  2
#property indicator_label10 "Prob Up"
#property indicator_type10  DRAW_NONE
#property indicator_label11 "Prob Down"
#property indicator_type11  DRAW_NONE
#property indicator_label12 "Signal State"
#property indicator_type12  DRAW_NONE
#property indicator_label13 "ST Direction"
#property indicator_type13  DRAW_NONE

#define NA              EMPTY_VALUE  // Pine "na"
#define GRADIENT_STEPS  20           // bar colour steps per side (palette max is 64)

#define PL_UP_FILL      0
#define PL_DN_FILL      1
#define PL_BARS         2
#define PL_UP_TREND     3
#define PL_DN_TREND     4
#define PL_ST_LONG      5
#define PL_ST_SHORT     6
#define PL_MAJOR_LONG   7
#define PL_MAJOR_SHORT  8
#define PL_COUNT        13

enum ENUM_FEATURE_MA
  {
   FEATURE_MA_SMA,   // SMA
   FEATURE_MA_EMA,   // EMA
   FEATURE_MA_DEMA,  // DEMA
   FEATURE_MA_TEMA,  // TEMA
   FEATURE_MA_LSMA,  // LSMA
   FEATURE_MA_WMA,   // WMA
   FEATURE_MA_HMA,   // HMA
   FEATURE_MA_ZLSMA, // ZLSMA
   FEATURE_MA_SMMA,  // SMMA
   FEATURE_MA_THMA   // THMA
  };

input group "SuperTrend"
input int             InpAtrPeriod      = 10;              // ATR Length
input double          InpFactor         = 2.0;             // Factor

input group "Machine Learning Engine"
input int             InpNeighbors      = 10;              // K-Neighbors (K)
input int             InpSamplingWindow = 1000;            // Learning Window Size
input int             InpStride         = 10;              // Stride
input double          InpProbThreshold  = 0.9;             // Prediction Threshold

input group "Feature Engineering"
input ENUM_FEATURE_MA InpFeatMaType     = FEATURE_MA_SMA;  // Feature MA Type
input int             InpRsiLen         = 20;              // RSI Period
input int             InpMaLen          = 20;              // MA Period
input int             InpSignalLen      = 10;              // Signal Line Period
input int             InpChopLen        = 14;              // CHOP Period
input int             InpNormWindow     = 1000;            // Normalizing Window Size
input double          InpMinkowskiP     = 2.0;             // Minkowski Parameter (p)
input double          InpShapeParam     = 2.0;             // Shape Parameter

input group "Dimensionality Reduction"
input bool            InpUsePca         = true;            // Enable PCA Compression

input group "Visual Analytics"
input bool            InpBarColor       = true;            // Dynamic Bar Coloring
input bool            InpTrendFill      = true;            // Trend Fill
input int             InpFillOpacity    = 30;              // Trend Fill Opacity (%)
input bool            InpPredLabels     = true;            // Prediction Labels
input int             InpMaxLabels      = 200;             // Max Prediction Labels
input color           InpBullColor      = C'40,158,255';   // Bull Color
input color           InpBearColor      = C'206,63,108';   // Bear Color
input color           InpNeutralColor   = C'100,116,139';  // Neutral Color

input group "Alerts"
input bool            InpAlertPopup     = false;           // Popup Alert
input bool            InpAlertPush      = false;           // Push Notification
input bool            InpAlertEmail     = false;           // Email
input bool            InpAlertOnClose   = true;            // Alert on Bar Close only

//--- plot buffers
double UpFillLow[], UpFillTrend[];
double DnFillHigh[], DnFillTrend[];
double BarOpen[], BarHigh[], BarLow[], BarClose[], BarColor[];
double UpTrend[];
double DnTrend[];
double StLong[], StLongColor[];
double StShort[], StShortColor[];
double MajorLong[];
double MajorShort[];
double ProbUp[];
double ProbDown[];
double SignalState[];  // Pine: last_stdir
double Direction[];    // Pine: direction (-1 = up trend, 1 = down trend)
//--- SuperTrend
double TrueRange[], Atr[], UpperBand[], LowerBand[], SuperTrendRaw[], Target[];
//--- features (short horizon only)
double Gain[], Loss[], AvgGain[], AvgLoss[], Rsi[], RsiSignal[], RsiSigDist[];
double MaTmp1[], MaTmp2[], MaTmp3[], FeatMa[], MaDev[];
double Chop[];
//--- normalization: running count, sum, sum of squares and the z-score
double RsiCnt[], RsiSum[], RsiSq[], RsiZ[];
double MaDevCnt[], MaDevSum[], MaDevSq[], MaDevZ[];
double SigDistCnt[], SigDistSum[], SigDistSq[], SigDistZ[];
double ChopCnt[], ChopSum[], ChopSq[], ChopZ[];
double MomIn[], MomCnt[], MomSum[], MomSq[], MomZ[];            // PCA: RSI + MA dev + signal dist
double ChopIn[], ChopInCnt[], ChopInSum[], ChopInSq[], ChopInZ[]; // PCA: CHOP over 3 horizons
//--- KNN inputs and signal state
double Pc1[], Pc2[], Pc3[], Pc4[];
double LastDir[];      // Pine: last_dir

double   g_topDist[];
double   g_topLabel[];
string   g_prefix;
datetime g_lastAlertTime = 0;

//+------------------------------------------------------------------+
//| Pine-style helpers                                               |
//+------------------------------------------------------------------+
bool IsNa(const double v)
  {
   return(v == NA);
  }

//--- src[bars] in Pine terms
double Back(const double &src[], const int t, const int bars)
  {
   return(t - bars >= 0 ? src[t - bars] : NA);
  }

double Scale(const double v, const double factor)
  {
   return(IsNa(v) ? NA : v * factor);
  }

double Combine(const double a, const double wa, const double b, const double wb,
               const double c = 0.0, const double wc = 0.0)
  {
   if(IsNa(a) || IsNa(b) || IsNa(c))
      return(NA);
   return(a * wa + b * wb + c * wc);
  }

//--- (value - base) / base
double RelativeTo(const double value, const double base)
  {
   if(IsNa(value) || IsNa(base) || base == 0.0)
      return(NA);
   return((value - base) / base);
  }

double SmaAt(const double &src[], const int t, const int len)
  {
   if(t - len + 1 < 0)
      return(NA);
   double sum = 0.0;
   for(int k = t - len + 1; k <= t; k++)
     {
      if(IsNa(src[k]))
         return(NA);
      sum += src[k];
     }
   return(sum / len);
  }

double WmaAt(const double &src[], const int t, const int len)
  {
   if(t - len + 1 < 0)
      return(NA);
   double sum = 0.0, norm = 0.0;
   for(int k = 0; k < len; k++)
     {
      double v = src[t - k];
      if(IsNa(v))
         return(NA);
      double w = len - k;
      sum  += v * w;
      norm += w;
     }
   return(sum / norm);
  }

//--- ta.linreg(src, len, 0): least squares line evaluated at the current bar
double LinregAt(const double &src[], const int t, const int len)
  {
   if(t - len + 1 < 0)
      return(NA);
   double sx = 0.0, sy = 0.0, sxx = 0.0, sxy = 0.0;
   for(int x = 0; x < len; x++)
     {
      double y = src[t - len + 1 + x];
      if(IsNa(y))
         return(NA);
      sx  += x;
      sy  += y;
      sxx += (double)x * x;
      sxy += x * y;
     }
   double den = len * sxx - sx * sx;
   if(den == 0.0)
      return(sy / len);
   double slope     = (len * sxy - sx * sy) / den;
   double intercept = (sy - slope * sx) / len;
   return(intercept + slope * (len - 1));
  }

//--- ta.ema / ta.rma: recursive average seeded with the SMA of the first len values
double EmaStep(const double &src[], const double &out[], const int t, const int len, const double alpha)
  {
   if(t > 0 && !IsNa(out[t - 1]))
      return(IsNa(src[t]) ? NA : alpha * src[t] + (1.0 - alpha) * out[t - 1]);
   return(SmaAt(src, t, len));
  }

double Power(const double x, const double p)
  {
   if(p == 2.0)
      return(x * x);
   if(p == 1.0)
      return(x);
   return(MathPow(x, p));
  }

double Minkowski(const double d1, const double d2, const double d3, const double d4)
  {
   const double p = InpMinkowskiP;
   double sum = Power(d1, p) + Power(d2, p) + Power(d3, p) + Power(d4, p);
   if(p == 2.0)
      return(MathSqrt(sum));
   if(p == 1.0)
      return(sum);
   return(MathPow(sum, 1.0 / p));
  }

int Channel(const color c, const int shift)
  {
   return((int)(((uint)c >> shift) & 0xFF));
  }

color Blend(const color from, const color to, const double f)
  {
   int r = (int)MathRound(Channel(from, 0)  + (Channel(to, 0)  - Channel(from, 0))  * f);
   int g = (int)MathRound(Channel(from, 8)  + (Channel(to, 8)  - Channel(from, 8))  * f);
   int b = (int)MathRound(Channel(from, 16) + (Channel(to, 16) - Channel(from, 16)) * f);
   return((color)(r | (g << 8) | (b << 16)));
  }

//+------------------------------------------------------------------+
//| normalize(src, len) from the Pine script. cnt/sum/sq accumulate  |
//| the valid values of src, so the window over the previous len     |
//| valid values is the difference of two running totals.            |
//+------------------------------------------------------------------+
int WindowStart(const double &cnt[], const int e, const int len)
  {
   double target = cnt[e] - len;
   if(target <= 0.0)
      return(-1);
   int j = e - len;
   if(j >= 0 && cnt[j] == target)
      return(j);
//--- na values inside the window: find the first bar with cnt == target
   int lo = 0, hi = e;
   while(lo < hi)
     {
      int mid = (lo + hi) / 2;
      if(cnt[mid] < target)
         lo = mid + 1;
      else
         hi = mid;
     }
   return(lo);
  }

void NormalizeAt(const int t, const int len, const double &src[],
                 double &cnt[], double &sum[], double &sq[], double &out[])
  {
   double v  = src[t];
   bool   ok = !IsNa(v);
   cnt[t] = (t > 0 ? cnt[t - 1] : 0.0) + (ok ? 1.0 : 0.0);
   sum[t] = (t > 0 ? sum[t - 1] : 0.0) + (ok ? v : 0.0);
   sq[t]  = (t > 0 ? sq[t - 1]  : 0.0) + (ok ? v * v : 0.0);
   out[t] = NA;
   if(!ok || t == 0 || cnt[t - 1] < len)
      return;

   int e = t - 1;
   int j = WindowStart(cnt, e, len);
   double mean = (sum[e] - (j >= 0 ? sum[j] : 0.0)) / len;
   double var  = (sq[e] - (j >= 0 ? sq[j] : 0.0)) / len - mean * mean;
//--- the running totals cancel out when the window is (almost) constant,
//--- e.g. in a flat market: recompute that window exactly
   if(var <= 1e-7 * sq[e] / len)
     {
      mean = 0.0;
      for(int k = j + 1; k <= e; k++)
         if(!IsNa(src[k]))
            mean += src[k];
      mean /= len;
      var = 0.0;
      for(int k = j + 1; k <= e; k++)
         if(!IsNa(src[k]))
            var += (src[k] - mean) * (src[k] - mean);
      var /= len;
     }
   out[t] = (v - mean) / MathMax(MathSqrt(var), 0.00001);
  }

//+------------------------------------------------------------------+
//| ta.supertrend(factor, atrPeriod) and the KNN label (target)      |
//+------------------------------------------------------------------+
void CalcSupertrend(const int t, const double &high[], const double &low[], const double &close[])
  {
   TrueRange[t] = (t == 0) ? high[t] - low[t]
                  : MathMax(high[t] - low[t], MathMax(MathAbs(high[t] - close[t - 1]), MathAbs(low[t] - close[t - 1])));
   Atr[t] = EmaStep(TrueRange, Atr, t, InpAtrPeriod, 1.0 / InpAtrPeriod);

   double atr = Atr[t];
   double hl2 = (high[t] + low[t]) / 2.0;
   double up  = IsNa(atr) ? NA : hl2 + InpFactor * atr;
   double lo  = IsNa(atr) ? NA : hl2 - InpFactor * atr;
//--- Pine: prevBand = nz(band[1]); band := cond ? band : prevBand
   double prevUp = (t > 0 && !IsNa(UpperBand[t - 1])) ? UpperBand[t - 1] : 0.0;
   double prevLo = (t > 0 && !IsNa(LowerBand[t - 1])) ? LowerBand[t - 1] : 0.0;
   bool   hasPrevClose = t > 0;
   double prevClose    = hasPrevClose ? close[t - 1] : 0.0;
   LowerBand[t] = ((!IsNa(lo) && lo > prevLo) || (hasPrevClose && prevClose < prevLo)) ? lo : prevLo;
   UpperBand[t] = ((!IsNa(up) && up < prevUp) || (hasPrevClose && prevClose > prevUp)) ? up : prevUp;

   double dir;
   if(t == 0 || IsNa(Atr[t - 1]))
      dir = 1.0;
   else if(SuperTrendRaw[t - 1] == prevUp)
      dir = close[t] > UpperBand[t] ? -1.0 : 1.0;
   else
      dir = close[t] < LowerBand[t] ? 1.0 : -1.0;
   Direction[t]     = dir;
   SuperTrendRaw[t] = dir < 0 ? LowerBand[t] : UpperBand[t];

//--- label = trend direction, 0 while the trend is younger than 6 bars
   double target = -dir;
   for(int k = 1; k <= 5; k++)
      if(t - k < 0 || Direction[t - k] != dir)
        {
         target = 0.0;
         break;
        }
   Target[t] = target;
  }

//+------------------------------------------------------------------+
//| calcMA(feat_ma_type, src, len)                                   |
//+------------------------------------------------------------------+
double CalcMaAt(const int t, const double &src[])
  {
   const int len = (int)MathMax(1, InpMaLen);
   const double emaAlpha = 2.0 / (len + 1);
   switch(InpFeatMaType)
     {
      case FEATURE_MA_EMA:
         return(EmaStep(src, FeatMa, t, len, emaAlpha));
      case FEATURE_MA_DEMA:
         MaTmp1[t] = EmaStep(src, MaTmp1, t, len, emaAlpha);
         MaTmp2[t] = EmaStep(MaTmp1, MaTmp2, t, len, emaAlpha);
         return(Combine(MaTmp1[t], 2.0, MaTmp2[t], -1.0));
      case FEATURE_MA_TEMA:
         MaTmp1[t] = EmaStep(src, MaTmp1, t, len, emaAlpha);
         MaTmp2[t] = EmaStep(MaTmp1, MaTmp2, t, len, emaAlpha);
         MaTmp3[t] = EmaStep(MaTmp2, MaTmp3, t, len, emaAlpha);
         return(Combine(MaTmp1[t], 3.0, MaTmp2[t], -3.0, MaTmp3[t], 1.0));
      case FEATURE_MA_LSMA:
         return(LinregAt(src, t, len));
      case FEATURE_MA_WMA:
         return(WmaAt(src, t, len));
      case FEATURE_MA_HMA:
         MaTmp1[t] = Combine(WmaAt(src, t, (int)MathMax(1, len / 2)), 2.0, WmaAt(src, t, len), -1.0);
         return(WmaAt(MaTmp1, t, (int)MathMax(1.0, MathFloor(MathSqrt(len)))));
      case FEATURE_MA_ZLSMA:
         return(Combine(LinregAt(src, t, len), 2.0, SmaAt(src, t, len), -1.0));
      case FEATURE_MA_SMMA:
         return(EmaStep(src, FeatMa, t, len, 1.0 / len));
      case FEATURE_MA_THMA:
        {
         int l3 = (int)MathMax(1.0, MathRound(len / 3.0));
         int l2 = (int)MathMax(1.0, MathRound(len / 2.0));
         MaTmp1[t] = Combine(WmaAt(src, t, l3), 3.0, WmaAt(src, t, l2), -1.0, WmaAt(src, t, len), -1.0);
         return(WmaAt(MaTmp1, t, len));
        }
      default:
         return(SmaAt(src, t, len));
     }
  }

//--- f_chop(len)
double ChopAt(const int t, const double &high[], const double &low[], const double &close[])
  {
   const int len = InpChopLen;
   if(t < len)               // ta.tr is na on the first bar
      return(NA);
   double sumTr = 0.0, hh = high[t], ll = low[t];
   for(int k = t - len + 1; k <= t; k++)
     {
      sumTr += TrueRange[k];
      hh = MathMax(hh, high[k]);
      ll = MathMin(ll, low[k]);
     }
   double range = MathMax(hh, close[t - 1]) - MathMin(ll, close[t - 1]);
   if(range <= 0.0 || sumTr <= 0.0)
      return(NA);
   return(100.0 * MathLog10(sumTr / range) / MathLog10(len));
  }

//+------------------------------------------------------------------+
//| Features and their z-scores (short horizon)                      |
//+------------------------------------------------------------------+
void CalcFeatures(const int t, const double &high[], const double &low[], const double &close[])
  {
//--- ta.rsi(close, rsi_len)
   Gain[t]    = t > 0 ? MathMax(close[t] - close[t - 1], 0.0) : NA;
   Loss[t]    = t > 0 ? MathMax(close[t - 1] - close[t], 0.0) : NA;
   AvgGain[t] = EmaStep(Gain, AvgGain, t, InpRsiLen, 1.0 / InpRsiLen);
   AvgLoss[t] = EmaStep(Loss, AvgLoss, t, InpRsiLen, 1.0 / InpRsiLen);
   double ag = AvgGain[t], al = AvgLoss[t];
   if(IsNa(ag) || IsNa(al))
      Rsi[t] = NA;
   else
      Rsi[t] = al == 0.0 ? 100.0 : ag == 0.0 ? 0.0 : 100.0 - 100.0 / (1.0 + ag / al);

//--- (rsi - sma(rsi[1], signal_len)) / sma(rsi[1], signal_len)
   RsiSignal[t]  = SmaAt(Rsi, t, InpSignalLen);
   RsiSigDist[t] = RelativeTo(Rsi[t], Back(RsiSignal, t, 1));

//--- (close - calcMA(close[1])) / calcMA(close[1])
   FeatMa[t] = CalcMaAt(t, close);
   MaDev[t]  = RelativeTo(close[t], Back(FeatMa, t, 1));

   Chop[t] = ChopAt(t, high, low, close);

   const int w = InpNormWindow;
   NormalizeAt(t, w, Rsi,        RsiCnt,     RsiSum,     RsiSq,     RsiZ);
   NormalizeAt(t, w, MaDev,      MaDevCnt,   MaDevSum,   MaDevSq,   MaDevZ);
   NormalizeAt(t, w, RsiSigDist, SigDistCnt, SigDistSum, SigDistSq, SigDistZ);
   NormalizeAt(t, w, Chop,       ChopCnt,    ChopSum,    ChopSq,    ChopZ);
  }

//+------------------------------------------------------------------+
//| pc1..pc4. Medium horizon = shifted by stride, long = 2*stride.   |
//+------------------------------------------------------------------+
void CalcComponents(const int t)
  {
   const int s = InpStride;
   if(InpUsePca)
     {
      const int w = InpNormWindow;
      MomIn[t] = Combine(RsiZ[t], 1.0, MaDevZ[t], 1.0, SigDistZ[t], 0.5);
      NormalizeAt(t, w, MomIn, MomCnt, MomSum, MomSq, MomZ);
      ChopIn[t] = Combine(ChopZ[t], 1.0, Back(ChopZ, t, s), 0.9, Back(ChopZ, t, 2 * s), 0.8);
      NormalizeAt(t, w, ChopIn, ChopInCnt, ChopInSum, ChopInSq, ChopInZ);

      Pc1[t] = MomZ[t];
      Pc2[t] = Scale(Back(MomZ, t, s), 0.9);
      Pc3[t] = Scale(Back(MomZ, t, 2 * s), 0.8);
      Pc4[t] = Scale(ChopInZ[t], 0.8);
     }
   else
     {
      Pc1[t] = Back(RsiZ, t, s);
      Pc2[t] = Back(MaDevZ, t, s);
      Pc3[t] = Back(SigDistZ, t, s);
      Pc4[t] = Back(ChopZ, t, s);
     }
  }

//+------------------------------------------------------------------+
//| KNN core engine                                                  |
//+------------------------------------------------------------------+
void CalcKnn(const int t)
  {
   ProbUp[t]   = 0.0;
   ProbDown[t] = 0.0;
   if(t <= InpNormWindow + InpStride)
      return;
   double c1 = Pc1[t], c2 = Pc2[t], c3 = Pc3[t], c4 = Pc4[t];
   if(IsNa(c1) || IsNa(c2) || IsNa(c3) || IsNa(c4))
      return;

//--- keep the k nearest neighbours sorted by distance (ties: older entry first)
   const int k = InpNeighbors;
   int found = 0, kept = 0;
   for(int i = InpStride; i <= InpSamplingWindow + InpStride; i += InpStride)
     {
      int h = t - i;
      if(h < 0)
         break;
      double label = Target[h];
      if(label == 0.0)
         continue;
      double h1 = Pc1[h], h2 = Pc2[h], h3 = Pc3[h], h4 = Pc4[h];
      if(IsNa(h1) || IsNa(h2) || IsNa(h3) || IsNa(h4))
         continue;
      double d = Minkowski(MathAbs(c1 - h1), MathAbs(c2 - h2), MathAbs(c3 - h3), MathAbs(c4 - h4));
      if(!MathIsValidNumber(d))
         continue;
      found++;
      if(kept == k && d >= g_topDist[k - 1])
         continue;
      int pos = k - 1;
      if(kept < k)
         pos = kept++;
      while(pos > 0 && g_topDist[pos - 1] > d)
        {
         g_topDist[pos]  = g_topDist[pos - 1];
         g_topLabel[pos] = g_topLabel[pos - 1];
         pos--;
        }
      g_topDist[pos]  = d;
      g_topLabel[pos] = label;
     }
   if(found < k)
      return;

   double sigma = MathMax(g_topDist[k / 2], 0.0001);
   double denom = 2.0 * sigma * sigma;
   double sumUp = 0.0, sumDown = 0.0, total = 0.0;
   for(int j = 0; j < k; j++)
     {
      double weight = MathExp(-Power(g_topDist[j], InpShapeParam) / denom);
      if(g_topLabel[j] == 1.0)
         sumUp += weight;
      else if(g_topLabel[j] == -1.0)
         sumDown += weight;
      total += weight;
     }
   if(total > 0.0)
     {
      ProbUp[t]   = sumUp / total;
      ProbDown[t] = sumDown / total;
     }
  }

//+------------------------------------------------------------------+
//| Signal generation (last_dir / last_stdir state machine)          |
//+------------------------------------------------------------------+
void CalcSignals(const int t)
  {
   const double thr = InpProbThreshold;
   double up = ProbUp[t], down = ProbDown[t];
   bool rawLong  = t > 0 && up > thr && ProbUp[t - 1] <= thr;       // ta.crossover(prob_up, thr)
   bool rawShort = t > 0 && down > thr && ProbDown[t - 1] <= thr;   // ta.crossover(prob_down, thr)

   double lastDir = t > 0 ? LastDir[t - 1] : 0.0;
   if(rawLong && lastDir <= 0)
      lastDir = 1.0;
   if(rawShort && lastDir >= 0)
      lastDir = -1.0;
   LastDir[t] = lastDir;

   double dir     = Direction[t];
   double prevDir = t > 0 ? Direction[t - 1] : 0.0;   // nz(direction[1])
   double state   = t > 0 ? SignalState[t - 1] : 0.0;
   if(dir != prevDir || rawLong || rawShort)
     {
      if(dir < 0 && lastDir == 1.0 && up > thr)
         state = -dir;
      if(dir > 0 && lastDir == -1.0 && down > thr)
         state = -dir;
     }
   SignalState[t] = state;
  }

//+------------------------------------------------------------------+
//| Visualization                                                    |
//+------------------------------------------------------------------+
int GradientStep(const double prob)
  {
//--- color.from_gradient(prob, 0.5, 0.95, neutral, bull/bear)
   double f = MathMin(MathMax((prob - 0.5) / 0.45, 0.0), 1.0);
   return((int)MathRound(f * GRADIENT_STEPS));
  }

int GradientIndex(const double up, const double down)
  {
   if(up > down)
      return(GradientStep(up));
   return(GRADIENT_STEPS + 1 + GradientStep(down));
  }

void CalcVisuals(const int t, const double &open[], const double &high[], const double &low[], const double &close[])
  {
   double dir       = Direction[t];
   double state     = SignalState[t];
   double prevDir   = t > 0 ? Direction[t - 1] : NA;
   double prevState = t > 0 ? SignalState[t - 1] : NA;
   double st        = (t == 0) ? NA : SuperTrendRaw[t];   // Pine: na on the first bar
   bool   hasSt     = !IsNa(st);

   UpTrend[t] = (state == 1.0 && hasSt) ? st : EMPTY_VALUE;
   DnTrend[t] = (state == -1.0 && hasSt) ? st : EMPTY_VALUE;

   bool upFill = InpTrendFill && state == 1.0 && dir < 0 && hasSt;
   UpFillLow[t]   = upFill ? low[t] : EMPTY_VALUE;
   UpFillTrend[t] = upFill ? st : EMPTY_VALUE;
   bool dnFill = InpTrendFill && state == -1.0 && dir > 0 && hasSt;
   DnFillHigh[t]  = dnFill ? high[t] : EMPTY_VALUE;
   DnFillTrend[t] = dnFill ? st : EMPTY_VALUE;

//--- ta.crossunder(direction, 0) / ta.crossover(direction, 0)
   bool flipUp = t > 0 && dir < 0 && prevDir >= 0;
   bool flipDn = t > 0 && dir > 0 && prevDir <= 0;
   double circleColor = state > 0 ? 0.0 : 1.0;
   StLong[t]       = (flipUp && hasSt) ? st : EMPTY_VALUE;
   StLongColor[t]  = circleColor;
   StShort[t]      = (flipDn && hasSt) ? st : EMPTY_VALUE;
   StShortColor[t] = circleColor;

//--- ta.crossover(last_stdir, 0) / ta.crossunder(last_stdir, 0)
   MajorLong[t]  = (t > 0 && state > 0 && prevState <= 0) ? low[t] : EMPTY_VALUE;
   MajorShort[t] = (t > 0 && state < 0 && prevState >= 0) ? high[t] : EMPTY_VALUE;

   if(InpBarColor)
     {
      BarOpen[t]  = open[t];
      BarHigh[t]  = high[t];
      BarLow[t]   = low[t];
      BarClose[t] = close[t];
      BarColor[t] = GradientIndex(ProbUp[t], ProbDown[t]);
     }
   else
     {
      BarOpen[t]  = EMPTY_VALUE;
      BarHigh[t]  = EMPTY_VALUE;
      BarLow[t]   = EMPTY_VALUE;
      BarClose[t] = EMPTY_VALUE;
      BarColor[t] = 0.0;
     }
  }

//+------------------------------------------------------------------+
//| "Pred xx.x%" labels on SuperTrend flips                          |
//+------------------------------------------------------------------+
bool IsTrendFlip(const int t)
  {
   return(t > 0 && Direction[t] != Direction[t - 1]);
  }

//--- str.tostring(prob * 100, "#.#") + "%"
string FormatPct(const double prob)
  {
   string s = DoubleToString(prob * 100.0, 1);
   int n = StringLen(s);
   if(n > 2 && StringSubstr(s, n - 2) == ".0")
      s = StringSubstr(s, 0, n - 2);
   return(s + "%");
  }

//--- creates, updates or removes the label of bar t; true if a label was created
bool SyncLabel(const int t, const datetime &time[], const double &high[], const double &low[], const bool mayExist)
  {
   string name = g_prefix + IntegerToString((long)time[t]);
   if(!IsTrendFlip(t))
     {
      if(mayExist)
         ObjectDelete(0, name);
      return(false);
     }
   bool   bull   = Direction[t] < 0;
   double offset = IsNa(Atr[t]) ? 0.0 : 0.75 * Atr[t];   // keep clear of the arrows
   double price  = bull ? low[t] - offset : high[t] + offset;
   bool created = false;
   if(ObjectFind(0, name) < 0)
     {
      if(!ObjectCreate(0, name, OBJ_TEXT, 0, time[t], price))
         return(false);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
      ObjectSetString(0, name, OBJPROP_FONT, "Arial");
      created = true;
     }
   ObjectMove(0, name, 0, time[t], price);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, bull ? ANCHOR_UPPER : ANCHOR_LOWER);
   ObjectSetInteger(0, name, OBJPROP_COLOR, bull ? InpBullColor : InpBearColor);
   ObjectSetString(0, name, OBJPROP_TEXT, "Pred " + FormatPct(bull ? ProbUp[t] : ProbDown[t]));
   return(created);
  }

//--- keep only the newest InpMaxLabels labels (Pine: max_labels_count)
void PruneLabels()
  {
   long times[];
   int  count = 0;
   int  total = ObjectsTotal(0, 0, OBJ_TEXT);
   ArrayResize(times, total);
   for(int i = 0; i < total; i++)
     {
      string name = ObjectName(0, i, 0, OBJ_TEXT);
      if(StringFind(name, g_prefix) == 0)
         times[count++] = ObjectGetInteger(0, name, OBJPROP_TIME);
     }
   if(count <= InpMaxLabels)
      return;
   ArrayResize(times, count);
   ArraySort(times);
   for(int i = 0; i < count - InpMaxLabels; i++)
      ObjectDelete(0, g_prefix + IntegerToString(times[i]));
  }

void UpdateLabels(const int start, const int rates_total, const datetime &time[], const double &high[], const double &low[])
  {
   if(!InpPredLabels || InpMaxLabels <= 0)
      return;
   int  from     = start;
   bool fullCalc = start == 0;
   if(fullCalc)
     {
      int found = 0;
      from = rates_total;
      for(int t = rates_total - 1; t > 0 && found < InpMaxLabels; t--)
         if(IsTrendFlip(t))
           {
            found++;
            from = t;
           }
     }
   bool created = false;
   for(int t = from; t < rates_total; t++)
      if(SyncLabel(t, time, high, low, !fullCalc))
         created = true;
   if(created && !fullCalc)
      PruneLabels();
  }

//+------------------------------------------------------------------+
//| Alerts (Pine alertcondition "Long" / "Short")                    |
//+------------------------------------------------------------------+
void CheckAlerts(const int rates_total, const datetime &time[], const bool initial)
  {
   if(!InpAlertPopup && !InpAlertPush && !InpAlertEmail)
      return;
   int t = InpAlertOnClose ? rates_total - 2 : rates_total - 1;
   if(t < 1 || time[t] == g_lastAlertTime)
      return;
   bool bull = SignalState[t] > 0 && SignalState[t - 1] <= 0;
   bool bear = SignalState[t] < 0 && SignalState[t - 1] >= 0;
   if(!bull && !bear)
      return;
   g_lastAlertTime = time[t];
   if(initial)                 // no alerts for history on the first calculation
      return;

   string tf  = StringSubstr(EnumToString((ENUM_TIMEFRAMES)_Period), 7);
   string msg = StringFormat("AI-SuperTrend %s %s: %s", _Symbol, tf,
                             bull ? "Bullish Signal with AI Confirmation" : "Bearish Signal with AI Confirmation");
   if(InpAlertPopup)
      Alert(msg);
   if(InpAlertPush)
      SendNotification(msg);
   if(InpAlertEmail)
      SendMail("AI-SuperTrend " + _Symbol, msg);
  }

//+------------------------------------------------------------------+
//| Custom indicator initialization function                         |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpAtrPeriod < 1 || InpFactor < 0.01 || InpNeighbors < 1 || InpSamplingWindow < 10 ||
      InpStride < 1 || InpProbThreshold < 0.1 || InpProbThreshold > 1.0 ||
      InpRsiLen < 1 || InpMaLen < 1 || InpSignalLen < 1 || InpChopLen < 2 ||
      InpNormWindow < 10 || InpMinkowskiP <= 0.0 ||
      InpFillOpacity < 0 || InpFillOpacity > 100 || InpMaxLabels < 0)
     {
      Print("AI-SuperTrend KNN: invalid input parameters");
      return(INIT_PARAMETERS_INCORRECT);
     }

   int b = 0;
   SetIndexBuffer(b++, UpFillLow,     INDICATOR_DATA);
   SetIndexBuffer(b++, UpFillTrend,   INDICATOR_DATA);
   SetIndexBuffer(b++, DnFillHigh,    INDICATOR_DATA);
   SetIndexBuffer(b++, DnFillTrend,   INDICATOR_DATA);
   SetIndexBuffer(b++, BarOpen,       INDICATOR_DATA);
   SetIndexBuffer(b++, BarHigh,       INDICATOR_DATA);
   SetIndexBuffer(b++, BarLow,        INDICATOR_DATA);
   SetIndexBuffer(b++, BarClose,      INDICATOR_DATA);
   SetIndexBuffer(b++, BarColor,      INDICATOR_COLOR_INDEX);
   SetIndexBuffer(b++, UpTrend,       INDICATOR_DATA);
   SetIndexBuffer(b++, DnTrend,       INDICATOR_DATA);
   SetIndexBuffer(b++, StLong,        INDICATOR_DATA);
   SetIndexBuffer(b++, StLongColor,   INDICATOR_COLOR_INDEX);
   SetIndexBuffer(b++, StShort,       INDICATOR_DATA);
   SetIndexBuffer(b++, StShortColor,  INDICATOR_COLOR_INDEX);
   SetIndexBuffer(b++, MajorLong,     INDICATOR_DATA);
   SetIndexBuffer(b++, MajorShort,    INDICATOR_DATA);
   SetIndexBuffer(b++, ProbUp,        INDICATOR_DATA);
   SetIndexBuffer(b++, ProbDown,      INDICATOR_DATA);
   SetIndexBuffer(b++, SignalState,   INDICATOR_DATA);
   SetIndexBuffer(b++, Direction,     INDICATOR_DATA);

   SetIndexBuffer(b++, TrueRange,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Atr,           INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, UpperBand,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, LowerBand,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, SuperTrendRaw, INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Target,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Gain,          INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Loss,          INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, AvgGain,       INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, AvgLoss,       INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Rsi,           INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, RsiSignal,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, RsiSigDist,    INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaTmp1,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaTmp2,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaTmp3,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, FeatMa,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaDev,         INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Chop,          INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, RsiCnt,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, RsiSum,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, RsiSq,         INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, RsiZ,          INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaDevCnt,      INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaDevSum,      INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaDevSq,       INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MaDevZ,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, SigDistCnt,    INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, SigDistSum,    INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, SigDistSq,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, SigDistZ,      INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopCnt,       INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopSum,       INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopSq,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopZ,         INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MomIn,         INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MomCnt,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MomSum,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MomSq,         INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, MomZ,          INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopIn,        INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopInCnt,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopInSum,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopInSq,      INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, ChopInZ,       INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Pc1,           INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Pc2,           INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Pc3,           INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, Pc4,           INDICATOR_CALCULATIONS);
   SetIndexBuffer(b++, LastDir,       INDICATOR_CALCULATIONS);

   for(int p = 0; p < PL_COUNT; p++)
      PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);

//--- trend fills: no transparency in MT5, so blend the trend colour with the background
   color bg     = (color)ChartGetInteger(0, CHART_COLOR_BACKGROUND);
   color upFill = Blend(bg, InpBullColor, InpFillOpacity / 100.0);
   color dnFill = Blend(bg, InpBearColor, InpFillOpacity / 100.0);
   PlotIndexSetInteger(PL_UP_FILL, PLOT_LINE_COLOR, 0, upFill);
   PlotIndexSetInteger(PL_UP_FILL, PLOT_LINE_COLOR, 1, upFill);
   PlotIndexSetInteger(PL_DN_FILL, PLOT_LINE_COLOR, 0, dnFill);
   PlotIndexSetInteger(PL_DN_FILL, PLOT_LINE_COLOR, 1, dnFill);
   PlotIndexSetInteger(PL_UP_FILL, PLOT_SHOW_DATA, false);
   PlotIndexSetInteger(PL_DN_FILL, PLOT_SHOW_DATA, false);

//--- bar colours: neutral -> bull (0..STEPS), neutral -> bear (STEPS+1..2*STEPS+1)
   PlotIndexSetInteger(PL_BARS, PLOT_COLOR_INDEXES, 2 * (GRADIENT_STEPS + 1));
   for(int i = 0; i <= GRADIENT_STEPS; i++)
     {
      double f = (double)i / GRADIENT_STEPS;
      PlotIndexSetInteger(PL_BARS, PLOT_LINE_COLOR, i, Blend(InpNeutralColor, InpBullColor, f));
      PlotIndexSetInteger(PL_BARS, PLOT_LINE_COLOR, GRADIENT_STEPS + 1 + i, Blend(InpNeutralColor, InpBearColor, f));
     }
   PlotIndexSetInteger(PL_BARS, PLOT_SHOW_DATA, false);

   PlotIndexSetInteger(PL_UP_TREND, PLOT_LINE_COLOR, InpBullColor);
   PlotIndexSetInteger(PL_DN_TREND, PLOT_LINE_COLOR, InpBearColor);

//--- SuperTrend flip circles, coloured by the confirmed signal state
   for(int p = PL_ST_LONG; p <= PL_ST_SHORT; p++)
     {
      PlotIndexSetInteger(p, PLOT_ARROW, 108);
      PlotIndexSetInteger(p, PLOT_COLOR_INDEXES, 2);
      PlotIndexSetInteger(p, PLOT_LINE_COLOR, 0, InpBullColor);
      PlotIndexSetInteger(p, PLOT_LINE_COLOR, 1, InpBearColor);
     }

   PlotIndexSetInteger(PL_MAJOR_LONG, PLOT_ARROW, 233);
   PlotIndexSetInteger(PL_MAJOR_LONG, PLOT_ARROW_SHIFT, 12);
   PlotIndexSetInteger(PL_MAJOR_LONG, PLOT_LINE_COLOR, InpBullColor);
   PlotIndexSetInteger(PL_MAJOR_SHORT, PLOT_ARROW, 234);
   PlotIndexSetInteger(PL_MAJOR_SHORT, PLOT_ARROW_SHIFT, -12);
   PlotIndexSetInteger(PL_MAJOR_SHORT, PLOT_LINE_COLOR, InpBearColor);

   IndicatorSetString(INDICATOR_SHORTNAME,
                      StringFormat("AI-SuperTrend KNN (%d, %.2f, K=%d)", InpAtrPeriod, InpFactor, InpNeighbors));
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);

   ArrayResize(g_topDist, InpNeighbors);
   ArrayResize(g_topLabel, InpNeighbors);
   g_prefix        = "AISTKNN_" + IntegerToString((long)(GetMicrosecondCount() % 1000000)) + "_";
   g_lastAlertTime = 0;
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Custom indicator deinitialization function                       |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   ObjectsDeleteAll(0, g_prefix);
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| Custom indicator iteration function                              |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(rates_total < 2)
      return(0);
//--- every value of bar t only depends on bars <= t, so the forming bar can be recalculated alone
   int start = prev_calculated > 0 ? prev_calculated - 1 : 0;
   if(start == 0)
      ObjectsDeleteAll(0, g_prefix);

   for(int t = start; t < rates_total; t++)
     {
      if(IsStopped())
         return(0);
      CalcSupertrend(t, high, low, close);
      CalcFeatures(t, high, low, close);
      CalcComponents(t);
      CalcKnn(t);
      CalcSignals(t);
      CalcVisuals(t, open, high, low, close);
     }

   UpdateLabels(start, rates_total, time, high, low);
   CheckAlerts(rates_total, time, prev_calculated == 0);
   return(rates_total);
  }
//+------------------------------------------------------------------+
