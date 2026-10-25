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

## Fazit

- Als eigenständiges Handelssystem (Long und Short) zeigt der Indikator auf keinem der
  getesteten Märkte einen positiven Vorteil nach Kosten.
- Der KNN-Filter halbiert die Zahl der Trades, verbessert die Ergebnisse gegenüber einem
  einfachen SuperTrend aber nicht messbar.
- Brauchbar ist er höchstens als Long-only-Trendfilter auf H4/D1 für Märkte mit Aufwärtsdrift
  (Aktienindex, Gold): Der Drawdown halbiert sich ungefähr, das Sharpe-Verhältnis bleibt
  etwa auf Buy-&-Hold-Niveau, die Rendite ist niedriger. Ein einfacher SuperTrend leistet als
  Filter ähnliches.

## Einschränkungen

- Vier Märkte, Daten bis 2018/2019/2021: Neuere Jahre konnten nicht getestet werden.
- Out-of-Sample-Zeiträume von 4–6 Jahren: Sharpe-Unterschiede von 0,1–0,3 sind statistisch nicht signifikant.
- Keine Swaps und Dividenden. Mit Dividenden läge Buy & Hold bei SPY etwa 2 %/Jahr höher, die
  Long-only-Regel anteilig zur Marktzeit (ca. 77 %) ebenfalls.
- Oanda-Retail-Spreads. Bei ECN-Konten mit Kommission sind die Kosten etwas niedriger, das ändert
  das Gesamtbild auf H1 aber nicht (die Bruttorenditen sind schon nahe null).
