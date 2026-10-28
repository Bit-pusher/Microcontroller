# Backtest: Strategien auf Basis von AI-SuperTrend (KNN)

Getestet wird, ob sich aus `AI_SuperTrend_KNN.mq5` eine profitable Handelsstrategie
ableiten lässt, und zwar mit echten historischen Kursen und realistischen Kosten.

## Ausführen

```bash
python3 fetch_data.py   # lädt die Kursdaten nach data/
python3 backtest.py     # rechnet alles, schreibt results/results.json
```

Benötigt werden `g++`, `numpy` und `pandas`. Die Indikatorwerte stammen direkt aus der
MQL5-Datei: `harness/convert.py` übersetzt sie nach C++, `harness/shim.h` stellt die
benötigten MQL5-Funktionen bereit, `harness/runner.cpp` gibt die Puffer aus. Es gibt
also keine zweite Implementierung, die vom Indikator abweichen könnte.

## Daten

Echte Kurse aus den Beispieldaten von [QuantConnect Lean](https://github.com/QuantConnect/Lean/tree/master/Data):

| Markt | Art | Zeitraum | Bars (H1) |
|---|---|---|---|
| EURUSD | Oanda Bid/Ask | 2007–2018 | 74.439 |
| NZDUSD | Oanda Bid/Ask | 2007–2018 | 74.451 |
| XAUUSD | Oanda Bid/Ask | 2006–2019 | 76.499 |
| SPY | Trade-Kurse (Handelszeit) | 1998–2021 | 40.832 (+ 5.849 D1) |

H4 wird aus H1 zusammengesetzt. Der Indikator läuft wie in MT5 auf Bid-Kursen.

## Ausführungsmodell

- Die Regel entscheidet beim Schluss von Bar t, ausgeführt wird zur Eröffnung von Bar t+1.
- Jede Ausführung zahlt den halben Spread dieser Eröffnung, eine Runde also genau
  einen Spread (FX und Gold, echte historische Spreads). Bei SPY sind es 2 Basispunkte pro Seite.
- Positionsgröße 1x Kontokapital mit Zinseszins, kein Hebel.
- Nicht berücksichtigt: Swaps/Finanzierungskosten (FX, Gold) und Dividenden (SPY, auch nicht bei Buy & Hold).
- Gewertet wird erst ab dem ersten Bar, an dem der KNN rechnet (Aufwärmphase ca. 2.200 Bars).
- Plausibilitätschecks der Engine: Eine Strategie, die den nächsten Bar kennt, erzielt absurde Gewinne,
  dieselbe Information erst beim Schluss verwendet nicht. Buy & Hold entspricht exakt dem Kursverhältnis,
  ein Round Trip kostet genau einen Spread.

## Strategien

| Name | Regel |
|---|---|
| SuperTrend | Immer im Markt in SuperTrend-Richtung (Vergleich ohne KNN) |
| KNN State | Immer im Markt im bestätigten Zustand des Indikators (Major-Long/Short-Pfeile) |
| KNN Trend | Nur im Markt, solange bestätigter Zustand und SuperTrend übereinstimmen (farbige Trendfläche), sonst flach |
| Buy & Hold | Kaufen und halten |

## Ergebnis 1: Standardparameter (ATR 10, Faktor 2, K 10, Schwelle 0,9)

CAGR / max. Drawdown / Sharpe nach Kosten, gesamter Testzeitraum:

| Serie | Buy & Hold | SuperTrend | KNN State | KNN Trend |
|---|---|---|---|---|
| EURUSD H1 | −1,4 % / −35 % / −0,09 | −1,9 % / −40 % / −0,14 | −2,0 % / −41 % / −0,15 | −1,8 % / −39 % / −0,17 |
| NZDUSD H1 | −0,8 % / −40 % / 0,01 | −12,0 % / −81 % / −0,80 | −3,1 % / −58 % / −0,16 | −7,4 % / −66 % / −0,56 |
| XAUUSD H1 | 6,0 % / −45 % / 0,42 | −2,8 % / −49 % / −0,06 | 1,6 % / −35 % / 0,18 | −0,1 % / −28 % / 0,07 |
| SPY H1 | 5,2 % / −57 % / 0,36 | −6,3 % / −83 % / −0,27 | −3,8 % / −83 % / −0,11 | −4,6 % / −77 % / −0,22 |
| EURUSD H4 | −2,8 % / −35 % / −0,22 | −2,0 % / −44 % / −0,15 | −3,6 % / −39 % / −0,30 | −2,7 % / −35 % / −0,26 |
| NZDUSD H4 | −1,4 % / −38 % / −0,03 | −4,9 % / −63 % / −0,29 | −4,3 % / −51 % / −0,25 | −4,6 % / −54 % / −0,34 |
| XAUUSD H4 | 6,1 % / −45 % / 0,42 | 2,1 % / −37 % / 0,21 | 4,5 % / −30 % / 0,33 | 4,0 % / −27 % / 0,32 |
| SPY D1 | 7,9 % / −56 % / 0,48 | −1,1 % / −64 % / 0,04 | −3,2 % / −73 % / −0,06 | −1,6 % / −65 % / −0,02 |

Auf H1 entstehen rund 250 Trades pro Jahr. Die Spreads fressen den ohnehin kleinen
Bruttovorteil vollständig auf.

## Ergebnis 2: Strategieentwicklung mit In-Sample/Out-of-Sample-Trennung

56 Varianten: Regel (SuperTrend, KNN State, KNN Trend) × Zeitrahmen (H1 oder H4/D1)
× Richtung (Long+Short oder nur Long) × ATR-Faktor (2, 3) × Schwelle (0,8 / 0,9 / 0,95).
**Eine** Regel für alle vier Märkte wird nach dem mittleren Sharpe der ersten 60 % eines
gemeinsamen Zeitraums ausgewählt und dann auf den restlichen 40 % geprüft.

Ausgewählt wurde **KNN State, H4 (FX/Gold) bzw. D1 (SPY), nur Long, Faktor 3, Schwelle 0,9**.

| Markt | Out-of-Sample ab | CAGR | max. DD | Sharpe | Buy & Hold CAGR / DD / Sharpe |
|---|---|---|---|---|---|
| EURUSD | Sep 2014 | −2,1 % | −16,0 % | −0,32 | −2,3 % / −19,3 % / −0,22 |
| NZDUSD | Sep 2014 | −3,6 % | −19,3 % | −0,40 | −3,9 % / −22,0 % / −0,31 |
| XAUUSD | Jul 2014 | 2,9 % | −12,4 % | 0,36 | −0,1 % / −21,6 % / 0,05 |
| SPY | Mai 2015 | 8,1 % | −18,9 % | 0,69 | 11,3 % / −34,9 % / 0,67 |

Im Mittel fällt das Sharpe-Verhältnis von 0,26 (In-Sample) auf 0,08 (Out-of-Sample).
Weitere Befunde:

- Auf EURUSD und NZDUSD erreichen nur 2 bzw. 1 von 56 Varianten Out-of-Sample ein positives Sharpe.
- Gegen einen einfachen SuperTrend mit gleichem Zeitrahmen, gleicher Richtung und gleichem Faktor
  gewinnt die KNN-Variante Out-of-Sample in 101 von 192 Vergleichen, also etwa wie ein Münzwurf.

## Ergebnis 3: Vergleich mit bekannten Indikatoren

`compare.py` (`python3 compare.py`, nach `backtest.py`) testet zehn verbreitete Regeln mit
Lehrbuchparametern unter denselben Bedingungen wie oben: gleiche Märkte, Kosten und
In-Sample/Out-of-Sample-Zeiträume, jeweils Long+Short und nur Long. Tagesbars für FX und Gold
enden um 17:00 New Yorker Zeit. Ausgewählt wird wieder nach dem mittleren In-Sample-Sharpe.

Portfolio aus allen vier Märkten zu gleichen Teilen, Out-of-Sample (6,7 Jahre), beste Seite je Regel:

| Regel | Sharpe In-Sample | CAGR | max. DD | Sharpe | t-Wert |
|---|---|---|---|---|---|
| AI-SuperTrend KNN (gewählte Regel, nur Long) | 0,55 | 1,5 % | −8,0 % | 0,35 | 0,9 |
| Donchian 20/10 (D1, nur Long) | 0,43 | 0,9 % | −6,9 % | 0,30 | 0,8 |
| Buy & Hold | 0,44 | 1,8 % | −15,3 % | 0,30 | 0,8 |
| Bollinger 20/2 Rückkehr (H4, Long+Short) | −0,35 | 1,3 % | −13,5 % | 0,28 | 0,7 |
| SMA 200 (D1, nur Long), In-Sample gewählt | 0,69 | 0,9 % | −7,6 % | 0,24 | 0,6 |
| SuperTrend 10/3 (D1, nur Long) | 0,62 | 0,7 % | −10,0 % | 0,18 | 0,5 |
| Golden Cross 50/200 (D1, nur Long) | 0,69 | 0,6 % | −10,2 % | 0,15 | 0,4 |
| RSI(2) mit SMA-200-Filter (D1, nur Long) | 0,46 | 0,2 % | −5,9 % | 0,13 | 0,3 |
| MACD 12/26/9 (D1, nur Long) | 0,42 | 0,3 % | −9,6 % | 0,08 | 0,2 |
| Donchian 55/20 (D1, nur Long) | 0,27 | 0,1 % | −8,1 % | 0,06 | 0,2 |
| Momentum 12 Monate (D1, nur Long) | 0,33 | 0,0 % | −10,4 % | 0,03 | 0,1 |
| Bollinger 20/2 Rückkehr (H1, Long+Short) | −1,24 | −3,7 % | −25,0 % | −0,78 | −2,0 |

- Keine Regel ist belastbar besser als der AI-SuperTrend oder als Buy & Hold: Alle t-Werte liegen
  unter 1, die Unterschiede sind Zufall. Nur die Bollinger-Rückkehr auf H1 ist deutlich negativ
  (die Spreads bei rund einem Trade pro Tag).
- Die In-Sample beste Regel (SMA 200, nur Long) fällt von 0,69 auf 0,24.
- Gemeinsam ist den Long-only-Trendfiltern auf D1 (SMA 200, Donchian, SuperTrend, AI-SuperTrend):
  Sie halbieren ungefähr den Drawdown gegenüber Buy & Hold bei ähnlichem oder etwas niedrigerem
  Sharpe. Das ist Risikobegrenzung, kein Renditevorteil.

## Ergebnis 4: Populäre TradingView-Skripte

`tradingview.py` (`python3 tradingview.py`, nach `compare.py`) testet elf viel genutzte
Community-Skripte mit ihren Standardeinstellungen. Die Logik ist aus dem veröffentlichten
Pine-Code übersetzt (Kopien auf GitHub, die Links stehen in `SCRIPTS`). Gehandelt wird wie in
den Strategie-Versionen der Skripte: Ein Signal eröffnet oder dreht die Position. Zeitrahmen sind
H4 (SPY: H1) und D1, jeweils Long+Short und nur Long, also 44 Varianten. Protokoll, Kosten und
Zeiträume sind dieselben wie oben.

- **Machine Learning: Lorentzian Classification** (jdehorty) ist hier ebenfalls selbst
  implementiert. `check_lorentzian.py` vergleicht die Implementierung mit vier TradingView-Exporten
  des Originals: Features, Vorhersagen und alle Kauf-/Verkaufssignale stimmen Bar für Bar überein.
  Das Original wählt sein Trainingsfenster nach dem letzten Bar des Charts. Getestet wird
  deshalb in Blöcken von 2.000 Bars, jeweils so, wie der Chart am Blockende ausgesehen hätte.
- **Nicht getestet:** Smart Money Concepts (LuxAlgo) zeichnet Zonen für diskretionäres Trading und
  hat keine mechanischen Signale (daraus abgeleitete Regeln: Ergebnis 6). Nadaraya-Watson Envelope (LuxAlgo) zeichnet in der Standardeinstellung
  nachträglich um. ChrisMoodys MACD-MTF entspricht auf dem Chart-Zeitrahmen dem MACD (oben getestet).
  Für QQE MOD war kein Quellcode erreichbar.

Portfolio aus allen vier Märkten, je Skript die In-Sample beste Variante, Out-of-Sample (6,7 Jahre):

| Skript (gewählte Variante) | Sharpe In-Sample | Sharpe OOS | t-Wert | CAGR | max. DD |
|---|---|---|---|---|---|
| AlphaTrend, KivancOzbilgic (D1, nur Long) | 0,63 | 0,30 | 0,8 | 1,1 % | −9,4 % |
| WaveTrend Oscillator, LazyBear (H4/H1, nur Long) | 0,34 | 0,32 | 0,8 | 1,5 % | −8,9 % |
| Chandelier Exit, everget (D1, nur Long) | 0,44 | −0,01 | −0,0 | −0,1 % | −13,1 % |
| Optimized Trend Tracker, KivancOzbilgic (H4/H1, nur Long) | 0,22 | −0,02 | −0,0 | −0,2 % | −14,2 % |
| Hull Suite, InSilico (D1, nur Long) | 0,41 | −0,05 | −0,1 | −0,3 % | −11,1 % |
| HalfTrend, everget (H4/H1, nur Long) | 0,32 | −0,10 | −0,3 | −0,5 % | −13,7 % |
| Range Filter, guikroth (H4/H1, nur Long) | 0,27 | −0,18 | −0,5 | −0,9 % | −16,3 % |
| Lorentzian Classification, jdehorty (D1, nur Long) | 0,47 | −0,21 | −0,5 | −0,3 % | −4,6 % |
| UT Bot Alerts, QuantNomad (H4/H1, nur Long) | 0,21 | −0,21 | −0,5 | −1,0 % | −13,4 % |
| Squeeze Momentum, LazyBear (D1, nur Long) | 0,28 | −0,26 | −0,7 | −0,8 % | −8,0 % |
| SSL Channel (H4/H1, nur Long) | 0,47 | −0,36 | −0,9 | −1,7 % | −17,4 % |
| *Vergleich: AI-SuperTrend KNN (gewählte Regel)* | 0,55 | 0,35 | 0,9 | 1,5 % | −8,0 % |
| *Vergleich: Buy & Hold* | 0,44 | 0,30 | 0,8 | 1,8 % | −15,3 % |

- Nach dem Protokoll (mittleres In-Sample-Sharpe) gewählt wurde die Lorentzian Classification auf D1,
  nur Long. Out-of-Sample liegt ihr Sharpe bei −0,21.
- 14 der 44 Varianten haben Out-of-Sample ein positives Sharpe, 4 schlagen Buy & Hold, keine mit einem
  t-Wert über 2. Das beste Ergebnis im Nachhinein (Lorentzian, D1, Long+Short: 0,44, t 1,1) hätte man
  vorher nicht wählen können.
- Die Rangkorrelation zwischen In-Sample und Out-of-Sample beträgt nur 0,24: Gute Ergebnisse in den
  ersten Jahren sagten kaum etwas über die späteren voraus.
- Auf H4/H1 sind die meisten Skripte nach Kosten deutlich negativ (bis −0,78, t −2,0).

## Ergebnis 5: Krypto

`fetch_crypto.py` lädt Binance-Spot-Kerzen (H4, D1) für BTC, ETH, BNB, XRP, ADA und LINK gegen USDT
aus dem Spiegel [finom/static-klines](https://github.com/finom/static-klines), vom Listing bis
Oktober 2026. `crypto.py` testet darauf alle Regeln von oben: AI-SuperTrend (H4; für D1 bräuchte der
KNN sechs Jahre Anlauf), die klassischen Indikatoren und die TradingView-Skripte, jeweils
Long+Short und nur Long, zusammen 70 Varianten. Kosten 0,1 % je Seite (Binance-Spotgebühr),
keine Funding-Kosten. In-Sample ab 400 Tagen nach dem Listing bis Ende 2022, Out-of-Sample
von Januar 2023 bis Oktober 2026. Der Out-of-Sample-Zeitraum enthält den Aufschwung bis Oktober 2025
und den Einbruch danach (BTC −53 %, ETH −68 %, ADA −88 % vom Hoch).

Portfolio der sechs Paare zu gleichen Teilen:

| Regel | Sharpe IS | Sharpe OOS | t-Wert | CAGR OOS | max. DD OOS |
|---|---|---|---|---|---|
| Hull Suite (H4, nur Long), In-Sample gewählt | 1,57 | 0,82 | 1,6 | 27,2 % | −53,6 % |
| AI-SuperTrend KNN State (H4, nur Long, Faktor 3, Schwelle 0,9), auf FX/Gold/SPY gewählt | 1,30 | 0,79 | 1,5 | 23,4 % | −38,4 % |
| SMA 200 (D1, nur Long), auf FX/Gold/SPY gewählt | 1,12 | 0,55 | 1,1 | 14,6 % | −44,3 % |
| Lorentzian Classification (D1, nur Long), auf FX/Gold/SPY gewählt | 0,22 | 0,24 | 0,5 | 1,9 % | −17,6 % |
| Squeeze Momentum (D1, nur Long), bestes OOS-Ergebnis im Nachhinein | 1,29 | 1,01 | 2,0 | 25,4 % | −30,2 % |
| Buy & Hold | 0,97 | 0,81 | 1,6 | 35,3 % | −66,4 % |

- Die gewählte Regel erreicht praktisch das Sharpe von Buy & Hold (0,82 gegen 0,81), bei geringerer
  Rendite und kaum kleinerem Drawdown. Von 35 Long-only-Varianten schlagen nur 3 das Sharpe von
  Buy & Hold, von 35 Long+Short-Varianten keine. Leerverkäufe haben in Krypto durchweg geschadet.
- Die auf FX/Gold/SPY gewählte AI-SuperTrend-Regel hält auf diesem völlig neuen Markt, was sie dort
  zeigte: Sharpe etwa wie Buy & Hold, Drawdown deutlich kleiner (−38 % statt −66 %), Rendite niedriger.
- Die Rangkorrelation zwischen In-Sample und Out-of-Sample ist hier hoch (0,71). Sie kommt fast ganz
  aus dem Gegensatz „nur Long“ gegen „Long+Short“ bei einem stark steigenden Markt, nicht aus der
  Qualität einzelner Indikatoren.
- Die Auswahl der Paare (heute noch große Coins) bevorzugt rückblickend Buy & Hold und alle Long-Regeln.

## Ergebnis 6: Smart Money Concepts (LuxAlgo)

Der Indikator [Smart Money Concepts (SMC) [LuxAlgo]](https://www.tradingview.com/script/CnB3fSph-Smart-Money-Concepts-LUX/)
erzeugt keine Einstiegs- oder Ausstiegssignale. Er zeichnet Marktstruktur (BOS und CHoCH, intern
mit 5 Bars und als Swing mit 50 Bars), Order Blocks, gleiche Hochs/Tiefs (EQH/EQL), Fair Value Gaps,
Strong/Weak High/Low und Premium/Discount-Zonen und meldet diese Ereignisse über 16 Alerts.
Was man daraus handelt, bleibt dem Nutzer überlassen.

`smc.py` rechnet die Logik des Pine-Skripts Bar für Bar nach (ohne Fair Value Gaps und
Tages-/Wochen-/Monatslevels, die hier nicht gebraucht werden) und leitet daraus Positionen ab.
`check_smc.py` vergleicht das mit dem, was das Original auf TradingView gezeichnet hat: dem Export
aus der Parity-Testumgebung von [GeneralTradingSarl/Smart-Money-Concepts](https://github.com/GeneralTradingSarl/Smart-Money-Concepts)
(5.044 AAPL-15-Minuten-Bars, Standardeinstellungen; geladen werden nur Daten). Alle 278 Strukturlinien
und -labels, die 43 EQH/EQL-Linien und -Labels, Strong/Weak High/Low, die 5 angezeigten Order Blocks
und die Trendfarbe aller 5.044 Kerzen stimmen überein (`ALL IDENTICAL`). Jedes Ereignis steht beim
Schluss seines Bars fest; ein Swing-Punkt wird wie im Original erst 50 Bars später bestätigt.

Lizenz: Das Original steht unter [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/),
`smc.py` als abgeleitetes Werk ebenfalls (Namensnennung, nicht kommerziell, gleiche Lizenz).

Abgeleitete Regeln (`smc.RULES`):

| Regel | Einstieg | Ausstieg |
|---|---|---|
| Swing-Struktur | Long nach bullischem Swing-BOS/-CHoCH, Short nach bärischem | Gegenteiliger Swing-Bruch (immer im Markt) |
| Interne Struktur | Ebenso mit der internen Struktur (= Kerzenfarbe des Indikators) | Gegenteiliger interner Bruch |
| Intern + Swing gleichgerichtet | Interne Struktur in Richtung der Swing-Struktur | Sobald beide auseinanderlaufen (flach) |
| Order-Block-Retest | Rückkehr in den jüngsten intakten internen Order Block in Swing-Richtung (Tief ≤ Oberkante, Schluss ≥ Unterkante); jeder Block nur einmal | Block gebrochen (Mitigation des Indikators: Tief unter der Unterkante) oder interner Bruch gegen die Position |
| CHoCH im Discount/Premium | Interner bullischer CHoCH bei bullischer Swing-Struktur mit Schluss in der unteren Hälfte der Swing-Spanne; Short spiegelbildlich in der oberen Hälfte | Nächster gegenteiliger interner Bruch |

`smc_test.py` (`python3 smc_test.py`, nach `backtest.py` und `fetch_crypto.py`) testet jede Regel auf
H4 (SPY: H1) und D1, Long+Short und nur Long: 20 Varianten je Universum, mit Standardeinstellungen
des Indikators. FX/Gold/SPY mit den Zeiträumen und Spreads von oben, Krypto mit den sechs Paaren und
0,1 % je Seite aus Ergebnis 5. Gewählt wird wieder nach dem mittleren In-Sample-Sharpe.

Portfolio, je Regel die In-Sample beste Variante, FX/Gold/SPY (Out-of-Sample 6,7 Jahre):

| Regel (Variante) | Sharpe IS | Sharpe OOS | t-Wert | CAGR OOS | max. DD OOS | Trades/Jahr |
|---|---|---|---|---|---|---|
| Swing-Struktur (H4/H1, nur Long), gewählt | 0,44 | 0,37 | 1,0 | 1,4 % | −7,4 % | 2,4 |
| Interne Struktur (D1, nur Long) | 0,36 | 0,29 | 0,8 | 1,1 % | −9,5 % | 3,2 |
| Intern + Swing gleichgerichtet (H4/H1, nur Long) | 0,23 | 0,21 | 0,5 | 0,6 % | −7,9 % | 12,2 |
| Order-Block-Retest (H4/H1, nur Long) | 0,04 | −0,25 | −0,6 | −0,6 % | −8,1 % | 13,3 |
| CHoCH im Discount/Premium (H4/H1, Long+Short) | 0,28 | 0,13 | 0,3 | 0,2 % | −3,5 % | 3,2 |
| *Buy & Hold* | 0,44 | 0,30 | 0,8 | 1,8 % | −15,3 % | |

Krypto (Out-of-Sample 3,8 Jahre):

| Regel (Variante) | Sharpe IS | Sharpe OOS | t-Wert | CAGR OOS | max. DD OOS | Trades/Jahr |
|---|---|---|---|---|---|---|
| Intern + Swing gleichgerichtet (H4, nur Long), gewählt | 1,62 | 0,66 | 1,3 | 15,8 % | −32,9 % | 18,3 |
| Swing-Struktur (H4, nur Long) | 1,37 | 0,67 | 1,3 | 19,9 % | −49,2 % | 4,5 |
| Interne Struktur (D1, nur Long) | 1,26 | 0,80 | 1,6 | 25,3 % | −43,5 % | 5,2 |
| Order-Block-Retest (D1, nur Long) | 1,51 | −0,32 | −0,6 | −6,3 % | −29,6 % | 3,3 |
| CHoCH im Discount/Premium (D1, nur Long) | 0,64 | 0,68 | 1,3 | 6,3 % | −9,6 % | 0,8 |
| *Buy & Hold* | 0,97 | 0,81 | 1,6 | 35,3 % | −66,4 % | |

- FX/Gold/SPY: Die gewählte Swing-Struktur (nur Long) liegt Out-of-Sample knapp über Buy & Hold
  (0,37 gegen 0,30, t 1,0) bei halbem Drawdown und geringerer Rendite, ähnlich wie die
  AI-SuperTrend-Regel (0,35). Der Vorteil kommt fast nur von SPY (0,83); EURUSD 0,23, NZDUSD −0,30,
  Gold −0,15. Long+Short liegen die zehn Varianten zwischen −0,45 und 0,17, im Mittel bei −0,09.
  2 von 20 Varianten schlagen Buy & Hold.
- Krypto: Gewählt wurde „Intern + Swing gleichgerichtet“ (H4, nur Long), Out-of-Sample 0,66 gegen 0,81
  für Buy & Hold, mit halbem Drawdown (−33 % statt −66 %). Keine der 20 Varianten schlägt Buy & Hold.
- Der Order-Block-Retest, der typischste SMC-Einstieg, verliert Out-of-Sample in beiden Universen.
  Auf Krypto D1 fällt er von 1,51 In-Sample auf −0,32 (Long+Short: −0,91, t −1,8).
- CHoCH im Discount/Premium handelt sehr selten (EURUSD D1: vier Signale in zwölf Jahren, alle
  In-Sample). Die Zahlen dieser Regel sind entsprechend unsicher.
- Die Rangkorrelation zwischen In-Sample und Out-of-Sample beträgt 0,59 (FX/Gold/SPY) und
  0,64 (Krypto). Sie kommt wieder vor allem aus „nur Long“ gegen „Long+Short“.
- Die Struktur-Regeln verhalten sich wie andere Trendfilter (SMA 200, SuperTrend): Sie halbieren den
  Drawdown auf steigenden Märkten, einen messbaren Vorteil nach Kosten liefern sie nicht.

## Ergebnis 7: DR/IDR (Defining Range)

Das Konzept stammt von TheMas7er (November 2022). Auf TradingView zeichnen es unter anderem
[DR/IDR V1.5](https://www.tradingview.com/script/upzvFFch-DR-IDR-V1/) (TheMas7er und bmistiaen,
MPL-2.0) und [DR/IDR Candles (LuxAlgo)](https://www.tradingview.com/script/wRtmtWIQ-DR-IDR-Candles-LuxAlgo/).
Die Definitionen hier folgen dem Quellcode von V1.5. Auf 5-Minuten-Kerzen gilt:

- **DR:** Hoch und Tief der Kerzen, die in der ersten Stunde einer Session beginnen, mit Dochten.
  Reguläre Session (RDR) 09:30–10:30 New York, Linien bis 16:00; Abend-Session (ADR) 19:30–20:30,
  Linien bis 02:00; Overnight-Session (ODR) 03:00–04:00, Linien bis 08:30.
- **IDR:** höchster und tiefster Kerzenkörper (Open/Close) derselben Stunde.
- **Regeln:** Schließt nach dieser Stunde eine 5-Minuten-Kerze über dem DR-Hoch, soll das DR-Tief das
  Tief der Session bleiben (die V1-Beschreibung nennt „80 %“). Bei einem Schluss unter dem DR-Tief gilt
  das Umgekehrte. Ein Schluss jenseits der IDR gilt als frühes Signal.
- **Ziele:** „Standardabweichungen“, also Vielfache von 0,5 × IDR-Spanne jenseits der IDR. V1.5
  zeichnet sie nur aus der IDR der regulären Session; hier nutzt jede Session ihre eigene IDR.

Die Skripte zeichnen nur diese Linien und legen keine Ein- oder Ausstiege fest.

`fetch_indices.py` lädt Oanda-Minutendaten der CFDs auf S&P 500, Nasdaq 100 und Russell 2000
(Januar 2005 bis Mai 2020, Mittelkurse) aus [FutureSharks/financial-data](https://github.com/FutureSharks/financial-data)
und baut daraus 5-Minuten-Kerzen. Die Stunde 09:30–10:30 ist an 99 % der Tage vollständig. Nachts
und abends fehlen in den frühen Jahren viele Kerzen (ADR bei US2000 bis 2017); übersprungen werden
Tage, an denen in der DR-Stunde weniger als 10 von 12 Kerzen vorliegen. `check_dridr.py` prüft Niveaus,
Zeitzone (Sommer- und Winterzeit), Sessions über Mitternacht und Orderausführung an 25 von Hand
durchgerechneten Fällen. Mit einem TradingView-Export vergleicht es zusätzlich jede Session mit dem
Original: `tradingview/DR_IDR_V1.5_export.pine` ist V1.5 mit angehängten unsichtbaren Plots der
Niveaus. Auf einem 5-Minuten-Chart mit *Chartdaten exportieren* als CSV speichern, dann
`python3 check_dridr.py export.csv`. `dridr_test.py` rechnet alles Folgende.

### Stimmt die 80-%-Regel?

Gemessen wird: Nach dem ersten Schluss jenseits der DR (ab 10:30), wie oft bleibt die Gegenseite der DR
bis Sessionende unberührt? Als Placebo dienen dieselben Tage mit zufällig umsortierten Kerzen nach
10:30: gleiche DR, gleiche Schwankung, aber keine Abfolge mehr. Der „Trade“ ist die Regel wörtlich:
Einstieg nach der Bestätigung, Stop an der DR-Gegenseite, Ausstieg um 16:00, ohne Kosten.

RDR, jeweils In-Sample (2005–2014) / Out-of-Sample (2015 bis Mai 2020):

| Markt | DR-Spanne (Median) | Gegenseite hält | Placebo | Trade, wenn sie hält | Trade, wenn nicht | Trade im Mittel |
|---|---|---|---|---|---|---|
| SPX500 | 0,51 % / 0,38 % | 76 % / 76 % | 74 % / 72 % | +22,5 / +16,6 bp | −66,7 / −54,3 bp | +1,4 / −0,4 bp |
| NAS100 | 0,70 % / 0,58 % | 79 % / 80 % | 77 % / 80 % | +21,2 / +17,8 bp | −81,9 / −73,9 bp | −0,6 / −0,6 bp |
| US2000 | 0,86 % / 0,68 % | 79 % / 81 % | 80 % / 82 % | +29,0 / +17,0 bp | −97,8 / −78,0 bp | +2,9 / −1,1 bp |

- Die Regel stimmt: Nach einer Bestätigung hält die Gegenseite in 76–81 % der Fälle (ADR 66–74 %,
  ODR 69–75 %). Die 80 % sind also nicht erfunden.
- Für die reguläre Session sagt das kaum etwas über die Richtung. Auf den Placebo-Tagen hält die
  Gegenseite fast genauso oft (72–82 %). Die Quote folgt aus der Geometrie: Wer über dem DR-Hoch
  schließt, ist mindestens eine DR-Spanne vom DR-Tief entfernt. Diese Strecke legt der Kurs im Rest
  des Tages meistens nicht mehr zurück, auch ohne jede Regelmäßigkeit.
- Abends und nachts liegt die Quote über dem Placebo: ADR um 4–14 Punkte (Placebo 55–66 %), ODR um
  1–8 Punkte (Placebo 65–71 %). Dort
  steckt also etwas Abfolge in den Kursen. Ein Teil davon kann auch aus dem Tagesmuster der Schwankung
  kommen, das der Placebo ebenfalls zerstört.
- Für den Handel zählt die Auszahlung. Stimmt die Regel, bringt der Trade im Mittel +17 bis +29 bp;
  stimmt sie nicht, kostet er −54 bis −98 bp. Im Mittel bleiben −1 bis +3 bp vor Kosten (ADR +0,5 bis
  +2,1 bp, ODR −0,3 bis −1,8 bp). Das ist meist weniger als ein Round Trip kostet (2 bp).

### Handelssysteme

Vorab festgelegt sind 108 Varianten. Dimensionen:

- Session: RDR, ADR oder ODR.
- Einstieg: nach dem ersten Schluss jenseits der DR, nach dem ersten Schluss jenseits der IDR oder als
  Limit-Order beim Rücklauf an die IDR nach der DR-Bestätigung.
- Stop: DR-Gegenseite oder DR-Mitte.
- Ziel: 0,5 SD, 1 SD oder keins (Ausstieg zum Sessionende).
- Richtung: Long+Short oder nur Long.

Ein Trade pro Session und Tag. Kosten 1 bp je Seite, etwa ein CFD-Spread von 0,5 Indexpunkten. Bei
ES-/NQ-Futures kosten Spread und Kommission ab 2015 eher 0,5–0,8 bp je Seite, vor 2010 mehr.
Market-Orders werden zur nächsten Eröffnung ausgeführt, Limits, Stops und Ziele zu ihrem Kurs (bei
einer Lücke zur Eröffnung). Berührt eine Kerze Stop und Ziel, zählt der Stop. Gewählt wird nach dem
mittleren In-Sample-Sharpe der drei Märkte.

Portfolio der drei Indizes zu gleichen Teilen, Out-of-Sample 5,4 Jahre:

| Variante | Sharpe IS | Sharpe OOS | t-Wert | CAGR OOS | max. DD OOS | Trades/Jahr | Trefferquote |
|---|---|---|---|---|---|---|---|
| RDR: IDR-Bestätigung, Stop DR-Mitte, Ziel 1 SD, Long+Short (gewählt) | 0,39 | −0,70 | −1,6 | −4,1 % | −24,7 % | 247 | 46 % |
| RDR: DR-Bestätigung, Stop DR-Gegenseite, bis Sessionende, Long+Short (die Regel wörtlich) | −0,16 | −0,74 | −1,7 | −6,7 % | −35,0 % | 239 | 46 % |
| RDR: IDR-Bestätigung, Stop DR-Gegenseite, bis Sessionende, nur Long (bestes OOS-Ergebnis im Nachhinein) | 0,14 | −0,27 | −0,6 | −1,8 % | −14,8 % | 134 | 50 % |
| *Vergleich: jeden Tag Long von 10:30 bis 16:00* | −0,21 | −0,24 | −0,6 | −3,6 % | −30,7 % | ca. 250 | |
| *Vergleich: Buy & Hold* | 0,45 | 0,44 | 1,0 | 7,0 % | −35,3 % | | |

- Nach Kosten sind 8 der 108 Varianten Out-of-Sample positiv, alle aus der ADR und nur Long (bis 0,47,
  t 1,1). In-Sample war keine ADR-Variante positiv; gewählt werden konnten sie nicht. Bei RDR und ODR
  ist keine Variante nach Kosten positiv.
- In-Sample hatten die RDR-Varianten mit IDR-Einstieg vor Kosten ein Sharpe um 1 (gewählte Variante:
  1,13), Out-of-Sample noch 0,16. Das Momentum nach dem Ausbruch war in den Jahren um 2008 stärker;
  für die Kosten von rund 250 Trades im Jahr reicht es nicht. Bei 2 bp je Seite liegen alle fünf
  In-Sample besten Varianten Out-of-Sample bei −0,8 oder schlechter.
- Ziele bei 0,5 SD bringen die höchsten Trefferquoten (bis 70 %). Bei RDR liefern sie aber die
  schlechtesten Ergebnisse (mittleres OOS-Sharpe −1,21 gegen −0,70 ohne Ziel): kleine Gewinne, volle
  Verluste. Auch der Einstieg beim Rücklauf an die IDR schneidet bei RDR schlechter ab (−1,14 gegen
  −0,65 mit IDR-Einstieg).
- Die Overnight-Range ist durchweg deutlich negativ (mittleres OOS-Sharpe −1,9 gegen −0,9 bei RDR).
  Ihre Spanne ist mit rund 0,2 % so klein, dass die Kosten den Großteil aufzehren.
- Die Rangkorrelation zwischen In-Sample und Out-of-Sample ist hoch (0,70). Sie spiegelt vor allem die
  unterschiedliche Kostenlast (ODR gegen RDR, Ziele gegen Sessionende), nicht einen Vorteil.
- Nicht getestet: der von TheMas7er empfohlene Verzicht auf Tage mit wichtigen Nachrichten
  (CPI, FOMC, NFP) und diskretionäre Zusätze wie „Displacement“. CFD-Mittelkurse statt Futures,
  Daten nur bis Mai 2020.

### LuxAlgo DR/IDR Candles

[DR/IDR Candles](https://www.tradingview.com/script/wRtmtWIQ-DR-IDR-Candles-LuxAlgo/) (LuxAlgo,
CC BY-NC-SA 4.0) berechnet DR und IDR genauso wie V1.5, weicht sonst aber in mehreren Punkten ab:

- **Uhrzeit:** Die Sessions liegen auf einem festen Versatz von UTC−5 (Eingabe *UTC Offset*), nicht auf
  New Yorker Zeit. Im US-Sommer (März bis November) ist die „Regular“-DR deshalb 10:30–11:30 New York
  statt 09:30–10:30, die „Overnight“-DR 04:00–05:00 statt 03:00–04:00. Wer den Indikator im Sommer
  nach dem Original-Konzept nutzen will, muss den Offset auf −4 stellen.
- **Gültigkeit:** Die Linien laufen bis zur nächsten Session, ein Sessionende (16:00, 08:30) gibt es nicht.
  Keine Abend-Session (ADR).
- **Niveaus:** keine „Standardabweichungen“, sondern Retracements innerhalb der Range, standardmäßig
  nur 0,5 der IDR (die IDR-Mitte). Die Linienfarbe zeigt, ob der aktuelle Schluss über oder unter der
  DR liegt.

`tradingview/DR_IDR_Candles_LuxAlgo_export.pine` macht die vier Niveau-Plots des Originals für den
Export sichtbar (transparent statt ausgeblendet); `check_dridr.py` erkennt die Spalten und vergleicht
auf der UTC−5-Uhr. `dridr_test.py` testet LuxAlgos Standardeinstellungen als eigenes Raster von
96 Varianten: Sessions auf der UTC−5-Uhr (Handel bis 16:00 bzw. 08:30 dieser Uhr) und als
zusätzlicher Einstieg eine Limit-Order an der IDR-Mitte.

- Die Regel trifft auch mit dieser Uhr zu: Die Gegenseite hält in 73–80 % (Regular) und 63–71 %
  (Overnight) der Fälle, auf den Placebo-Tagen in 70–77 % bzw. 59–66 %.
- Gewählt wurde „IDR-Bestätigung, Stop DR-Mitte, bis Sessionende, Long+Short“ (Regular): In-Sample 0,50,
  Out-of-Sample −0,31 (t −0,7). Nach Kosten ist 1 von 96 Varianten Out-of-Sample positiv (0,17, t 0,4).
- Für dieselben Regeln schneidet die verschobene Regular-Session etwas weniger schlecht ab als die
  New Yorker (mittleres OOS-Sharpe −0,47 gegen −0,93), die verschobene Overnight-Session schlechter
  (−2,05 gegen −1,87). Positiv wird keine.
- Der Einstieg an der IDR-Mitte, LuxAlgos Standard-Niveau, ist der schlechteste aller Einstiege
  (mittleres OOS-Sharpe −1,67 Regular, −2,86 Overnight).

### Die Abend-Range (ADR)

Die ADR ist die einzige Session mit einem beständigen Vorteil vor Kosten: Alle 36 ADR-Varianten sind
ohne Kosten In-Sample und Out-of-Sample positiv (mittleres Sharpe 0,43 und 1,09). Der Vorteil ist
aber klein, im Mittel +0,7 bp (In-Sample) und +1,6 bp (Out-of-Sample) pro Trade.

| ADR: Rücklauf an die IDR, Stop DR-Gegenseite, bis Sessionende, nur Long | Sharpe IS | Sharpe OOS | t-Wert OOS | OOS ohne 2020 |
|---|---|---|---|---|
| 0,5 bp je Seite | 0,37 | 0,72 | 1,7 | 0,35 (t 0,8) |
| 1 bp je Seite | −0,01 | 0,31 | 0,7 | −0,20 |

- Erst bei sehr niedrigen Kosten (0,5 bp je Seite) wäre diese Variante unter den ADR-Varianten
  In-Sample die beste und in beiden Zeiträumen positiv. Bei 0,75 bp sind noch 2 von 36 ADR-Varianten
  In-Sample positiv.
- Out-of-Sample hängt sie stark an 2020: Von den Monaten Januar bis Mai 2020 kommen +5,3 %, aus den fünf
  Jahren davor zusammen +2,7 %. Ohne 2020 halbiert sich das Sharpe auf 0,35 (t 0,8).
- Die Rendite ist gering (1,5 % pro Jahr Out-of-Sample), weil die Position nur abends und nur an
  etwa 80 Tagen im Jahr läuft.
- Abends sind die Spreads breiter als tagsüber, und Stops rutschen in dünnen Märkten. Ob die 0,5 bp
  erreichbar sind, lässt sich nur mit echten Abend-Spreads prüfen, z. B. mit Tickdaten aus dem
  eigenen MT5-Konto (`mt5/HistoryExport.mq5`).

## Ergebnis 8: 1-Minuten-Scalping nach einem Video

Quelle ist das Video „The ONLY 1 Minute Scalping Guide You'll Ever Need“ (30 Minuten, auf `master`
abgelegt). Der Ton wurde mit Whisper (small.en über `sherpa-onnx`) transkribiert, die Bilder im Abstand
von 15 Sekunden angesehen. Der Sprecher handelt EURUSD auf 1 und 5 Minuten und ordnet den Markt einem
von drei Zuständen zu.

| Marktzustand | Regel im Video |
|---|---|
| Seitwärts | Box, wo der Kurs kein höheres Hoch und kein tieferes Tief mehr schafft. Schließt eine Kerze außerhalb, Einstieg in Ausbruchsrichtung; Stop in der Box-Mitte, Ziel 1,5 × Risiko. |
| Trend | Nach einem Impuls, der die letzte Struktur bricht, und 33 % Rücklauf: Limit-Order beim 0,618-Retracement, Stop am Impulsbeginn, Ziel am Impulsende (1:1,6). Die EMA 200 dient als Bestätigung. |
| Trendende | RSI-Divergenz: tieferes Tief mit höherem RSI, der erste RSI-Punkt unter 30, der zweite zwischen 30 und 70 („Geheimrezept“). Einstieg auf der ersten bullischen Kerze, Stop am Tief, Ziel 1,5 × Risiko; an Hochs spiegelbildlich. |
| Tagesplan | Die erste 5-Minuten-Kerze außerhalb der Spanne der Tokio-Session gibt die Tagesrichtung vor und wird gehandelt (Stop halbe Spanne, Ziel 2 × Risiko). Danach Fibonacci-Scalps in dieser Richtung, bis eine RSI-Divergenz gegen sie das Trendende anzeigt; diese ist der letzte Trade. Zwei bis vier Scalps je Trend, 1 % Risiko je Trade. |

Was das Video offenlässt, legt `scalping.py` so fest:
- Wendepunkte: ein Zickzack, der bei 3 × ATR(14) gegen das laufende Extrem dreht (im Video von Hand
  gezeichnet).
- Tokio-Session 19:00–04:00 New York (Variante 20:00–03:00), Ausbrüche bis 12:00 New York.
- RSI(14) und EMA(200).
- Tagesplan: höchstens vier Trades am Tag (Ausbruch, bis zu drei Fibonacci-Scalps auf 1 Minute, die
  Divergenz). Der Tokio-Trade läuft wie im Video neben den Scalps weiter, die Scalps und die Divergenz
  folgen nacheinander.
- Keine Einstiege von 16:30 bis 18:00 New York; alle Positionen schließen um 17:00 New York.
- Ausgeführt wird auf Minutenkerzen. Berührt eine Kerze Stop und Ziel, zählt der Stop.

`check_scalping.py` prüft die Regeln an 16 konstruierten Kursverläufen. `fetch_fx_m1.py` lädt die
Minutendaten (Oanda, EURUSD und GBPUSD, 2005 bis Mai 2020, Mittelkurse) aus derselben Quelle wie
`fetch_indices.py`. `scalping_test.py` testet 13 vorab festgelegte Varianten:
- Gewichtung wie im Video: 1 % Risiko je Trade, Ergebnisse in R (Vielfachen des Risikos).
- Kosten je Seite 0, 0,4 bp (dein Raw-Spread-Konto: Kommission plus etwa ein halber Raw Spread) oder 0,75 bp.
- In-Sample 2005–2014, Out-of-Sample 2015 bis Mai 2020.

Out-of-Sample, Mittel aus EURUSD und GBPUSD; Sharpe, Rendite und Drawdown für beide Märkte zusammen,
nach Kosten mit 0,4 bp je Seite:

| Variante | Trades/Jahr | Treffer | Stop (Pips) | R je Trade vor / nach Kosten | Sharpe vor / nach Kosten | Rendite p. a. (max. DD) |
|---|---|---|---|---|---|---|
| Tokio-Ausbruch, Spanne 19–04 NY (5m), gewählt | 244 | 39 % | 20,2 | +0,036 / −0,018 | +0,58 / −0,29 | −5,4 % (−39 %) |
| Tokio-Ausbruch, Spanne 20–03 NY (5m) | 252 | 36 % | 15,5 | +0,036 / −0,034 | +0,56 / −0,53 | −9,5 % (−58 %) |
| Tagesplan des Videos (Tokio + Fibonacci + RSI) | 768 | 38 % | 8,7 | −0,003 / −0,189 | −0,07 / −4,88 | −77,6 % (−100 %) |
| RSI-Divergenz mit 70/30-Regel (5m) | 243 | 41 % | 5,8 | +0,014 / −0,253 | +0,25 / −4,16 | −46,6 % (−97 %) |
| RSI-Divergenz mit 70/30-Regel (1m) | 1.169 | 42 % | 2,2 | +0,041 / −0,681 | +1,61 / −17,95 | −100 % |
| Box-Ausbruch (5m) | 488 | 39 % | 8,9 | −0,040 / −0,172 | −1,11 / −4,67 | −57,5 % (−99 %) |
| Box-Ausbruch (1m) | 2.642 | 38 % | 4,1 | −0,043 / −0,340 | −2,52 / −17,97 | −100 % |
| Fibonacci-Rücksetzer mit EMA 200 (5m) | 725 | 39 % | 10,8 | −0,011 / −0,129 | −0,33 / −3,80 | −61,9 % (−99 %) |
| Fibonacci-Rücksetzer mit EMA 200 (1m) | 3.484 | 37 % | 4,6 | −0,020 / −0,302 | −1,25 / −17,84 | −100 % |

Ohne die 70/30-Regel, ohne EMA-Filter oder mit der zweiten Tokio-Spanne sind die Ergebnisse ähnlich oder
schlechter (`results/scalping.json`).

- Nach Kosten ist keine der 13 Varianten Out-of-Sample positiv, auch nicht mit 0,4 bp je Seite. Gewählt
  wurde der Tokio-Ausbruch, Out-of-Sample −0,29 (EURUSD −0,56, GBPUSD +0,12).
- Entscheidend sind die Kosten im Verhältnis zum Stop. Ein Round Trip kostet auf deinem Konto etwa 1 Pip.
  Bei Stops von 2–5 Pips auf 1 Minute sind das im Mittel 0,3–0,7 R je Trade, beim Tokio-Ausbruch mit
  20 Pips nur rund 0,05 R.
- Vor Kosten gibt es kleine Vorteile beim Tokio-Ausbruch (+0,04 R) und bei der RSI-Divergenz auf 1 Minute
  (+0,04 R, Sharpe +1,6). Das sind beim Tokio-Ausbruch etwa 0,7 Pips je Trade, bei der Divergenz mit
  2 Pips Stop weniger als 0,1 Pips; der Round Trip kostet rund 1 Pip.
- Fibonacci-Rücksetzer und Box-Ausbrüche verlieren schon vor Kosten. Bei 1:1,6 bräuchte der
  Fibonacci-Einstieg eine Trefferquote von 38,2 %. Er erreicht 37 % (1 Minute) und 39 % (5 Minuten),
  wobei auch kleine Gewinne beim Schließen zum Tagesende als Treffer zählen.
- Mit 1 % Risiko je Trade ist das Konto bei jeder 1-Minuten-Variante im ersten Jahr aufgebraucht. Bei
  2 Pips Stop verlangt 1 % Risiko außerdem etwa das 50-Fache des Kontos als Positionsgröße.
- Die hohe Rangkorrelation zwischen In-Sample und Out-of-Sample (0,96) kommt aus der Zahl der Trades und
  damit der Kostenlast, nicht aus einem Vorteil.
- Nicht nachgebildet sind Ermessensteile des Videos (Ablehnungskerzen, „starke“ Kerzen, Linien von Hand).
  Getestet wurde mit Oanda-Mittelkursen plus festen Kosten bis Mai 2020; mit dem MT5-Export lässt sich
  derselbe Test auf IC-Markets-Daten mit echten Spreads bis 2026 wiederholen.

## Fazit

- Als eigenständiges Handelssystem (Long und Short) zeigt der Indikator auf keinem der
  getesteten Märkte einen positiven Vorteil nach Kosten.
- Der KNN-Filter halbiert die Zahl der Trades, verbessert die Ergebnisse gegenüber einem
  einfachen SuperTrend aber nicht messbar.
- Brauchbar ist er höchstens als Long-only-Trendfilter auf H4/D1 für Märkte mit Aufwärtsdrift
  (Aktienindex, Gold): Der Drawdown halbiert sich ungefähr, das Sharpe-Verhältnis bleibt
  etwa auf Buy-&-Hold-Niveau, die Rendite ist niedriger. Ein einfacher SuperTrend leistet als
  Filter ähnliches.
- Dasselbe gilt für die aus Smart Money Concepts abgeleiteten Regeln: Die Marktstruktur taugt als
  Long-only-Trendfilter, Einstiege an Order Blocks verlieren Out-of-Sample.
- DR/IDR: Die bekannte 80-%-Regel trifft zu, folgt in der regulären Session aber aus der Geometrie
  der Range und gilt dort auch für zufällig umsortierte Kurse. Als Intraday-System verliert sie nach
  Kosten. Nur die Abend-Range zeigt vor Kosten einen kleinen, beständigen Vorteil; er reicht nur bei
  sehr niedrigen Kosten und hängt Out-of-Sample stark an 2020.
- 1-Minuten-Scalping (Video): Bei Stops von 2–5 Pips kosten Spread und Kommission 0,3–0,7 R je Trade.
  Alle Varianten verlieren nach Kosten, auf 1 Minute ist das Konto bei 1 % Risiko je Trade im ersten
  Jahr aufgebraucht. Am nächsten an der Gewinnschwelle liegt der Tokio-Ausbruch mit Stops um 20 Pips.

## Einschränkungen

- Vier Märkte, Daten bis 2018/2019/2021: Neuere Jahre konnten nicht getestet werden.
- Out-of-Sample-Zeiträume von 4–6 Jahren: Sharpe-Unterschiede von 0,1–0,3 sind statistisch nicht signifikant.
- Keine Swaps und Dividenden. Mit Dividenden läge Buy & Hold bei SPY etwa 2 %/Jahr höher, die
  Long-only-Regel anteilig zur Marktzeit (ca. 77 %) ebenfalls.
- Oanda-Retail-Spreads. Bei ECN-Konten mit Kommission sind die Kosten etwas niedriger, das ändert
  das Gesamtbild auf H1 aber nicht (die Bruttorenditen sind schon nahe null).

## Eigene Daten: Export aus MetaTrader 5

`mt5/HistoryExport.mq5` ist ein MQL5-Skript, das auf dem eigenen Rechner im MetaTrader-5-Terminal läuft.
Es exportiert für die gewählten Symbole M1-Kerzen (mit Spread), Ticks (Bid/Ask, bei Börsensymbolen auch
Last und Volumen) und die Symbolspezifikationen (Kontraktgröße, Tickwert, Swaps, Handelszeiten) als CSV.
Kontonummer, Kontostand und Positionen werden nicht exportiert.

1. In MetaTrader *Datei > Dateiordner öffnen*, die Datei nach `MQL5\Scripts` kopieren, in MetaEditor
   öffnen und kompilieren (F7).
2. *Extras > Optionen > Charts > Max. Bars im Chart* auf *Unlimited* stellen und MetaTrader neu starten,
   sonst begrenzt das Terminal die M1-Historie.
3. Das Skript aus dem Navigator auf einen beliebigen Chart ziehen und die Eingaben setzen: Symbolliste
   (oder alle Symbole der Marktübersicht bzw. des Servers), Zeitraum, Ticks und/oder M1.
4. Fortschritt steht oben links im Chart, Details im Reiter *Experten*. Ein abgebrochener Lauf kann neu
   gestartet werden: Fertige Monate (Ticks) und Jahre (M1) werden übersprungen.

Ausgabe in `Common\Files\HistoryExport\<Server>\` (Pfad steht am Ende im Protokoll):

| Datei | Inhalt |
|---|---|
| `export_info.txt` | Broker, Server, Abstand der Serverzeit zu UTC beim Export, Zeitraum |
| `symbols.csv` | Spezifikationen und Handelszeiten aller exportierten Symbole (Trennzeichen `;`) |
| `<Symbol>/<Symbol>_M1_<Jahr>.csv` | `time,open,high,low,close,tick_volume,spread,real_volume` (Bid, Spread in Punkten) |
| `<Symbol>/ticks/<Symbol>_ticks_<Jahr-Monat>.csv` | `time_msc,bid,ask,last,volume_real,flags` |

Alle Zeiten sind Serverzeit (bei vielen Brokern UTC+2, im US-Sommer UTC+3). Ticks sind groß: ein
FX-Paar erzeugt je nach Broker einige Millionen Ticks pro Monat, als CSV etwa 100–500 MB, gezippt
rund ein Fünftel davon. M1-Kerzen kosten etwa 20 MB pro Symbol und Jahr.

Version 1.01 lädt die M1-Historie vor dem Export vom Server nach. Version 1.00 hatte Monate ohne
lokal geladene Historie als „keine Daten“ gewertet und deshalb leere Dateien erzeugt. Die Fehlersuche
dokumentiert `mt5/export_report.md`.

### Import

`python3 -I mt5_data.py data/mt5_export/<Server>` (den Server-Ordner des Exports nach `data/mt5_export/`
kopieren) rechnet die Serverzeit in UTC um und schreibt je Symbol `data/mt5/<Symbol>_H1.csv` im Format
von `fetch_data.py` sowie `data/mt5/<Symbol>_M5.csv` für `dridr.py` (`dridr.load_mt5("US500")`). Als
Ask gilt Bid plus der kleinste Spread der Minute.

Die Umrechnung nimmt an, dass der Server auf New Yorker Zeit + 7 Stunden läuft (UTC+2, im US-Sommer
UTC+3), wie bei IC Markets und vielen anderen MT5-Brokern. `mt5_data.py` prüft das an den Daten:
- Die Woche muss Sonntag gegen 17:00–18:00 New York beginnen.
- Bei US-Index-CFDs muss die Zahl der Kursänderungen um 09:30 New York stärker steigen als eine Stunde
  früher oder später.

### Probe: US500 bei IC Markets, 14.–18. September 2026

- **Umfang:** 6.884 M1-Kerzen und 380.009 Ticks, ohne Lücken, Duplikate oder Bid über Ask.
- **M1 aus Ticks:** Die M1-Kerzen lassen sich aus den Ticks exakt nachbauen (OHLC und Spread in jeder Minute).
- **Serverzeit:** UTC+3. Die Woche beginnt Sonntag 18:00 New York. Die Kursänderungen je Minute steigen um
  08:30 / 09:30 / 10:30 New York auf das 1,2- / 2,0- / 0,9-Fache, der Sprung liegt also auf der Kassaeröffnung.
- **Spread:** 0,30 Punkte von 09:30 bis 16:00 New York, sonst 0,50 Punkte. Beim Indexstand von rund 7.600
  sind das 0,2 bzw. 0,33 bp je Seite, deutlich weniger als die 1 bp je Seite in Ergebnis 7.
  - Dieser Spread lässt sich nicht einfach auf die Oanda-Daten 2005–2020 übertragen: Bei festen Punkten
    wiegt er bei niedrigeren Indexständen (1.200–3.000) in Basispunkten das 2,5- bis 6-Fache.
  - Die faire Prüfung ist ein Test auf den Daten des Brokers selbst, mit dem vollen M1-Export.

### Kosten des Kontos (IC Markets Raw Spread, Konto in EUR)

Nach Angabe des Nutzers fallen an:
- FX und Metalle: 3,25 EUR Kommission je Lot und Seite, also 6,50 EUR je Round Trip, dazu der Raw Spread.
- Index-CFDs: keine Kommission, nur der Spread.

Die Backtests auf den Broker-Daten nehmen den Spread aus den M1-Daten und rechnen die Kommission je Kerze in
einen Anteil des Handelsvolumens um: 3,25 EUR geteilt durch den Euro-Wert eines Lots.

| Markt | Kommission je Seite | zum Vergleich: Oanda-Spread in Ergebnis 1–4 (Round Trip, Median) |
|---|---|---|
| EURUSD (1 Lot = 100.000 EUR) | 0,33 bp | 1,02 bp (1,3 Pips) |
| NZDUSD (1 Lot = 100.000 NZD, bei NZDUSD 0,73 und EURUSD 1,31 ≈ 56.000 EUR) | 0,58 bp | 3,19 bp (2,5 Pips) |
| XAUUSD (1 Lot = 100 Unzen, bei 1.230 USD ≈ 94.000 EUR) | 0,35 bp, bei höherem Goldpreis weniger | 2,83 bp (0,37 USD) |
| US500 | keine | Ergebnis 7 rechnete mit 1 bp je Seite |

Für EURUSD ist die Kommission allein (0,65 bp je Round Trip) schon zwei Drittel des Oanda-Spreads; wie viel
das Konto insgesamt spart, hängt vom Raw Spread ab, den erst der Export zeigt.
