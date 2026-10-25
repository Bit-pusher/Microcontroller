// Runs AI_SuperTrend_KNN.mq5 (translated by convert.py) on a CSV of bars and
// writes the buffers the backtest needs.
// usage: runner bars.csv out.csv [input=value ...]
// bars.csv: time,o,h,l,c[,...]  (first five columns are used)
#include "shim.h"
#include "indicator.cpp"
#include <fstream>
#include <sstream>

static void setInput(const std::string& k, const std::string& v) {
  double d = atof(v.c_str()); int i = atoi(v.c_str());
  if(k == "atr") InpAtrPeriod = i;
  else if(k == "factor") InpFactor = d;
  else if(k == "k") InpNeighbors = i;
  else if(k == "sampling") InpSamplingWindow = i;
  else if(k == "stride") InpStride = i;
  else if(k == "thr") InpProbThreshold = d;
  else if(k == "ma") InpFeatMaType = (ENUM_FEATURE_MA)i;
  else if(k == "rsi") InpRsiLen = i;
  else if(k == "malen") InpMaLen = i;
  else if(k == "sig") InpSignalLen = i;
  else if(k == "chop") InpChopLen = i;
  else if(k == "norm") InpNormWindow = i;
  else if(k == "p") InpMinkowskiP = d;
  else if(k == "w") InpShapeParam = d;
  else if(k == "pca") InpUsePca = i != 0;
  else { fprintf(stderr, "unknown input %s\n", k.c_str()); exit(2); }
}

int main(int argc, char** argv) {
  if(argc < 3) { fprintf(stderr, "usage: runner bars.csv out.csv [input=value ...]\n"); return 2; }
  Arr<datetime> T; Arr<double> O, H, L, C; Arr<long> V; Arr<int> S;
  std::ifstream in(argv[1]); std::string line; std::getline(in, line);
  while(std::getline(in, line)) {
    std::stringstream ss(line); std::string f; std::vector<std::string> c;
    while(std::getline(ss, f, ',')) c.push_back(f);
    T.v.push_back(atoll(c[0].c_str())); O.v.push_back(atof(c[1].c_str())); H.v.push_back(atof(c[2].c_str()));
    L.v.push_back(atof(c[3].c_str())); C.v.push_back(atof(c[4].c_str()));
  }
  for(int a = 3; a < argc; a++) { std::string s = argv[a]; auto p = s.find('='); setInput(s.substr(0, p), s.substr(p + 1)); }
  InpPredLabels = false;
  if(OnInit() != INIT_SUCCEEDED) { fprintf(stderr, "OnInit failed\n"); return 3; }
  const int n = (int)C.v.size();
  for(auto* b : g_buffers) b->v.resize(n, std::nan(""));
  V.v.resize(n); S.v.resize(n);
  if(OnCalculate(n, 0, T, O, H, L, C, V, V, S) != n) { fprintf(stderr, "OnCalculate failed\n"); return 4; }
  FILE* f = fopen(argv[2], "w");
  fprintf(f, "time,direction,supertrend,prob_up,prob_down,state,atr\n");
  auto num = [](double v) { return v == EMPTY_VALUE ? std::nan("") : v; };
  for(int t = 0; t < n; t++)
    fprintf(f, "%lld,%g,%.10g,%.10g,%.10g,%g,%.10g\n", T[t], Direction[t], num(SuperTrendRaw[t]),
            ProbUp[t], ProbDown[t], SignalState[t], num(Atr[t]));
  fclose(f);
  return 0;
}
