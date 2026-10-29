//+------------------------------------------------------------------+
//|                                              ScalpingVideoEA.mq5 |
//|     Expert advisor for the 1-minute scalping rules of the video  |
//|     "The ONLY 1 Minute Scalping Guide You'll Ever Need"          |
//+------------------------------------------------------------------+
// The rules are in ScalpingCore.mqh, the same rules as the backtest in
// backtest/scalping.py (backtest/check_ea.py compares every trade).
// This file feeds the core the chart symbol's closed M1 bars, sends its
// orders with 1 % risk per trade and closes everything at the end of
// the forex day (17:00 New York).
//
// In the backtest (backtest/README.md, Ergebnis 8) no variant was
// profitable after costs on EURUSD, GBPUSD, gold or the US indices.
// Use it in the strategy tester or on a demo account.
//
// Notes
// - New York time: most brokers run their server clock at New York + 7
//   hours (IC Markets, Pepperstone and others), so 17:00 New York is
//   midnight. For a server on a fixed UTC offset choose the UTC clock;
//   US daylight saving time is then computed.
// - Decisions are taken at the first tick of a new M1 bar, at its open.
// - The day plan holds the Tokyo trade next to the Fibonacci scalps and
//   needs a hedging account.
// - A Fibonacci limit is cancelled on the tick that extends the impulse,
//   deleted at 16:30 New York and at the day end.
#property copyright   "Microcontroller backtest"
#property version     "1.00"
#property description "1-Minuten-Scalping nach dem Video \"The ONLY 1 Minute Scalping Guide You'll Ever Need\":"
#property description "Tokio-Ausbruch, Box-Ausbruch, Fibonacci 0,618, RSI-Divergenz und der Tagesplan."
#property description "Im Backtest nach Kosten nicht profitabel - nur für Strategietester und Demokonto."

#include <Trade\Trade.mqh>
#include "ScalpingCore.mqh"

enum ENUM_SV_TF
  {
   SV_TF_M1=1,                            // 1 Minute
   SV_TF_M5=5                             // 5 Minuten
  };

enum ENUM_SV_CLOCK
  {
   SV_CLOCK_NY=0,                         // Serverzeit = New York + Versatz
   SV_CLOCK_UTC=1                         // Serverzeit = UTC + Versatz (US-Sommerzeit wird berechnet)
  };

input group "Strategie"
input ENUM_SC_STRATEGY InpStrategy     = SC_DAY_PLAN;       // Strategie
input ENUM_SV_TF       InpTimeframe    = SV_TF_M1;          // Zeiteinheit für Box, RSI und Fibonacci
input ENUM_SC_TOKYO    InpTokyo        = SC_TOKYO_19_04;    // Tokio-Spanne
input bool             InpRsiRule      = true;              // RSI-Divergenz: 70/30-Regel
input bool             InpFibEma       = true;              // Fibonacci: nur auf der Seite der EMA 200

input group "Risiko"
input double           InpRiskPercent  = 1.0;               // Risiko je Trade in % des Kontostands
input double           InpMaxLeverage  = 30.0;              // Position höchstens das x-Fache des Kapitals

input group "Zeit"
input ENUM_SV_CLOCK    InpClock        = SV_CLOCK_NY;       // Uhr des Handelsservers
input int              InpClockOffset  = 7;                 // Versatz in Stunden (IC Markets: New York + 7)
input int              InpCloseHour    = 16;                // Alles schließen um (New York): Stunde
input int              InpCloseMinute  = 58;                // Alles schließen um (New York): Minute

input group "Ausführung"
input long             InpMagic        = 26102800;          // Magic Number (+0 Tokio, +1 Box, +2 RSI, +3 Fibonacci)
input int              InpSlippage     = 10;                // Höchste Abweichung bei Market-Orders (Punkte)
input int              InpWarmupBars   = 20000;             // M1-Kerzen zum Einschwingen beim Start
input double           InpExtraComm    = 0.0;               // Nur Statistik: Kommission je Lot und Seite, falls der Tester keine bucht
input bool             InpLog          = false;             // Orders im Journal protokollieren

#define SV_MAX_PENDING 64

//+------------------------------------------------------------------+
//| Server time -> New York local time                               |
//+------------------------------------------------------------------+
long NewYork(const datetime server)
  {
   if(InpClock==SV_CLOCK_NY)
      return (long)server-(long)InpClockOffset*3600;
   return ScNewYork((long)server-(long)InpClockOffset*3600);
  }

//+------------------------------------------------------------------+
//| The core's broker: real orders, one per component                |
//+------------------------------------------------------------------+
class CBrokerMT5 : public CScalpBroker
  {
public:
   CTrade            m_trade;
   bool              m_live;              // false while warming up and for stale bars: orders are refused
   ulong             m_order[SC_COMPONENTS];
   ulong             m_pos[SC_COMPONENTS];
   double            m_cancel[SC_COMPONENTS];
   int               m_side[SC_COMPONENTS];
   double            m_risk[SC_COMPONENTS];          // money at risk of the order / position
   double            m_lots[SC_COMPONENTS];
   // core events: queue per component
   int               m_ev[SC_COMPONENTS][SC_EVENTS];
   long              m_ev_bar[SC_COMPONENTS][SC_EVENTS];
   int               m_ev_n[SC_COMPONENTS];
   // events seen but not yet given to the core: component, type, time
   int               m_p_comp[SV_MAX_PENDING];
   int               m_p_type[SV_MAX_PENDING];
   datetime          m_p_time[SV_MAX_PENDING];
   int               m_p_n;
   // statistics in R (multiples of the money at risk)
   int               m_trades[SC_COMPONENTS];
   int               m_wins[SC_COMPONENTS];
   double            m_sum_r[SC_COMPONENTS];
   double            m_sum_r_net[SC_COMPONENTS];

   void              Init(void)
     {
      m_trade.SetExpertMagicNumber((ulong)InpMagic);
      m_trade.SetDeviationInPoints((ulong)InpSlippage);
      m_trade.SetTypeFillingBySymbol(_Symbol);
      m_trade.SetMarginMode();
      m_trade.LogLevel(InpLog ? LOG_LEVEL_ALL : LOG_LEVEL_ERRORS);
      m_live=false;
      m_p_n=0;
      for(int c=0; c<SC_COMPONENTS; c++)
        {
         m_order[c]=0;
         m_pos[c]=0;
         m_cancel[c]=0.0;
         m_side[c]=0;
         m_risk[c]=0.0;
         m_lots[c]=0.0;
         m_ev_n[c]=0;
         m_trades[c]=m_wins[c]=0;
         m_sum_r[c]=m_sum_r_net[c]=0.0;
        }
     }
   ulong             Magic(const int comp) const { return (ulong)(InpMagic+comp); }
   string            Name(const int comp) const
     {
      return comp==SC_C_TOKYO ? "Tokio" : comp==SC_C_BOX ? "Box" : comp==SC_C_RSI ? "RSI" : "Fibonacci";
     }
   double            Norm(const double price) const
     {
      double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
      if(tick<=0.0)
         return NormalizeDouble(price,_Digits);
      return NormalizeDouble(MathRound(price/tick)*tick,_Digits);
     }
   // lots for InpRiskPercent of the balance, at most InpMaxLeverage x equity; 0 if below the minimum lot
   double            Lots(const int side,const double entry,const double stop)
     {
      double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
      double value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS);
      if(value<=0.0)
         value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
      double dist=MathAbs(entry-stop);
      if(tick<=0.0 || value<=0.0 || dist<=0.0)
         return 0.0;
      double lots=AccountInfoDouble(ACCOUNT_BALANCE)*InpRiskPercent/100.0/(dist/tick*value);
      double per_lot=entry/tick*value;                  // position value of one lot
      if(per_lot>0.0 && InpMaxLeverage>0.0)
         lots=MathMin(lots,InpMaxLeverage*AccountInfoDouble(ACCOUNT_EQUITY)/per_lot);
      double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
      double vmin=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      double vmax=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
      if(step<=0.0)
         step=vmin;
      double margin=0.0;
      if(OrderCalcMargin(side>0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL,_Symbol,lots,entry,margin) && margin>0.0)
        {
         double free=AccountInfoDouble(ACCOUNT_MARGIN_FREE)*0.95;
         if(margin>free)
            lots*=free/margin;
        }
      int digits=0;                                     // decimals of the volume step (0.01 -> 2)
      for(double st=step; st<1.0-1e-9 && digits<8; st*=10.0)
         digits++;
      lots=NormalizeDouble(MathFloor(lots/step+1e-9)*step,digits);
      if(lots<vmin)
         return 0.0;
      return MathMin(lots,vmax);
     }
   bool              StopsOk(const double price,const double stop,const double target) const
     {
      double min_dist=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
      return MathAbs(price-stop)>min_dist && MathAbs(target-price)>min_dist;
     }
   virtual bool      Market(const int comp,const int side,const double stop,const double rr,const double target)
     {
      if(!m_live || m_pos[comp]!=0 || m_order[comp]!=0)
         return false;
      double price=(side>0) ? SymbolInfoDouble(_Symbol,SYMBOL_ASK) : SymbolInfoDouble(_Symbol,SYMBOL_BID);
      if((price-stop)*side<=0.0)
         return false;
      double tp=(rr>0.0) ? price+side*rr*((price-stop)*side) : target;
      if((tp-price)*side<=0.0)
         return false;
      double sl=Norm(stop);
      tp=Norm(tp);
      if(!StopsOk(price,sl,tp))
         return false;
      double lots=Lots(side,price,sl);
      if(lots<=0.0)
         return false;
      m_trade.SetExpertMagicNumber(Magic(comp));
      bool ok=(side>0) ? m_trade.Buy(lots,_Symbol,price,sl,tp,"SV "+Name(comp))
                       : m_trade.Sell(lots,_Symbol,price,sl,tp,"SV "+Name(comp));
      if(!ok || (m_trade.ResultRetcode()!=TRADE_RETCODE_DONE && m_trade.ResultRetcode()!=TRADE_RETCODE_PLACED))
         return false;
      ulong pos=FindPosition(comp);
      if(pos==0)
         return false;
      m_pos[comp]=pos;
      m_side[comp]=side;
      m_lots[comp]=lots;
      PositionSelectByTicket(pos);
      m_risk[comp]=RiskMoney(PositionGetDouble(POSITION_PRICE_OPEN),sl,lots);
      Collect(comp,SC_EV_FILLED,TimeCurrent());
      return true;
     }
   virtual bool      Limit(const int comp,const int side,const double price,const double stop,
                           const double target,const double cancel_level)
     {
      if(!m_live || m_pos[comp]!=0 || m_order[comp]!=0)
         return false;
      double p=Norm(price),sl=Norm(stop),tp=Norm(target);
      double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK),bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double min_dist=(double)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
      if((side>0 && p>=ask-min_dist) || (side<0 && p<=bid+min_dist) || !StopsOk(p,sl,tp))
         return false;
      double lots=Lots(side,p,sl);
      if(lots<=0.0)
         return false;
      m_trade.SetExpertMagicNumber(Magic(comp));
      bool ok=(side>0) ? m_trade.BuyLimit(lots,p,_Symbol,sl,tp,ORDER_TIME_GTC,0,"SV "+Name(comp))
                       : m_trade.SellLimit(lots,p,_Symbol,sl,tp,ORDER_TIME_GTC,0,"SV "+Name(comp));
      if(!ok || m_trade.ResultOrder()==0)
         return false;
      m_order[comp]=m_trade.ResultOrder();
      m_cancel[comp]=cancel_level;
      m_side[comp]=side;
      m_lots[comp]=lots;
      m_risk[comp]=RiskMoney(p,sl,lots);
      return true;
     }
   virtual void      Cancel(const int comp)
     {
      if(m_order[comp]!=0)
        {
         m_trade.OrderDelete(m_order[comp]);
         m_order[comp]=0;
        }
     }
   virtual int       Status(const int comp)
     {
      if(m_pos[comp]!=0)
         return SC_ST_OPEN;
      return m_order[comp]!=0 ? SC_ST_PENDING : SC_ST_NONE;
     }
   virtual int       PopEvent(const int comp,long &bar)
     {
      if(m_ev_n[comp]==0)
         return SC_EV_NONE;
      int ev=m_ev[comp][0];
      bar=m_ev_bar[comp][0];
      for(int i=1; i<m_ev_n[comp]; i++)
        {
         m_ev[comp][i-1]=m_ev[comp][i];
         m_ev_bar[comp][i-1]=m_ev_bar[comp][i];
        }
      m_ev_n[comp]--;
      return ev;
     }
   double            RiskMoney(const double entry,const double stop,const double lots) const
     {
      double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
      double value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS);
      if(value<=0.0)
         value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
      return tick>0.0 ? MathAbs(entry-stop)/tick*value*lots : 0.0;
     }
   ulong             FindPosition(const int comp) const
     {
      for(int i=PositionsTotal()-1; i>=0; i--)
        {
         ulong t=PositionGetTicket(i);
         if(t!=0 && PositionGetString(POSITION_SYMBOL)==_Symbol && PositionGetInteger(POSITION_MAGIC)==(long)Magic(comp))
            return t;
        }
      return 0;
     }
   ulong             FindOrder(const int comp) const
     {
      for(int i=OrdersTotal()-1; i>=0; i--)
        {
         ulong t=OrderGetTicket(i);
         if(t!=0 && OrderGetString(ORDER_SYMBOL)==_Symbol && OrderGetInteger(ORDER_MAGIC)==(long)Magic(comp))
            return t;
        }
      return 0;
     }
   // an event for the core, handed over with the M1 bar it happened in
   void              Collect(const int comp,const int type,const datetime time)
     {
      if(m_p_n>=SV_MAX_PENDING)
         return;
      m_p_comp[m_p_n]=comp;
      m_p_type[m_p_n]=type;
      m_p_time[m_p_n]=time;
      m_p_n++;
     }
   // move the events that happened before `until` into the core queues as events of bar `bar`
   void              Deliver(const datetime until,const long bar)
     {
      int keep=0;
      for(int i=0; i<m_p_n; i++)
        {
         int c=m_p_comp[i];
         if(m_p_time[i]<until && m_ev_n[c]<SC_EVENTS)
           {
            m_ev[c][m_ev_n[c]]=m_p_type[i];
            m_ev_bar[c][m_ev_n[c]]=bar;
            m_ev_n[c]++;
           }
         else
           {
            m_p_comp[keep]=m_p_comp[i];
            m_p_type[keep]=m_p_type[i];
            m_p_time[keep]=m_p_time[i];
            keep++;
           }
        }
      m_p_n=keep;
     }
   // deal times and result of a position from the history
   bool              PositionDeals(const ulong pos,datetime &opened,datetime &closed,double &pnl)
     {
      opened=0;
      closed=0;
      pnl=0.0;
      if(!HistorySelectByPosition(pos))
         return false;
      for(int i=0; i<HistoryDealsTotal(); i++)
        {
         ulong d=HistoryDealGetTicket(i);
         long entry=HistoryDealGetInteger(d,DEAL_ENTRY);
         datetime t=(datetime)HistoryDealGetInteger(d,DEAL_TIME);
         pnl+=HistoryDealGetDouble(d,DEAL_PROFIT)+HistoryDealGetDouble(d,DEAL_COMMISSION)+
              HistoryDealGetDouble(d,DEAL_SWAP)+HistoryDealGetDouble(d,DEAL_FEE);
         if(entry==DEAL_ENTRY_IN && opened==0)
            opened=t;
         if(entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY)
            closed=t;
        }
      return true;
     }
   void              Record(const int comp,const ulong pos)
     {
      datetime opened,closed;
      double pnl;
      PositionDeals(pos,opened,closed,pnl);
      if(m_risk[comp]<=0.0)
         return;
      double r=pnl/m_risk[comp];
      m_trades[comp]++;
      if(pnl>0.0)
         m_wins[comp]++;
      m_sum_r[comp]+=r;
      m_sum_r_net[comp]+=(pnl-2.0*InpExtraComm*m_lots[comp])/m_risk[comp];
     }
   // fills of resting limits and closes by stop, target or hand
   void              Poll(void)
     {
      for(int c=0; c<SC_COMPONENTS; c++)
        {
         if(m_order[c]!=0 && !OrderSelect(m_order[c]))
           {
            ulong order=m_order[c];
            m_order[c]=0;
            datetime opened,closed;
            double pnl;
            ulong pos=FindPosition(c);
            if(pos!=0)
              {
               m_pos[c]=pos;
               PositionDeals(pos,opened,closed,pnl);
               Collect(c,SC_EV_FILLED,opened>0 ? opened : TimeCurrent());
              }
            else
               if(HistoryOrderSelect(order) && HistoryOrderGetInteger(order,ORDER_STATE)==ORDER_STATE_FILLED &&
                  PositionDeals(order,opened,closed,pnl) && opened>0)
                 {
                  Collect(c,SC_EV_FILLED,opened);             // filled and closed between two ticks
                  Collect(c,SC_EV_CLOSED,closed>0 ? closed : opened);
                  Record(c,order);
                 }
               else
                  Collect(c,SC_EV_EXPIRED,TimeCurrent());   // removed by the server
           }
         if(m_pos[c]!=0 && !PositionSelectByTicket(m_pos[c]))
           {
            datetime opened,closed;
            double pnl;
            PositionDeals(m_pos[c],opened,closed,pnl);
            Collect(c,SC_EV_CLOSED,closed>0 ? closed : TimeCurrent());
            Record(c,m_pos[c]);
            m_pos[c]=0;
           }
        }
     }
   // tick rules: a Fibonacci limit is cancelled when price extends the impulse
   void              CheckCancel(void)
     {
      int c=SC_C_FIB;
      if(m_order[c]==0)
         return;
      double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
      if((m_side[c]<0 && bid<m_cancel[c]) || (m_side[c]>0 && bid>m_cancel[c]))
        {
         m_trade.OrderDelete(m_order[c]);
         m_order[c]=0;
         Collect(c,SC_EV_CANCELLED,TimeCurrent());
        }
     }
   // 16:30 New York: pending orders are void; the close time: everything is closed
   void              CheckClock(const int minute)
     {
      bool no_entry=minute>=SC_NO_ENTRY_FROM && minute<SC_NO_ENTRY_TO;
      int  close_at=InpCloseHour*60+InpCloseMinute;
      bool closing=minute>=close_at && minute<SC_NO_ENTRY_TO;
      for(int c=0; c<SC_COMPONENTS; c++)
        {
         if(m_order[c]!=0 && no_entry)
           {
            m_trade.OrderDelete(m_order[c]);
            m_order[c]=0;
            Collect(c,closing ? SC_EV_EXPIRED : SC_EV_VOID,TimeCurrent());
           }
         if(m_pos[c]!=0 && closing && PositionSelectByTicket(m_pos[c]))
            m_trade.PositionClose(m_pos[c],(ulong)InpSlippage);
        }
     }
  };

CBrokerMT5 g_broker;
CScalpCore g_core;
datetime   g_last_fed=0;                  // open time of the last M1 bar given to the core
datetime   g_forming=0;                   // open time of the M1 bar forming at the last feed
bool       g_ready=false;

//+------------------------------------------------------------------+
//| One M1 bar for the core                                          |
//+------------------------------------------------------------------+
void ToBar(const MqlRates &r,SScBar &b)
  {
   b.clock=(long)r.time;
   b.ny=NewYork(r.time);
   b.open=r.open;
   b.high=r.high;
   b.low=r.low;
   b.close=r.close;
  }

//+------------------------------------------------------------------+
//| Give the core every closed M1 bar after g_last_fed               |
//+------------------------------------------------------------------+
bool Feed(const bool warmup)
  {
   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   int n;
   if(g_last_fed==0)
      n=CopyRates(_Symbol,PERIOD_M1,0,InpWarmupBars+1,rates);
   else
      n=CopyRates(_Symbol,PERIOD_M1,g_last_fed+1,TimeCurrent(),rates);
   if(n<1)
      return false;
   g_forming=rates[n-1].time;
   // rates[n-1] is the bar now forming; its open is the price of decisions taken at the close before it
   for(int i=0; i<n-1; i++)
     {
      SScBar bar,next;
      ToBar(rates[i],bar);
      ToBar(rates[i+1],next);
      g_broker.m_live=!warmup && i==n-2;
      g_broker.Deliver(rates[i].time+PeriodSeconds(PERIOD_M1),g_core.Processed());
      g_core.OnBar(g_broker,bar,next,true);
      g_last_fed=rates[i].time;
     }
   g_broker.m_live=false;
   return true;
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpRiskPercent<=0.0 || InpRiskPercent>10.0)
     {
      Print("Risiko je Trade muss zwischen 0 und 10 % liegen");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpStrategy==SC_DAY_PLAN && AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      Print("Der Tagesplan hält Tokio- und Fibonacci-Trade gleichzeitig und braucht ein Hedging-Konto");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_broker.Init();
   g_core.Init(InpStrategy,(int)InpTimeframe,InpTokyo,InpRsiRule,InpFibEma);
   for(int c=0; c<SC_COMPONENTS; c++)             // after a restart: keep managing our orders and positions
     {
      g_broker.m_pos[c]=g_broker.FindPosition(c);
      g_broker.m_order[c]=g_broker.FindOrder(c);
      if(g_broker.m_order[c]!=0 && OrderSelect(g_broker.m_order[c]))
        {
         g_broker.m_side[c]=(OrderGetInteger(ORDER_TYPE)==ORDER_TYPE_BUY_LIMIT) ? 1 : -1;
         g_broker.m_cancel[c]=OrderGetDouble(ORDER_TP);   // the impulse end is the target
        }
     }
   g_last_fed=0;
   g_forming=0;
   g_ready=false;
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(!g_ready)
     {
      if(!Feed(true))
         return;
      g_ready=true;
      PrintFormat("ScalpingVideoEA: %d M1-Kerzen eingeschwungen, Strategie %s",
                  (int)g_core.Processed(),EnumToString(InpStrategy));
     }
   g_broker.Poll();
   if(iTime(_Symbol,PERIOD_M1,0)!=g_forming)
      Feed(false);
   g_broker.CheckCancel();
   g_broker.CheckClock(g_core.Minute(NewYork(TimeCurrent())));
   if(!MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_VISUAL_MODE))
      Panel();
  }

//+------------------------------------------------------------------+
void Panel()
  {
   long ny=NewYork(TimeCurrent());
   string s=StringFormat("ScalpingVideoEA - %s\nNew York %02d:%02d",EnumToString(InpStrategy),
                         (int)((ny%86400)/3600),(int)((ny%3600)/60));
   if(InpStrategy==SC_DAY_PLAN || InpStrategy==SC_TOKYO)
     {
      if(g_core.m_has_range)
         s+=StringFormat("\nTokio-Spanne %s - %s",DoubleToString(g_core.m_bottom,_Digits),DoubleToString(g_core.m_top,_Digits));
      if(g_core.m_bias_day==g_core.Day(ny))
         s+=g_core.m_bias>0 ? "\nTagesrichtung: Long" : "\nTagesrichtung: Short";
     }
   for(int c=0; c<SC_COMPONENTS; c++)
      if(g_broker.m_trades[c]>0)
         s+=StringFormat("\n%s: %d Trades, %.0f %% Treffer, %+.3f R je Trade",g_broker.Name(c),g_broker.m_trades[c],
                         100.0*g_broker.m_wins[c]/g_broker.m_trades[c],g_broker.m_sum_r[c]/g_broker.m_trades[c]);
   Comment(s);
  }

//+------------------------------------------------------------------+
double OnTester()
  {
   int n=0;
   double r=0.0;
   for(int c=0; c<SC_COMPONENTS; c++)
     {
      n+=g_broker.m_trades[c];
      r+=g_broker.m_sum_r_net[c];
     }
   return n>0 ? r/n : 0.0;                         // mean R per trade after costs
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   for(int c=0; c<SC_COMPONENTS; c++)
     {
      int n=g_broker.m_trades[c];
      if(n>0)
         PrintFormat("%s: %d Trades, Trefferquote %.1f %%, im Mittel %+.3f R je Trade (mit Zusatzkommission %+.3f R)",
                     g_broker.Name(c),n,100.0*g_broker.m_wins[c]/n,g_broker.m_sum_r[c]/n,g_broker.m_sum_r_net[c]/n);
     }
   Comment("");
  }
//+------------------------------------------------------------------+
