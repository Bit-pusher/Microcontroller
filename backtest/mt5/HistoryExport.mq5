//+------------------------------------------------------------------+
//|                                                HistoryExport.mq5 |
//|  Exports tick data, M1 bars and symbol specifications of the     |
//|  connected account to CSV files, as reference data for the       |
//|  Python backtests in this repository.                            |
//|                                                                  |
//|  Output (MQL5\Files or Common\Files):                            |
//|    <folder>\<server>\export_info.txt   server, time offset, ...  |
//|    <folder>\<server>\symbols.csv       specifications, sessions  |
//|    <folder>\<server>\<symbol>\<symbol>_M1_<yyyy>.csv             |
//|    <folder>\<server>\<symbol>\ticks\<symbol>_ticks_<yyyy-mm>.csv |
//|  All times are server time: M1 "time" in seconds, ticks          |
//|  "time_msc" in milliseconds since 1970-01-01.                    |
//|                                                                  |
//|  Each file is written as <name>.part and renamed when complete,  |
//|  so an interrupted run can simply be started again: finished     |
//|  months / years are skipped (input "InpSkipDone").               |
//|  A file that covers only part of its year / month ends in        |
//|  "_partial" and is never skipped; the complete file of the same  |
//|  period replaces it.                                             |
//+------------------------------------------------------------------+
#property version     "1.02"
#property description "Exportiert Ticks, M1-Kerzen und Symbolspezifikationen als CSV."
#property description "Alle Zeiten in Serverzeit. Abgebrochene Läufe können neu gestartet werden."
#property script_show_inputs

enum ENUM_EXPORT_SOURCE
  {
   EXPORT_LIST,          // Symbolliste (Eingabe unten)
   EXPORT_MARKET_WATCH,  // alle Symbole der Marktübersicht
   EXPORT_ALL            // alle Symbole des Servers
  };

enum ENUM_EXPORT_TICKS
  {
   EXPORT_TICKS_ALL,     // alle Ticks
   EXPORT_TICKS_INFO,    // nur Bid/Ask-Änderungen
   EXPORT_TICKS_TRADE    // nur Last/Volumen (Börsensymbole)
  };

input ENUM_EXPORT_SOURCE InpSource   = EXPORT_LIST;          // Symbole
input string             InpSymbols  = "EURUSD,XAUUSD";      // Symbolliste, durch Kommas getrennt
input datetime           InpFrom     = D'2015.01.01 00:00';  // Von (Serverzeit)
input datetime           InpTo       = 0;                    // Bis (Serverzeit, 0 = jetzt)
input bool               InpTicks    = true;                 // Ticks exportieren
input ENUM_EXPORT_TICKS  InpTickKind = EXPORT_TICKS_ALL;     // Tick-Art
input bool               InpM1       = true;                 // M1-Kerzen exportieren
input bool               InpSpecs    = true;                 // Symbolspezifikationen exportieren
input string             InpFolder   = "HistoryExport";      // Zielordner
input bool               InpCommon   = true;                 // Gemeinsamer Datenordner (Common\Files)
input bool               InpSkipDone = true;                 // Fertige Dateien überspringen (Fortsetzen)
input int                InpRetries  = 5;                    // Wiederholungen beim Nachladen der Historie

#define LINES_PER_WRITE 2000

int      g_common      = 0;     // FILE_COMMON or 0
string   g_root        = "";    // <folder>\<server>
datetime g_to          = 0;     // end of the export range (server time)
long     g_ticks_total = 0;
long     g_bars_total  = 0;
int      g_failed      = 0;

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
string SafeName(string s)
  {
   string bad = "\\/:*?\"<>| ";
   for(int i = 0; i < StringLen(bad); i++)
      StringReplace(s, StringSubstr(bad, i, 1), "_");
   return s;
  }

void EnsureFolder(const string path)
  {
   string parts[];
   int n = StringSplit(path, '\\', parts);
   string current = "";
   for(int i = 0; i < n; i++)
     {
      if(parts[i] == "")
         continue;
      current = (current == "") ? parts[i] : current + "\\" + parts[i];
      FolderCreate(current, g_common);          // fails harmlessly when the folder exists
     }
  }

void Push(string &arr[], const string value)
  {
   int n = ArraySize(arr);
   ArrayResize(arr, n + 1, 64);
   arr[n] = value;
  }

// number without trailing zeros (volumes, specifications)
string Num(const double value)
  {
   if(value == 0.0)
      return "0";
   string s = DoubleToString(value, 8);
   int len = StringLen(s);
   while(len > 1 && StringGetCharacter(s, len - 1) == '0')
      len--;
   if(StringGetCharacter(s, len - 1) == '.')
      len--;
   return StringSubstr(s, 0, len);
  }

datetime MonthStart(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t, d);
   d.day  = 1;
   d.hour = 0;
   d.min  = 0;
   d.sec  = 0;
   return StructToTime(d);
  }

datetime NextMonth(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(MonthStart(t), d);
   d.mon++;
   if(d.mon > 12)
     {
      d.mon = 1;
      d.year++;
     }
   return StructToTime(d);
  }

datetime YearStart(const int year)
  {
   MqlDateTime d;
   ZeroMemory(d);
   d.year = year;
   d.mon  = 1;
   d.day  = 1;
   return StructToTime(d);
  }

int YearOf(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t, d);
   return d.year;
  }

string MonthLabel(const datetime t)
  {
   MqlDateTime d;
   TimeToStruct(t, d);
   return StringFormat("%04d-%02d", d.year, d.mon);
  }

uint TickFlags()
  {
   if(InpTickKind == EXPORT_TICKS_INFO)
      return (uint)COPY_TICKS_INFO;
   if(InpTickKind == EXPORT_TICKS_TRADE)
      return (uint)COPY_TICKS_TRADE;
   return (uint)COPY_TICKS_ALL;
  }

// moves a finished .part file to its final name, or removes it when it holds no data
bool Finish(const string tmp, const string name, const long count)
  {
   if(count == 0)
     {
      FileDelete(tmp, g_common);
      return true;
     }
   if(!FileMove(tmp, g_common, name, FILE_REWRITE | g_common))
     {
      PrintFormat("Umbenennen %s -> %s fehlgeschlagen, Fehler %d", tmp, name, GetLastError());
      g_failed++;
      return false;
     }
   return true;
  }

// file of a whole year / month, or of only part of it ("_partial", never skipped as finished)
string PeriodFile(const string base, const bool partial)
  {
   return base + (partial ? "_partial.csv" : ".csv");
  }

// a complete file replaces the partial one of the same period
void DeletePartial(const string base)
  {
   string name = base + "_partial.csv";
   if(FileIsExist(name, g_common) && FileDelete(name, g_common))
      PrintFormat("%s ersetzt durch die vollständige Datei", name);
  }

//+------------------------------------------------------------------+
//| Symbols                                                          |
//+------------------------------------------------------------------+
int CollectSymbols(string &out[])
  {
   ArrayResize(out, 0);
   if(InpSource == EXPORT_LIST)
     {
      string parts[];
      int n = StringSplit(InpSymbols, ',', parts);
      for(int i = 0; i < n; i++)
        {
         string s = parts[i];
         StringTrimLeft(s);
         StringTrimRight(s);
         if(s == "")
            continue;
         bool custom = false;
         if(!SymbolExist(s, custom))
           {
            PrintFormat("Symbol %s gibt es auf diesem Server nicht, übersprungen", s);
            continue;
           }
         Push(out, s);
        }
     }
   else
     {
      bool selected = (InpSource == EXPORT_MARKET_WATCH);
      int total = SymbolsTotal(selected);
      for(int i = 0; i < total; i++)
         Push(out, SymbolName(i, selected));
     }
   return ArraySize(out);
  }

// Waits up to 60 s until the terminal is connected and every symbol has a quote and a tick value.
// Started together with the terminal, the script would otherwise write a server time offset of 0
// to export_info.txt and tick values of 0 to symbols.csv.
void WaitForQuotes(const string &symbols[])
  {
   int n = ArraySize(symbols);
   for(int i = 0; i < n; i++)
      SymbolSelect(symbols[i], true);
   uint   t0      = GetTickCount();
   int    missing = 0;
   string names   = "";
   while(!IsStopped())
     {
      missing = 0;
      names   = "";
      if(!TerminalInfoInteger(TERMINAL_CONNECTED))
        {
         missing = n;
         names   = "keine Verbindung";
        }
      else
         for(int i = 0; i < n; i++)
           {
            MqlTick tick;
            if(SymbolInfoTick(symbols[i], tick) && tick.bid > 0
               && SymbolInfoDouble(symbols[i], SYMBOL_TRADE_TICK_VALUE) > 0)
               continue;
            if(++missing <= 10)
               names += (names == "" ? "" : ",") + symbols[i];
           }
      if(missing == 0 || GetTickCount() - t0 > 60000)
         break;
      Comment(StringFormat("HistoryExport  warte auf Verbindung und Kurse (%s)", names));
      Sleep(500);
     }
   if(missing > 0 && !IsStopped())
      PrintFormat("Warnung: nach 60 s fehlen noch Kurse oder Tickwerte für %d Symbole (%s). Serverzeit in "
                  "export_info.txt und Tickwerte in symbols.csv können falsch sein.", missing, names);
  }

string Sessions(const string sym)
  {
   string days[7] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
   string out = "";
   for(int d = 0; d < 7; d++)
     {
      for(uint k = 0; k < 16; k++)
        {
         datetime from = 0, to = 0;
         if(!SymbolInfoSessionTrade(sym, (ENUM_DAY_OF_WEEK)d, k, from, to))
            break;
         string end = (to >= 86400) ? "24:00" : TimeToString(to, TIME_MINUTES);
         out += StringFormat("%s %s-%s ", days[d], TimeToString(from, TIME_MINUTES), end);
        }
     }
   return out;
  }

string Text(string s)
  {
   StringReplace(s, ";", ",");
   StringReplace(s, "\r", " ");
   StringReplace(s, "\n", " ");
   return s;
  }

void ExportSpecs(const string &symbols[])
  {
   string name = g_root + "\\symbols.csv";
   int h = FileOpen(name, FILE_WRITE | FILE_TXT | FILE_ANSI | g_common);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("%s nicht anlegbar, Fehler %d", name, GetLastError());
      g_failed++;
      return;
     }
   FileWriteString(h, "symbol;description;path;currency_base;currency_profit;currency_margin;digits;point;"
                   "tick_size;tick_value;contract_size;volume_min;volume_step;volume_max;spread_now;spread_float;"
                   "calc_mode;trade_mode;swap_mode;swap_long;swap_short;swap_3days;stops_level;margin_initial;"
                   "sessions_server_time\r\n");
   for(int i = 0; i < ArraySize(symbols); i++)
     {
      string s = symbols[i];
      string row = s
                   + ";" + Text(SymbolInfoString(s, SYMBOL_DESCRIPTION))
                   + ";" + Text(SymbolInfoString(s, SYMBOL_PATH))
                   + ";" + SymbolInfoString(s, SYMBOL_CURRENCY_BASE)
                   + ";" + SymbolInfoString(s, SYMBOL_CURRENCY_PROFIT)
                   + ";" + SymbolInfoString(s, SYMBOL_CURRENCY_MARGIN)
                   + ";" + IntegerToString(SymbolInfoInteger(s, SYMBOL_DIGITS))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_POINT))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_TRADE_TICK_VALUE))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_VOLUME_MIN))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_VOLUME_STEP))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_VOLUME_MAX))
                   + ";" + IntegerToString(SymbolInfoInteger(s, SYMBOL_SPREAD))
                   + ";" + IntegerToString(SymbolInfoInteger(s, SYMBOL_SPREAD_FLOAT))
                   + ";" + EnumToString((ENUM_SYMBOL_CALC_MODE)SymbolInfoInteger(s, SYMBOL_TRADE_CALC_MODE))
                   + ";" + EnumToString((ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(s, SYMBOL_TRADE_MODE))
                   + ";" + EnumToString((ENUM_SYMBOL_SWAP_MODE)SymbolInfoInteger(s, SYMBOL_SWAP_MODE))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_SWAP_LONG))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_SWAP_SHORT))
                   + ";" + EnumToString((ENUM_DAY_OF_WEEK)SymbolInfoInteger(s, SYMBOL_SWAP_ROLLOVER3DAYS))
                   + ";" + IntegerToString(SymbolInfoInteger(s, SYMBOL_TRADE_STOPS_LEVEL))
                   + ";" + Num(SymbolInfoDouble(s, SYMBOL_MARGIN_INITIAL))
                   + ";" + Sessions(s)
                   + "\r\n";
      FileWriteString(h, row);
     }
   FileClose(h);
  }

void ExportInfo(const int symbol_count)
  {
   string name = g_root + "\\export_info.txt";
   int h = FileOpen(name, FILE_WRITE | FILE_TXT | FILE_ANSI | g_common);
   if(h == INVALID_HANDLE)
      return;
   long offset = (long)TimeTradeServer() - (long)TimeGMT();
   offset = (long)MathRound(offset / 900.0) * 900;              // server time - UTC, in 15-minute steps
   FileWriteString(h, "company=" + AccountInfoString(ACCOUNT_COMPANY) + "\r\n");
   FileWriteString(h, "server=" + AccountInfoString(ACCOUNT_SERVER) + "\r\n");
   FileWriteString(h, "terminal_build=" + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)) + "\r\n");
   FileWriteString(h, "export_time_server=" + TimeToString(TimeTradeServer(), TIME_DATE | TIME_SECONDS) + "\r\n");
   FileWriteString(h, "export_time_utc=" + TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS) + "\r\n");
   FileWriteString(h, StringFormat("server_utc_offset_hours_now=%+.2f\r\n", offset / 3600.0));
   FileWriteString(h, "from=" + TimeToString(InpFrom, TIME_DATE | TIME_MINUTES) + "\r\n");
   FileWriteString(h, "to=" + TimeToString(g_to, TIME_DATE | TIME_MINUTES) + "\r\n");
   FileWriteString(h, "symbols=" + IntegerToString(symbol_count) + "\r\n");
   FileWriteString(h, "ticks=" + (InpTicks ? EnumToString(InpTickKind) : "no") + "\r\n");
   FileWriteString(h, "m1=" + (InpM1 ? "yes" : "no") + "\r\n");
   FileWriteString(h, "account_currency=" + AccountInfoString(ACCOUNT_CURRENCY) + "\r\n");
   FileWriteString(h, "times=server time; M1 time in seconds, ticks time_msc in milliseconds since 1970-01-01\r\n");
   FileWriteString(h, "m1_spread=minimum spread of the bar in points\r\n");
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| History requests with retries (the terminal loads history from   |
//| the server on demand)                                            |
//+------------------------------------------------------------------+
int CopyTicksRetry(const string sym, MqlTick &ticks[], const long from_msc, const long to_msc)
  {
   for(int attempt = 0; attempt <= InpRetries && !IsStopped(); attempt++)
     {
      ResetLastError();
      int n = CopyTicksRange(sym, ticks, TickFlags(), (ulong)from_msc, (ulong)to_msc);
      int err = GetLastError();
      if(n >= 0 && err != ERR_HISTORY_TIMEOUT)
         return n;
      PrintFormat("%s Ticks %s: Versuch %d, Ergebnis %d, Fehler %d", sym,
                  TimeToString((datetime)(from_msc / 1000), TIME_DATE), attempt + 1, n, err);
      Sleep(1000 * (attempt + 1));
     }
   return -1;
  }

int CopyRatesRetry(const string sym, const datetime from, const datetime to, MqlRates &rates[])
  {
   int err = 0;
   for(int attempt = 0; attempt <= InpRetries && !IsStopped(); attempt++)
     {
      ResetLastError();
      int n = CopyRates(sym, PERIOD_M1, from, to, rates);
      if(n >= 0)
         return n;
      err = GetLastError();
      if(err == ERR_HISTORY_BARS_LIMIT)
         Print("Hinweis: Extras > Optionen > Charts > \"Max. Bars im Chart\" auf Unlimited stellen "
               "und MetaTrader neu starten");
      PrintFormat("%s M1 %s: Versuch %d, Fehler %d", sym, TimeToString(from, TIME_DATE), attempt + 1, err);
      Sleep(1000 * (attempt + 1));
     }
   if(err == ERR_HISTORY_NOT_FOUND)
      return 0;                                    // no bars in this range (gap in the history)
   return -1;
  }

datetime FirstBarDate(const string sym)
  {
   long first = 0;
   for(int k = 0; k < 20 && first == 0 && !IsStopped(); k++)
     {
      if(!SeriesInfoInteger(sym, PERIOD_M1, SERIES_SERVER_FIRSTDATE, first) || first == 0)
        {
         first = 0;
         Sleep(500);
        }
     }
   return (datetime)first;
  }

// Makes the terminal download the M1 history back to "start" (pattern "CheckLoadHistory" in the
// MQL5 documentation). CopyRates by date fails with 4401 for ranges older than the oldest bar in
// the terminal and loads nothing; requesting the bars beyond the oldest one by position does.
// Returns the oldest M1 bar in the terminal afterwards, 0 when there is none.
datetime LoadM1History(const string sym, const datetime start, const string progress)
  {
   long     maxbars   = TerminalInfoInteger(TERMINAL_MAXBARS);
   long     first     = 0;
   int      last_bars = 0;
   uint     last_gain = GetTickCount();
   datetime times[];
   while(!IsStopped())
     {
      for(int k = 0; k < 200 && !SeriesInfoInteger(sym, PERIOD_M1, SERIES_SYNCHRONIZED) && !IsStopped(); k++)
         Sleep(50);                                // the series is still being built
      int bars = Bars(sym, PERIOD_M1);
      if(!SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE, first))
         first = 0;
      if(bars > 0 && first > 0 && (datetime)first <= start)
         break;
      if(bars >= maxbars)
        {
         Print("Hinweis: Extras > Optionen > Charts > \"Max. Bars im Chart\" auf Unlimited stellen "
               "und MetaTrader neu starten");
         break;
        }
      bool grew = (bars > last_bars);
      if(grew)
        {
         last_bars = bars;
         last_gain = GetTickCount();
        }
      else if(GetTickCount() - last_gain > 60000)
         break;                                    // nothing older arrived from the server for a minute
      Comment(StringFormat("HistoryExport  %s  %s M1 nachladen, im Terminal ab %s", progress, sym,
                           first > 0 ? TimeToString((datetime)first, TIME_DATE) : "-"));
      CopyTime(sym, PERIOD_M1, bars, 1000, times);  // bars beyond the oldest one: starts the download
      if(!grew)
         Sleep(100);
     }
   if(!SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE, first))
      first = 0;
   return (datetime)first;
  }

//+------------------------------------------------------------------+
//| Exports                                                          |
//+------------------------------------------------------------------+
bool ExportM1Year(const string sym, const int year, const datetime server_first, const datetime first_bar,
                  const int digits)
  {
   datetime y0 = YearStart(year), y1 = YearStart(year + 1);
   datetime a = (y0 < InpFrom) ? InpFrom : y0;
   datetime b = (y1 > g_to) ? g_to : y1;
   if(first_bar > a)
      a = first_bar;
   if(a >= b)
      return true;
   // the start of the server history does not make a year partial; "Von", "Bis" or a shorter local history do
   datetime full = (server_first > y0) ? server_first : y0;
   bool partial = (a > full || b != y1);
   string dir  = g_root + "\\" + SafeName(sym);
   string base = StringFormat("%s\\%s_M1_%04d", dir, SafeName(sym), year);
   string name = PeriodFile(base, partial);
   if(InpSkipDone && !partial && FileIsExist(name, g_common))
      return true;
   EnsureFolder(dir);
   string tmp = name + ".part";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | g_common);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("%s nicht anlegbar, Fehler %d", tmp, GetLastError());
      g_failed++;
      return false;
     }
   FileWriteString(h, "time,open,high,low,close,tick_volume,spread,real_volume\r\n");
   MqlRates rates[];
   long count = 0;
   for(datetime m = a; m < b && !IsStopped(); m = NextMonth(m))
     {
      datetime e = NextMonth(m);
      if(e > b)
         e = b;
      int n = CopyRatesRetry(sym, m, e - 1, rates);
      if(n < 0)
        {
         FileClose(h);
         FileDelete(tmp, g_common);
         PrintFormat("%s M1 %04d: Historie nicht verfügbar, beim nächsten Lauf erneut versucht", sym, year);
         g_failed++;
         return false;
        }
      string buf = "";
      int lines = 0;
      for(int i = 0; i < n; i++)
        {
         if(rates[i].time < m || rates[i].time >= e)
            continue;
         StringAdd(buf, IntegerToString((long)rates[i].time) + ","
                   + DoubleToString(rates[i].open, digits) + "," + DoubleToString(rates[i].high, digits) + ","
                   + DoubleToString(rates[i].low, digits) + "," + DoubleToString(rates[i].close, digits) + ","
                   + IntegerToString(rates[i].tick_volume) + "," + IntegerToString(rates[i].spread) + ","
                   + IntegerToString(rates[i].real_volume) + "\r\n");
         count++;
         if(++lines == LINES_PER_WRITE)
           {
            FileWriteString(h, buf);
            buf = "";
            lines = 0;
           }
        }
      if(lines > 0)
         FileWriteString(h, buf);
     }
   FileClose(h);
   if(IsStopped())
     {
      FileDelete(tmp, g_common);
      return false;
     }
   g_bars_total += count;
   PrintFormat("%s M1 %04d: %I64d Kerzen", sym, year, count);
   if(!Finish(tmp, name, count))
      return false;
   if(!partial && count > 0)
      DeletePartial(base);
   return true;
  }

bool ExportTicksMonth(const string sym, const datetime month, const int digits, const string progress)
  {
   datetime m0 = MonthStart(month), m1 = NextMonth(month);
   datetime a = (m0 < InpFrom) ? InpFrom : m0;
   datetime b = (m1 > g_to) ? g_to : m1;
   if(a >= b)
      return true;
   bool partial = (a != m0 || b != m1);
   string dir  = g_root + "\\" + SafeName(sym) + "\\ticks";
   string base = StringFormat("%s\\%s_ticks_%s", dir, SafeName(sym), MonthLabel(m0));
   string name = PeriodFile(base, partial);
   if(InpSkipDone && !partial && FileIsExist(name, g_common))
      return true;
   EnsureFolder(dir);
   string tmp = name + ".part";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | g_common);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("%s nicht anlegbar, Fehler %d", tmp, GetLastError());
      g_failed++;
      return false;
     }
   FileWriteString(h, "time_msc,bid,ask,last,volume_real,flags\r\n");
   MqlTick ticks[];
   long count = 0;
   for(datetime d = a; d < b && !IsStopped(); d += 86400)
     {
      datetime e = d + 86400;
      if(e > b)
         e = b;
      Comment(StringFormat("HistoryExport  %s  %s Ticks %s  (%I64d Ticks bisher)", progress, sym,
                           TimeToString(d, TIME_DATE), g_ticks_total + count));
      long from_msc = (long)d * 1000, to_msc = (long)e * 1000 - 1;
      int n = CopyTicksRetry(sym, ticks, from_msc, to_msc);
      if(n < 0)
        {
         FileClose(h);
         FileDelete(tmp, g_common);
         PrintFormat("%s Ticks %s: Historie nicht verfügbar, beim nächsten Lauf erneut versucht", sym, MonthLabel(m0));
         g_failed++;
         return false;
        }
      string buf = "";
      int lines = 0;
      for(int i = 0; i < n; i++)
        {
         if(ticks[i].time_msc < from_msc || ticks[i].time_msc > to_msc)
            continue;                               // the range is inclusive: no tick twice
         StringAdd(buf, IntegerToString(ticks[i].time_msc) + ","
                   + DoubleToString(ticks[i].bid, digits) + "," + DoubleToString(ticks[i].ask, digits) + ","
                   + DoubleToString(ticks[i].last, digits) + "," + Num(ticks[i].volume_real) + ","
                   + IntegerToString(ticks[i].flags) + "\r\n");
         count++;
         if(++lines == LINES_PER_WRITE)
           {
            FileWriteString(h, buf);
            buf = "";
            lines = 0;
           }
        }
      if(lines > 0)
         FileWriteString(h, buf);
     }
   FileClose(h);
   if(IsStopped())
     {
      FileDelete(tmp, g_common);
      return false;
     }
   g_ticks_total += count;
   if(count > 0)
      PrintFormat("%s Ticks %s: %I64d", sym, MonthLabel(m0), count);
   if(!Finish(tmp, name, count))
      return false;
   if(!partial && count > 0)
      DeletePartial(base);
   return true;
  }

//+------------------------------------------------------------------+
//| Script entry point                                               |
//+------------------------------------------------------------------+
void OnStart()
  {
   g_common = InpCommon ? FILE_COMMON : 0;
   g_to     = (InpTo > 0) ? InpTo : TimeTradeServer();
   g_root   = SafeName(InpFolder) + "\\" + SafeName(AccountInfoString(ACCOUNT_SERVER));
   if(InpFrom >= g_to)
     {
      Print("\"Von\" liegt nicht vor \"Bis\", nichts zu tun");
      return;
     }
   EnsureFolder(g_root);

   string symbols[];
   int n = CollectSymbols(symbols);
   if(n == 0)
     {
      Print("Keine Symbole ausgewählt");
      return;
     }
   PrintFormat("HistoryExport: %d Symbole, %s bis %s (Serverzeit)", n,
               TimeToString(InpFrom, TIME_DATE), TimeToString(g_to, TIME_DATE));
   long maxbars = TerminalInfoInteger(TERMINAL_MAXBARS);
   if(InpM1 && maxbars < (long)(g_to - InpFrom) / 60)
      PrintFormat("Hinweis: \"Max. Bars im Chart\" ist %I64d. Für lange M1-Historien unter Extras > Optionen > "
                  "Charts auf Unlimited stellen und MetaTrader neu starten.", maxbars);

   WaitForQuotes(symbols);
   ExportInfo(n);
   if(InpSpecs)
      ExportSpecs(symbols);

   for(int s = 0; s < n && !IsStopped(); s++)
     {
      string sym = symbols[s];
      if(!SymbolSelect(sym, true))
        {
         PrintFormat("%s lässt sich nicht in die Marktübersicht aufnehmen, übersprungen", sym);
         g_failed++;
         continue;
        }
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      string progress = StringFormat("%d/%d", s + 1, n);
      if(InpM1)
        {
         datetime first = FirstBarDate(sym);
         datetime start = (first > InpFrom) ? first : InpFrom;
         datetime loaded = LoadM1History(sym, start, progress);
         if(loaded == 0)
           {
            if(!IsStopped())
              {
               PrintFormat("%s M1: keine Historie im Terminal, übersprungen", sym);
               g_failed++;
              }
           }
         else
           {
            if(loaded > start && !IsStopped())
              {
               PrintFormat("%s M1: Historie nur ab %s geladen (angefordert ab %s), beim nächsten Lauf erneut versucht",
                           sym, TimeToString(loaded, TIME_DATE | TIME_MINUTES), TimeToString(start, TIME_DATE | TIME_MINUTES));
               g_failed++;
              }
            int y_from = YearOf((loaded > InpFrom) ? loaded : InpFrom);
            for(int y = y_from; y <= YearOf(g_to) && !IsStopped(); y++)
              {
               Comment(StringFormat("HistoryExport  %s  %s M1 %04d  (%I64d Kerzen bisher)", progress, sym, y, g_bars_total));
               ExportM1Year(sym, y, first, loaded, digits);
              }
           }
        }
      if(InpTicks)
         for(datetime m = MonthStart(InpFrom); m < g_to && !IsStopped(); m = NextMonth(m))
            ExportTicksMonth(sym, m, digits, progress);
     }
   Comment("");
   string base = InpCommon ? TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\"
                           : TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   PrintFormat("HistoryExport %s: %I64d Ticks, %I64d M1-Kerzen, %d Fehler. Ordner: %s%s",
               IsStopped() ? "abgebrochen" : "fertig", g_ticks_total, g_bars_total, g_failed, base, g_root);
  }
//+------------------------------------------------------------------+
