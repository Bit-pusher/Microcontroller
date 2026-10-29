# ScalpingVideoEA

Expert Advisor für MetaTrader 5 mit den Regeln aus dem Video „The ONLY 1 Minute Scalping Guide You'll Ever
Need“, so wie sie in `backtest/scalping.py` mechanisch festgelegt und in `backtest/README.md` (Ergebnis 8)
getestet sind.

**Im Backtest war nach Kosten keine Variante profitabel** (EURUSD, GBPUSD, Gold, S&P 500, Nasdaq 100,
Russell 2000, 2005 bis Mai 2020). Der EA ist zum Nachprüfen im Strategietester und auf einem Demokonto
gedacht, nicht für echtes Geld.

## Dateien

| Datei | Inhalt |
|---|---|
| `ScalpingCore.mqh` | Die Regeln: Kerzen, ATR, RSI, EMA, Zickzack, Tokio-, Box-, RSI- und Fibonacci-Signale, Tagesplan. Rechnet nur und gibt Orders an eine Broker-Schnittstelle. |
| `ScalpingVideoEA.mq5` | Der EA: liefert dem Kern die M1-Kerzen, setzt dessen Orders mit Positionsgröße nach Risiko um und schließt zum Tagesende. |

## Installation

1. Den Ordner `ScalpingVideoEA` nach `MQL5/Experts/` kopieren (im Terminal: *Datei → Dateiordner öffnen*).
2. `ScalpingVideoEA.mq5` im MetaEditor öffnen und kompilieren (F7).
3. Im Strategietester (Strg+R) den EA wählen.

## Einstellungen

| Eingabe | Standard | Bedeutung |
|---|---|---|
| Strategie | Tagesplan | Tagesplan des Videos, Tokio-Ausbruch, Box-Ausbruch, RSI-Divergenz oder Fibonacci-Rücksetzer |
| Zeiteinheit | 1 Minute | Kerzen für Box, RSI und Fibonacci (1 oder 5 Minuten); der Tagesplan nutzt immer 1 Minute, den Tokio-Ausbruch immer 5 Minuten |
| Tokio-Spanne | 19:00–04:00 | oder 20:00–03:00 New York |
| RSI: 70/30-Regel | an | erster RSI-Punkt unter 30 (über 70), zweiter zwischen 30 und 70 |
| Fibonacci: EMA 200 | an | Fibonacci-Einstiege nur auf der Seite der EMA 200 (nicht im Tagesplan) |
| Risiko je Trade | 1 % | vom Kontostand, über den Stop-Abstand in Lots umgerechnet |
| Hebel höchstens | 30 | die Position ist höchstens das 30-Fache des Kapitals; bei sehr engem Stop riskiert ein Trade dann weniger als 1 % |
| Uhr des Servers | New York + 7 | die übliche Serverzeit (IC Markets, Pepperstone u. a.): 17:00 New York ist Mitternacht. Bei fester UTC-Zeit „UTC + Versatz“ wählen. |
| Schließen um | 16:58 New York | alle Positionen; offene Limits werden schon um 16:30 gelöscht |
| Magic Number | 26102800 | +0 Tokio, +1 Box, +2 RSI, +3 Fibonacci |
| Einschwingen | 20.000 M1-Kerzen | beim Start werden Indikatoren und Wendepunkte aus der Historie aufgebaut, ohne zu handeln |
| Zusatzkommission | 0 | nur für die Statistik im Journal: Kommission je Lot und Seite, falls der Tester keine bucht |

Die Einstellungen der 13 Varianten aus dem Backtest:

| Variante im Backtest | Strategie | Zeiteinheit | weitere Eingaben |
|---|---|---|---|
| Tagesplan des Videos | Tagesplan | – | Tokio-Spanne 19:00–04:00 |
| Tokio-Ausbruch 19–04 / 20–03 | Tokio-Ausbruch | – | Tokio-Spanne |
| Box-Ausbruch (1m / 5m) | Box-Ausbruch | 1 / 5 Minuten | |
| RSI-Divergenz mit / ohne 70/30-Regel | RSI-Divergenz | 1 / 5 Minuten | 70/30-Regel an / aus |
| Fibonacci mit EMA 200 / ohne Filter | Fibonacci-Rücksetzer | 1 / 5 Minuten | EMA 200 an / aus |

## Strategietester

- Modell *Jeder Tick basierend auf realen Ticks*: Dann rechnet der Tester mit den echten Spreads deines Brokers.
- Ein Hedging-Konto für den Tagesplan, weil dort der Tokio-Trade neben den Fibonacci-Scalps läuft. Auf einem
  Netting-Konto startet der EA den Tagesplan nicht.
- Im Journal stehen am Ende Trades, Trefferquote und das mittlere R je Teilstrategie. Das Optimierungskriterium
  *Benutzerdefiniert* ist das mittlere R je Trade nach Kosten.
- Prüfe in der Liste der Deals, ob der Tester die Kommission bucht (Spalte *Kommission*). Wenn nicht, trage
  sie unter *Zusatzkommission* ein, damit wenigstens die R-Statistik sie enthält (IC Markets Raw: 3,25 EUR je
  Lot und Seite bei FX und Metallen).

## Abweichungen vom Backtest

Der Kern ist derselbe wie im Backtest: `backtest/check_ea.py` übersetzt `ScalpingCore.mqh` nach C++, lässt ihn
mit simulierten Ausführungen nach den Regeln von `scalping.py` laufen und vergleicht jeden Trade. Auf EURUSD
(2005–2020, 5,6 Mio. Minutenkerzen), dem S&P 500 und Bitcoin sind alle 13 Varianten identisch, Trade für
Trade. Im Terminal gibt es dennoch Unterschiede:

- Echte Ausführung: Market-Orders zum Ask bzw. Bid statt zum Mittelkurs, Spread und Kommission wie beim Broker.
- Das Ziel einer Fibonacci-Order kann schon in der Minute der Ausführung erreicht werden (der Backtest lässt
  in dieser Minute nur den Stop zu).
- Eine Fibonacci-Limit-Order wird beim ersten Tick gelöscht, der den Impuls verlängert; der Backtest sieht nur
  ganze Minuten und löscht im Zweifel zuerst.
- Positionen schließen um 16:58 New York statt zum Schluss der letzten Minute vor 17:00.
- Bei zu kleinem Konto für das Mindestlot oder bei zu geringem Abstand zum Kurs (Stop-Level des Brokers)
  entfällt ein Trade.
