//+------------------------------------------------------------------+
//|                                                 ScalpingCore.mqh |
//|     Rules of the video "The ONLY 1 Minute Scalping Guide You'll  |
//|     Ever Need", bar by bar and without looking ahead             |
//+------------------------------------------------------------------+
// The same rules as backtest/scalping.py (see the README there,
// Ergebnis 8); backtest/check_ea.py runs this file as C++ against the
// Python backtest and compares every trade.
//
// The core only decides. It is fed closed 1-minute bars and calls a
// CScalpBroker for orders; ScalpingVideoEA.mq5 implements the broker
// with real orders, the C++ harness with simulated fills.
// - Times: every bar carries its New York local time (sessions, the
//   forex day 17:00-17:00) and a clock time for the 5-minute grouping.
// - A decision at the close of a bar is executed at the open of the
//   next 1-minute bar, so OnBar() receives that bar's time and open.
// - Swings: a zigzag that turns at 3 x ATR(14) against the running
//   extreme. RSI(14), EMA(200) and ATR are exponential means computed
//   exactly like pandas ewm(adjust=False).
// - One position per component (Tokyo, box, RSI, Fibonacci); the day
//   plan runs the Tokyo trade next to the Fibonacci scalps.
#ifndef SCALPING_CORE_MQH
#define SCALPING_CORE_MQH

#define SC_SWING_ATR       3.0
#define SC_ATR_N           14
#define SC_RSI_N           14
#define SC_EMA_N           200
#define SC_BREAKOUT_UNTIL  720            // New York minute (12:00)
#define SC_NO_ENTRY_FROM   990            // 16:30
#define SC_NO_ENTRY_TO     1080           // 18:00
#define SC_RR_BOX          1.5
#define SC_RR_TOKYO        2.0
#define SC_RR_DIV          1.5
#define SC_FIB_TRIGGER     0.33
#define SC_FIB_ENTRY       0.618
#define SC_DIV_WINDOW      5
#define SC_MIN_RISK        1e-6           // smallest stop distance as a fraction of the price
#define SC_MAX_FIB         3              // day plan: Fibonacci trades a day
#define SC_MAX_TRADES      4              // day plan: trades a day
#define SC_RING            16384          // bars kept per timeframe (a power of two)
#define SC_EVENTS          16

// components, each with at most one order or position
#define SC_C_TOKYO         0
#define SC_C_BOX           1
#define SC_C_RSI           2
#define SC_C_FIB           3
#define SC_COMPONENTS      4

// CScalpBroker::Status()
#define SC_ST_NONE         0
#define SC_ST_PENDING      1              // limit order waiting, or a market order not yet filled
#define SC_ST_OPEN         2

// CScalpBroker::PopEvent()
#define SC_EV_NONE         0
#define SC_EV_FILLED       1
#define SC_EV_CLOSED       2
#define SC_EV_CANCELLED    3              // limit cancelled because price extended the impulse first
#define SC_EV_VOID         4              // limit removed at the start of the hours without entries
#define SC_EV_EXPIRED      5              // limit removed at the end of the forex day

enum ENUM_SC_STRATEGY
  {
   SC_DAY_PLAN=0,                         // Tagesplan des Videos (Tokio + Fibonacci + RSI)
   SC_TOKYO=1,                            // Tokio-Ausbruch
   SC_BOX=2,                              // Box-Ausbruch
   SC_RSI=3,                              // RSI-Divergenz
   SC_FIB=4                               // Fibonacci-Rücksetzer
  };

enum ENUM_SC_TOKYO
  {
   SC_TOKYO_19_04=0,                      // 19:00-04:00 New York
   SC_TOKYO_20_03=1                       // 20:00-03:00 New York
  };

//+------------------------------------------------------------------+
//| New York local time from UTC (US daylight saving rules)          |
//+------------------------------------------------------------------+
long ScDaysFromCivil(long y,const int m,const int d)
  {
   if(m<=2)
      y--;
   long era=(y>=0 ? y : y-399)/400;
   long yoe=y-era*400;
   long mp=(m+9)%12;                              // March = 0
   long doy=(153*mp+2)/5+d-1;
   long doe=yoe*365+yoe/4-yoe/100+doy;
   return era*146097+doe-719468;                  // days since 1970-01-01
  }
int ScWeekday(const long days) { return (int)((days%7+11)%7); }   // 0 = Sunday
long ScYear(const long utc)
  {
   long z=utc/86400+719468;
   long era=z/146097;
   long doe=z-era*146097;
   long yoe=(doe-doe/1460+doe/36524-doe/146096)/365;
   long doy=doe-(365*yoe+yoe/4-yoe/100);
   long mp=(5*doy+2)/153;
   long m=(mp<10) ? mp+3 : mp-9;
   return yoe+era*400+((m<=2) ? 1 : 0);
  }
long ScNthSunday(const long y,const int m,const int nth)
  {
   long first=ScDaysFromCivil(y,m,1);
   return first+(7-ScWeekday(first))%7+7*(nth-1);
  }
long ScLastSunday(const long y,const int m)
  {
   long last=((m==12) ? ScDaysFromCivil(y+1,1,1) : ScDaysFromCivil(y,m+1,1))-1;
   return last-ScWeekday(last);
  }
long ScNewYork(const long utc)
  {
   long y=ScYear(utc);
   long start,end;                                // switches at 02:00 local time, as UTC seconds
   if(y>=2007)
     {
      start=ScNthSunday(y,3,2)*86400+7*3600;
      end=ScNthSunday(y,11,1)*86400+6*3600;
     }
   else
     {
      start=ScNthSunday(y,4,1)*86400+7*3600;
      end=ScLastSunday(y,10)*86400+6*3600;
     }
   return utc-((utc>=start && utc<end) ? 4 : 5)*3600;
  }

//+------------------------------------------------------------------+
//| Orders of the core: implemented by the EA and by the C++ harness |
//+------------------------------------------------------------------+
class CScalpBroker
  {
public:
   // market order at the open of the next 1-minute bar; target = entry + side * rr * risk if rr > 0.
   // A Fibonacci fill (comp SC_C_FIB) can be stopped but not reach its target in the fill bar.
   virtual bool      Market(const int comp,const int side,const double stop,const double rr,const double target)=0;
   // resting limit order from the next 1-minute bar on; cancelled when price passes cancel_level
   // before the fill, removed at 16:30 New York (void) and at the end of the forex day (expired)
   virtual bool      Limit(const int comp,const int side,const double price,const double stop,
                           const double target,const double cancel_level)=0;
   virtual void      Cancel(const int comp)=0;
   virtual int       Status(const int comp)=0;
   // oldest unread event of a component and the 1-minute bar (core index) it happened in
   virtual int       PopEvent(const int comp,long &bar)=0;
  };

//+------------------------------------------------------------------+
//| One bar as the core sees it                                      |
//+------------------------------------------------------------------+
struct SScBar
  {
   long              clock;               // seconds, any clock whose 5-minute grid is the market's (UTC, server)
   long              ny;                  // New York local time in seconds since 1970
   double            open,high,low,close;
  };

//+------------------------------------------------------------------+
//| Bars of one timeframe with ATR, RSI, EMA and the zigzag          |
//+------------------------------------------------------------------+
class CScSeries
  {
public:
   long              n;                   // bars so far
   double            o[SC_RING],h[SC_RING],l[SC_RING],c[SC_RING];
   double            atr[SC_RING],rsi[SC_RING],ema[SC_RING];
   long              last1[SC_RING];      // index of the bar's last 1-minute bar
   // zigzag swing confirmed by the bar added last
   bool              sw_new;
   int               sw_kind;             // +1 swing high, -1 swing low
   long              sw_idx;              // bar of the extreme
   double            sw_price;
   long              sw_id;               // running number of the swing
   double            m_a_wilder,m_a_ema;
   double            m_prev_c,m_atr_w,m_up_w,m_dn_w,m_ema_w;
   int               m_zz_dir;
   double            m_zz_ext;
   long              m_zz_ext_i;
   long              m_swings;

   void              Reset(void)
     {
      n=0;
      sw_new=false;
      sw_kind=0;
      sw_idx=-1;
      sw_price=0.0;
      sw_id=-1;
      m_swings=0;
      double a=1.0/SC_ATR_N;                       // pandas: alpha -> center of mass -> alpha
      double com=(1.0-a)/a;
      m_a_wilder=1.0/(1.0+com);
      com=(SC_EMA_N-1)/2.0;                         // pandas: span -> center of mass -> alpha
      m_a_ema=1.0/(1.0+com);
      m_prev_c=m_atr_w=m_up_w=m_dn_w=m_ema_w=0.0;
      m_zz_dir=1;
      m_zz_ext=0.0;
      m_zz_ext_i=0;
     }
   int               P(const long i) const { return (int)(i&(SC_RING-1)); }
   bool              Has(const long i) const { return i>=0 && i<n && i>n-SC_RING; }
   double            O(const long i) const { return o[P(i)]; }
   double            H(const long i) const { return h[P(i)]; }
   double            L(const long i) const { return l[P(i)]; }
   double            C(const long i) const { return c[P(i)]; }
   double            Rsi(const long i) const { return rsi[P(i)]; }
   double            Ema(const long i) const { return ema[P(i)]; }
   long              Last1(const long i) const { return last1[P(i)]; }
   bool              RsiOk(const long i) const { return i>=SC_RSI_N && Has(i); }
   bool              EmaOk(const long i) const { return i>=SC_EMA_N && Has(i); }
   double            Ewm(const double w,const double x,const double a) const
     {
      if(w==x)
         return w;
      return ((1.0-a)*w+a*x)/((1.0-a)+a);
     }
   void              Add(const double bo,const double bh,const double bl,const double bc,const long l1)
     {
      long i=n;
      int  p=P(i);
      o[p]=bo;
      h[p]=bh;
      l[p]=bl;
      c[p]=bc;
      last1[p]=l1;
      double pc=(i==0) ? bc : m_prev_c;
      double tr=MathMax(bh-bl,MathMax(MathAbs(bh-pc),MathAbs(bl-pc)));
      double d=(i==0) ? 0.0 : bc-m_prev_c;
      double up=MathMax(d,0.0);
      double dn=MathMax(-d,0.0);
      if(i==0)
        {
         m_atr_w=tr;
         m_up_w=up;
         m_dn_w=dn;
         m_ema_w=bc;
        }
      else
        {
         m_atr_w=Ewm(m_atr_w,tr,m_a_wilder);
         m_up_w=Ewm(m_up_w,up,m_a_wilder);
         m_dn_w=Ewm(m_dn_w,dn,m_a_wilder);
         m_ema_w=Ewm(m_ema_w,bc,m_a_ema);
        }
      atr[p]=m_atr_w;
      ema[p]=m_ema_w;
      rsi[p]=(m_dn_w>0.0) ? 100.0-100.0/(1.0+m_up_w/m_dn_w) : 100.0;
      m_prev_c=bc;
      n++;
      Zigzag(i);
     }
   void              Zigzag(const long i)
     {
      sw_new=false;
      if(i==0)
        {
         m_zz_dir=1;
         m_zz_ext=H(0);
         m_zz_ext_i=0;
         return;
        }
      double t=(i>=SC_ATR_N) ? SC_SWING_ATR*atr[P(i)] : 0.0;
      if(!(t>0.0))
         return;
      if(m_zz_dir==1)
        {
         if(H(i)>m_zz_ext)
           {
            m_zz_ext=H(i);
            m_zz_ext_i=i;
           }
         else
            if(m_zz_ext-L(i)>=t)
              {
               Swing(1);
               m_zz_dir=-1;
               m_zz_ext=L(i);
               m_zz_ext_i=i;
              }
        }
      else
        {
         if(L(i)<m_zz_ext)
           {
            m_zz_ext=L(i);
            m_zz_ext_i=i;
           }
         else
            if(H(i)-m_zz_ext>=t)
              {
               Swing(-1);
               m_zz_dir=1;
               m_zz_ext=H(i);
               m_zz_ext_i=i;
              }
        }
     }
   void              Swing(const int kind)
     {
      sw_new=true;
      sw_kind=kind;
      sw_idx=m_zz_ext_i;
      sw_price=m_zz_ext;
      sw_id=m_swings;
      m_swings++;
     }
   // lowest low / highest high and "a close beyond level" over bars [a, b] still in the ring
   double            MinL(long a,const long b) const
     {
      if(a<n-SC_RING+1)
         a=n-SC_RING+1;
      double m=L(b);
      for(long i=a; i<b; i++)
         m=MathMin(m,L(i));
      return m;
     }
   double            MaxH(long a,const long b) const
     {
      if(a<n-SC_RING+1)
         a=n-SC_RING+1;
      double m=H(b);
      for(long i=a; i<b; i++)
         m=MathMax(m,H(i));
      return m;
     }
   bool              CloseBelow(long a,const long b,const double level) const
     {
      if(a<n-SC_RING+1)
         a=n-SC_RING+1;
      for(long i=a; i<=b; i++)
         if(C(i)<level)
            return true;
      return false;
     }
   bool              CloseAbove(long a,const long b,const double level) const
     {
      if(a<n-SC_RING+1)
         a=n-SC_RING+1;
      for(long i=a; i<=b; i++)
         if(C(i)>level)
            return true;
      return false;
     }
  };

//+------------------------------------------------------------------+
//| Box breakout: highs stop rising and lows stop falling            |
//+------------------------------------------------------------------+
struct SScBox
  {
   double            hi1,hi2,lo1,lo2;     // last and previous swing high / low
   int               nh,nl;
   bool              active;
   double            lo,hi;
   long              conf;
  };

//+------------------------------------------------------------------+
//| RSI divergence: the last confirmed swing of each kind            |
//+------------------------------------------------------------------+
struct SScRsi
  {
   bool              has_low,has_high;
   long              low_idx,low_conf,high_idx,high_conf;
   double            low_price,high_price;
   bool              low_used,high_used;
  };

//+------------------------------------------------------------------+
//| Fibonacci impulse of one side (-1 down from a swing high)        |
//+------------------------------------------------------------------+
struct SScImpulse
  {
   bool              exists;
   long              id;
   double            start,prev,ext;
   long              created,resume;
   bool              done,frozen,bos;
  };

//+------------------------------------------------------------------+
//| A signal ready to be traded at the open of the next bar          |
//+------------------------------------------------------------------+
struct SScSignal
  {
   bool              valid;
   int               side;
   double            stop;
  };

//+------------------------------------------------------------------+
//| The strategy                                                     |
//+------------------------------------------------------------------+
class CScalpCore
  {
public:
   int               m_strategy;
   int               m_tf;                // minutes of the box / RSI / Fibonacci bars: 1 or 5
   int               m_tokyo_from,m_tokyo_to;
   bool              m_rsi_rule;          // RSI 70/30 rule
   bool              m_fib_ema;           // EMA 200 filter of the Fibonacci pullbacks
   CScSeries         m1,m5;
   // 1-minute bars: New York minute and forex day
   int               m_min1[SC_RING];
   long              m_day1[SC_RING];
   // 5-minute bar being built
   long              m_bucket;
   double            m_bo,m_bh,m_bl,m_bc;
   long              m_bfirst;
   // Tokyo range of the current forex day and the day plan's bias
   long              m_range_day;
   double            m_top,m_bottom;
   bool              m_has_range;
   long              m_tokyo_done_day;
   long              m_bias_day;
   int               m_bias;
   long              m_tok_entry;         // 1-minute bar of the Tokyo entry
   long              m_counter_day;
   long              m_fib_day;
   int               m_fib_count;
   // detectors
   SScBox            m_box;
   SScRsi            m_rsi;
   SScImpulse        m_imp[2];            // [0] side -1, [1] side +1
   bool              m_fib_has_low,m_fib_has_high;     // last confirmed swing low / high for the impulses
   double            m_fib_low_price,m_fib_high_price;
   int               m_imp_order[2];
   int               m_imp_orders;
   long              m_imp_ids;
   // the running Fibonacci order: owner impulse, first bar, events waiting for the Fibonacci timeframe
   bool              m_run;
   int               m_run_side;
   long              m_run_owner;
   long              m_run_start;
   bool              m_fib_open;
   long              m_fib_blocked;
   int               m_ev_type[SC_EVENTS];
   long              m_ev_bar[SC_EVENTS];
   int               m_ev_n;
   // the bar being processed and the next one
   long              m_k;
   bool              m_has_next;
   double            m_next_open;
   int               m_next_min;
   long              m_next_day;

                     CScalpCore(void) { Init(SC_DAY_PLAN,1,SC_TOKYO_19_04,true,true); }
   void              Init(const int strategy,const int tf,const int tokyo,const bool rsi_rule,const bool fib_ema)
     {
      m_strategy=strategy;
      m_tf=(tf==5) ? 5 : 1;
      if(m_strategy==SC_DAY_PLAN)
         m_tf=1;
      m_tokyo_from=(tokyo==SC_TOKYO_20_03) ? 20*60 : 19*60;
      m_tokyo_to=(tokyo==SC_TOKYO_20_03) ? 3*60 : 4*60;
      m_rsi_rule=(m_strategy==SC_DAY_PLAN) ? true : rsi_rule;
      m_fib_ema=(m_strategy==SC_DAY_PLAN) ? false : fib_ema;
      m1.Reset();
      m5.Reset();
      m_bucket=-1;
      m_bfirst=0;
      m_bo=m_bh=m_bl=m_bc=0.0;
      m_range_day=-1;
      m_top=m_bottom=0.0;
      m_has_range=false;
      m_tokyo_done_day=-1;
      m_bias_day=-1;
      m_bias=0;
      m_tok_entry=-1;
      m_counter_day=-1;
      m_fib_day=-1;
      m_fib_count=0;
      m_box.hi1=m_box.hi2=m_box.lo1=m_box.lo2=0.0;
      m_box.nh=m_box.nl=0;
      m_box.active=false;
      m_box.lo=m_box.hi=0.0;
      m_box.conf=-1;
      m_rsi.has_low=m_rsi.has_high=false;
      m_rsi.low_idx=m_rsi.low_conf=m_rsi.high_idx=m_rsi.high_conf=-1;
      m_rsi.low_price=m_rsi.high_price=0.0;
      m_rsi.low_used=m_rsi.high_used=false;
      for(int s=0; s<2; s++)
        {
         m_imp[s].exists=false;
         m_imp[s].id=-1;
         m_imp[s].start=m_imp[s].prev=m_imp[s].ext=0.0;
         m_imp[s].created=m_imp[s].resume=-1;
         m_imp[s].done=m_imp[s].frozen=m_imp[s].bos=false;
         m_imp_order[s]=0;
        }
      m_imp_orders=0;
      m_imp_ids=0;
      m_fib_has_low=m_fib_has_high=false;
      m_fib_low_price=m_fib_high_price=0.0;
      m_run=false;
      m_run_side=0;
      m_run_owner=-1;
      m_run_start=-1;
      m_fib_open=false;
      m_fib_blocked=-1;
      m_ev_n=0;
      m_k=-1;
      m_has_next=false;
      m_next_open=0.0;
      m_next_min=0;
      m_next_day=0;
     }
   long              Processed(void) const { return m1.n; }   // 1-minute bars fed so far
   int               Minute(const long ny) const { return (int)((ny%86400)/60); }
   long              Day(const long ny) const { return (ny+7*3600)/86400; }   // forex day 17:00-17:00, named by its end
   bool              EntryOk(const int minute) const { return !(minute>=SC_NO_ENTRY_FROM && minute<SC_NO_ENTRY_TO); }
   bool              UsesM1(const int what) const { return m_strategy==SC_DAY_PLAN ? (what==SC_RSI || what==SC_FIB) : (m_strategy==what && m_tf==1); }
   bool              UsesM5(const int what) const { return m_strategy!=SC_DAY_PLAN && m_strategy==what && m_tf==5; }

   //--- feed one closed 1-minute bar; next = the bar after it (its open is the decision price)
   void              OnBar(CScalpBroker &broker,const SScBar &bar,const SScBar &next,const bool has_next)
     {
      long k=m1.n;
      m_k=k;
      m1.Add(bar.open,bar.high,bar.low,bar.close,k);
      int p=m1.P(k);
      m_min1[p]=Minute(bar.ny);
      m_day1[p]=Day(bar.ny);
      m_has_next=has_next;
      m_next_open=next.open;
      m_next_min=Minute(next.ny);
      m_next_day=Day(next.ny);
      long bucket=bar.clock/300;
      if(bucket!=m_bucket)
        {
         m_bucket=bucket;
         m_bfirst=k;
         m_bo=bar.open;
         m_bh=bar.high;
         m_bl=bar.low;
        }
      else
        {
         m_bh=MathMax(m_bh,bar.high);
         m_bl=MathMin(m_bl,bar.low);
        }
      m_bc=bar.close;
      bool m5_done=!has_next || next.clock/300!=bucket;
      if(m_strategy==SC_TOKYO || m_strategy==SC_DAY_PLAN)
         TokyoRange(k);
      ReadEvents(broker);
      if(UsesM1(SC_FIB))
         FibEvents(m1);
      if(UsesM1(SC_BOX))
         Box(broker,m1);
      SScSignal div;
      div.valid=false;
      div.side=0;
      div.stop=0.0;
      if(UsesM1(SC_RSI))
         Rsi(broker,m1,div);
      if(UsesM1(SC_FIB))
        {
         FibSwing(m1);
         if(m_strategy==SC_DAY_PLAN)
            Counter(broker,div);
         FibTriggers(broker,m1);
        }
      if(m5_done)
        {
         m5.Add(m_bo,m_bh,m_bl,m_bc,k);
         if(UsesM5(SC_FIB))
            FibEvents(m5);
         if(UsesM5(SC_BOX))
            Box(broker,m5);
         SScSignal div5;
         div5.valid=false;
         div5.side=0;
         div5.stop=0.0;
         if(UsesM5(SC_RSI))
            Rsi(broker,m5,div5);
         if(UsesM5(SC_FIB))
           {
            FibSwing(m5);
            FibTriggers(broker,m5);
           }
         if(m_strategy==SC_TOKYO || m_strategy==SC_DAY_PLAN)
            TokyoBreakout(broker,k);
        }
     }

   //--- market trade at the next open: valid like scalping.market_trade()
   bool              MarketOk(const int side,const double stop) const
     {
      if(!m_has_next || !EntryOk(m_next_min))
         return false;
      double risk=(m_next_open-stop)*side;
      return risk>SC_MIN_RISK*m_next_open;
     }

   //--- broker events: Fibonacci events wait for the Fibonacci timeframe, the other components are polled
   void              ReadEvents(CScalpBroker &broker)
     {
      for(int comp=0; comp<SC_COMPONENTS; comp++)
        {
         long bar=0;
         int  ev=broker.PopEvent(comp,bar);
         while(ev!=SC_EV_NONE)
           {
            if(comp==SC_C_FIB && m_ev_n<SC_EVENTS)
              {
               m_ev_type[m_ev_n]=ev;
               m_ev_bar[m_ev_n]=bar;
               m_ev_n++;
              }
            ev=broker.PopEvent(comp,bar);
           }
        }
     }

   //--- Tokyo session range of the forex day
   void              TokyoRange(const long k)
     {
      int p=m1.P(k);
      if(m_day1[p]!=m_range_day)
        {
         m_range_day=m_day1[p];
         m_has_range=false;
        }
      int minute=m_min1[p];
      if(minute>=m_tokyo_from || minute<m_tokyo_to)
        {
         if(!m_has_range)
           {
            m_top=m1.H(k);
            m_bottom=m1.L(k);
            m_has_range=true;
           }
         else
           {
            m_top=MathMax(m_top,m1.H(k));
            m_bottom=MathMin(m_bottom,m1.L(k));
           }
        }
     }

   //--- first 5-minute close outside the Tokyo range, 04:00 (03:00) to 12:00 New York
   void              TokyoBreakout(CScalpBroker &broker,const long k)
     {
      int start_min=m_min1[m1.P(m_bfirst)];
      if(start_min<m_tokyo_to || start_min>=SC_BREAKOUT_UNTIL)
         return;
      long d=m_day1[m1.P(k)];
      if(d==m_tokyo_done_day || d!=m_range_day || !m_has_range || !(m_top>m_bottom))
         return;
      double close=m_bc;
      int side=(close>m_top) ? 1 : (close<m_bottom) ? -1 : 0;
      if(side==0)
         return;
      m_tokyo_done_day=d;
      if(!m_has_next || m_next_day!=d)
         return;
      double half=0.5*(m_top-m_bottom);
      double stop=m_next_open-side*half;
      if(!MarketOk(side,stop))
         return;
      m_bias_day=d;
      m_bias=side;
      m_tok_entry=k+1;
      if(broker.Status(SC_C_TOKYO)==SC_ST_NONE)
         broker.Market(SC_C_TOKYO,side,stop,SC_RR_TOKYO,0.0);
     }

   //--- consolidation box: the last swing high below the one before, the last swing low above the one before
   void              Box(CScalpBroker &broker,CScSeries &s)
     {
      long k=s.n-1;
      if(s.sw_new)
        {
         if(s.sw_kind>0)
           {
            m_box.hi2=m_box.hi1;
            m_box.hi1=s.sw_price;
            m_box.nh++;
           }
         else
           {
            m_box.lo2=m_box.lo1;
            m_box.lo1=s.sw_price;
            m_box.nl++;
           }
         if(m_box.nh>=2 && m_box.nl>=2 && m_box.hi1<=m_box.hi2 && m_box.lo1>=m_box.lo2)
           {
            m_box.active=true;
            m_box.lo=m_box.lo1;
            m_box.hi=m_box.hi1;
            m_box.conf=k;
           }
        }
      if(!m_box.active || k<=m_box.conf)
         return;
      double close=s.C(k);
      int side=(close>m_box.hi) ? 1 : (close<m_box.lo) ? -1 : 0;
      if(side==0)
         return;
      m_box.active=false;
      double stop=0.5*(m_box.lo+m_box.hi);
      if(MarketOk(side,stop) && broker.Status(SC_C_BOX)==SC_ST_NONE)
         broker.Market(SC_C_BOX,side,stop,SC_RR_BOX,0.0);
     }

   //--- RSI divergence at the last confirmed swing; the day plan only reads the signal
   void              Rsi(CScalpBroker &broker,CScSeries &s,SScSignal &sig)
     {
      long k=s.n-1;
      if(s.sw_new)
        {
         if(s.sw_kind<0)
           {
            m_rsi.has_low=true;
            m_rsi.low_idx=s.sw_idx;
            m_rsi.low_price=s.sw_price;
            m_rsi.low_conf=k;
            m_rsi.low_used=false;
           }
         else
           {
            m_rsi.has_high=true;
            m_rsi.high_idx=s.sw_idx;
            m_rsi.high_price=s.sw_price;
            m_rsi.high_conf=k;
            m_rsi.high_used=false;
           }
        }
      if(k<SC_DIV_WINDOW)
         return;
      bool bull=s.C(k)>s.O(k);
      bool bear=s.C(k)<s.O(k);
      if(bull && m_rsi.has_low)
        {
         long p=k-SC_DIV_WINDOW;
         for(long i=k-SC_DIV_WINDOW+1; i<=k; i++)
            if(s.L(i)<s.L(p))
               p=i;
         long si=m_rsi.low_idx;
         if(p>m_rsi.low_conf && s.L(p)<m_rsi.low_price && !m_rsi.low_used && s.RsiOk(p) && s.RsiOk(si) &&
            s.Rsi(p)>s.Rsi(si) && (!m_rsi_rule || (s.Rsi(si)<30.0 && 30.0<=s.Rsi(p) && s.Rsi(p)<=70.0)) &&
            MarketOk(1,s.L(p)))
           {
            m_rsi.low_used=true;
            Divergence(broker,sig,1,s.L(p));
           }
        }
      if(bear && m_rsi.has_high)
        {
         long p=k-SC_DIV_WINDOW;
         for(long i=k-SC_DIV_WINDOW+1; i<=k; i++)
            if(s.H(i)>s.H(p))
               p=i;
         long si=m_rsi.high_idx;
         if(p>m_rsi.high_conf && s.H(p)>m_rsi.high_price && !m_rsi.high_used && s.RsiOk(p) && s.RsiOk(si) &&
            s.Rsi(p)<s.Rsi(si) && (!m_rsi_rule || (s.Rsi(si)>70.0 && 70.0>=s.Rsi(p) && s.Rsi(p)>=30.0)) &&
            MarketOk(-1,s.H(p)))
           {
            m_rsi.high_used=true;
            Divergence(broker,sig,-1,s.H(p));
           }
        }
     }
   void              Divergence(CScalpBroker &broker,SScSignal &sig,const int side,const double stop)
     {
      sig.valid=true;
      sig.side=side;
      sig.stop=stop;
      if(m_strategy==SC_RSI && broker.Status(SC_C_RSI)==SC_ST_NONE)
         broker.Market(SC_C_RSI,side,stop,SC_RR_DIV,0.0);
     }

   //--- day plan: the first divergence against the bias ends the Fibonacci scalps and is the last trade
   void              Counter(CScalpBroker &broker,const SScSignal &div)
     {
      if(!div.valid)
         return;
      long e=m_k+1;
      long d=m_next_day;
      if(m_bias_day!=d || div.side!=-m_bias || e<=m_tok_entry || m_counter_day==d)
         return;
      m_counter_day=d;
      if(m_run)
        {
         broker.Cancel(SC_C_FIB);
         EndRun(true,m_k);
        }
      int fibs=(m_fib_day==d) ? m_fib_count : 0;
      if(1+fibs<SC_MAX_TRADES && !m_fib_open && broker.Status(SC_C_RSI)==SC_ST_NONE)
         broker.Market(SC_C_RSI,div.side,div.stop,SC_RR_DIV,0.0);
     }
   bool              AllowFib(const int side,const long i) const
     {
      if(m_strategy!=SC_DAY_PLAN)
         return true;
      long d=m_next_day;
      int fibs=(m_fib_day==d) ? m_fib_count : 0;
      return m_bias_day==d && side==m_bias && i>m_tok_entry && m_counter_day!=d && fibs<SC_MAX_FIB && fibs<SC_MAX_TRADES-1;
     }

   //--- Fibonacci pullbacks
   int               Slot(const int side) const { return side<0 ? 0 : 1; }
   void              EndRun(const bool owner_done,const long blocked)
     {
      int sl=Slot(m_run_side);
      if(m_imp[sl].exists && m_imp[sl].id==m_run_owner)
        {
         m_imp[sl].frozen=false;
         if(owner_done)
            m_imp[sl].done=true;
        }
      m_run=false;
      m_fib_blocked=blocked;
     }
   // events of the running order that happened in this bar of the Fibonacci timeframe
   void              FibEvents(CScSeries &s)
     {
      long K=s.n-1;
      for(int q=0; q<m_ev_n; q++)
        {
         int  ev=m_ev_type[q];
         long x=m_ev_bar[q];
         if(ev==SC_EV_FILLED)
           {
            if(m_run)
               EndRun(true,m_fib_blocked);
            m_fib_open=true;
            m_fib_blocked=K+SC_RING;                  // until the trade ends
            long d=m_day1[m1.P(x)];
            if(m_fib_day!=d)
              {
               m_fib_day=d;
               m_fib_count=0;
              }
            m_fib_count++;
           }
         else
            if(ev==SC_EV_CLOSED)
              {
               m_fib_open=false;
               m_fib_blocked=K;
              }
            else
               if(ev==SC_EV_CANCELLED && m_run)
                 {
                  int sl=Slot(m_run_side);
                  if(m_imp[sl].exists && m_imp[sl].id==m_run_owner)
                    {
                     if(m_run_side<0)
                        m_imp[sl].ext=m1.MinL(m_run_start,x);
                     else
                        m_imp[sl].ext=m1.MaxH(m_run_start,x);
                     m_imp[sl].resume=K;
                    }
                  EndRun(false,K);
                 }
               else
                  if((ev==SC_EV_VOID || ev==SC_EV_EXPIRED) && m_run)
                     EndRun(true,K);
        }
      m_ev_n=0;
     }
   // a confirmed swing starts the impulse away from it; the swing before is the structure to break
   void              FibSwing(CScSeries &s)
     {
      if(!s.sw_new)
         return;
      long k=s.n-1;
      int  kind=s.sw_kind;
      bool has_prev=(kind>0) ? m_fib_has_low : m_fib_has_high;
      double prev=(kind>0) ? m_fib_low_price : m_fib_high_price;
      if(kind>0)
        {
         m_fib_has_high=true;
         m_fib_high_price=s.sw_price;
        }
      else
        {
         m_fib_has_low=true;
         m_fib_low_price=s.sw_price;
        }
      if(!has_prev)
         return;
      int side=(kind>0) ? -1 : 1;
      int sl=Slot(side);
      bool first=!m_imp[sl].exists;
      m_imp[sl].exists=true;
      m_imp[sl].id=m_imp_ids;
      m_imp_ids++;
      m_imp[sl].start=s.sw_price;
      m_imp[sl].prev=prev;
      m_imp[sl].created=k;
      m_imp[sl].resume=-1;
      m_imp[sl].done=false;
      m_imp[sl].frozen=false;
      if(side<0)
        {
         m_imp[sl].ext=s.MinL(s.sw_idx,k);
         m_imp[sl].bos=s.CloseBelow(s.sw_idx,k,prev);
        }
      else
        {
         m_imp[sl].ext=s.MaxH(s.sw_idx,k);
         m_imp[sl].bos=s.CloseAbove(s.sw_idx,k,prev);
        }
      if(first)
        {
         m_imp_order[m_imp_orders]=side;
         m_imp_orders++;
        }
     }
   void              FibTriggers(CScalpBroker &broker,CScSeries &s)
     {
      long K=s.n-1;
      for(int q=0; q<m_imp_orders; q++)
        {
         int side=m_imp_order[q];
         int sl=Slot(side);
         if(!m_imp[sl].exists || m_imp[sl].frozen || K<=m_imp[sl].resume || m_imp[sl].done || m_imp[sl].created==K)
            continue;
         if((side<0) ? s.H(K)>m_imp[sl].start : s.L(K)<m_imp[sl].start)
           {
            m_imp[sl].done=true;
            continue;
           }
         bool new_ext=(side<0) ? s.L(K)<m_imp[sl].ext : s.H(K)>m_imp[sl].ext;
         if(new_ext)
            m_imp[sl].ext=(side<0) ? s.L(K) : s.H(K);
         if(!m_imp[sl].bos && ((side<0) ? s.C(K)<m_imp[sl].prev : s.C(K)>m_imp[sl].prev))
            m_imp[sl].bos=true;
         if(!m_imp[sl].bos || new_ext || m_run || m_fib_open || K<=m_fib_blocked)
            continue;
         double rng=(m_imp[sl].start-m_imp[sl].ext)*(-side);
         double retr=(side<0) ? s.H(K)-m_imp[sl].ext : m_imp[sl].ext-s.L(K);
         if(!(rng>0.0) || retr<SC_FIB_TRIGGER*rng)
            continue;
         if(m_fib_ema && !(s.EmaOk(K) && ((side<0) ? s.C(K)<s.Ema(K) : s.C(K)>s.Ema(K))))
           {
            m_imp[sl].done=true;
            continue;
           }
         long i=s.Last1(K);
         if(!m_has_next || !EntryOk(m_next_min) || !AllowFib(side,i))
            continue;
         double ext=m_imp[sl].ext;
         double stop=m_imp[sl].start;
         double limit=ext+((side<0) ? SC_FIB_ENTRY*rng : -SC_FIB_ENTRY*rng);
         double p=m_next_open;
         if((side<0) ? p>=stop : p<=stop)
           {
            m_imp[sl].done=true;                     // the setup broke before the order could be placed
            continue;
           }
         bool placed=false;
         if((side<0) ? p>=limit : p<=limit)
           {
            if(!((stop-p)*(-side)>SC_MIN_RISK*p))
              {
               m_imp[sl].done=true;
               continue;
              }
            placed=broker.Market(SC_C_FIB,side,stop,0.0,ext);
           }
         else
           {
            if(!((stop-limit)*(-side)>SC_MIN_RISK*limit))
              {
               m_imp[sl].done=true;
               continue;
              }
            placed=broker.Limit(SC_C_FIB,side,limit,stop,ext,ext);
           }
         if(!placed)
            continue;
         m_imp[sl].frozen=true;
         m_run=true;
         m_run_side=side;
         m_run_owner=m_imp[sl].id;
         m_run_start=i+1;
        }
     }
  };

#endif
//+------------------------------------------------------------------+
