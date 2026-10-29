# Notizen der Cloud-Sitzung an den lokalen Agenten

Neueste Einträge oben. Der lokale Agent liest diese Datei nach `git pull`.

## 2026-10-29: Bitte den neuen EA kompilieren und kurz testen

Neu im Repo: `ScalpingVideoEA/` (EA `ScalpingVideoEA.mq5` und Regelkern `ScalpingCore.mqh`). In der Cloud gibt
es keinen MetaEditor; den Kern habe ich als C++ geprüft, die MT5-Aufrufe des EA aber noch nie kompiliert.
Erst nach dem laufenden Export, und nur wenn der Nutzer zustimmt:

1. Den Ordner `ScalpingVideoEA` nach `MQL5/Experts/` kopieren und `ScalpingVideoEA.mq5` kompilieren, z. B.
   `metaeditor64.exe /compile:"<Pfad>\ScalpingVideoEA.mq5" /log`. Fehler und Warnungen mit Zeilennummer in
   `backtest/mt5/export_report.md` eintragen.
2. Kompiliert er: Strategietester, EURUSD, Modell „Jeder Tick basierend auf realen Ticks“, Zeitraum
   2026-09-01 bis 2026-09-30, Einzahlung 10.000 EUR, Standardeinstellungen (Tagesplan). Dann dasselbe mit
   „Strategie: Tokio-Ausbruch“. Je Lauf berichten: Zahl der Trades, Nettogewinn, maximaler Drawdown, ob die
   Deals eine Kommission enthalten, und die Zeilen „… Trades, Trefferquote …“ aus dem Journal des Testers.
3. Nur im Tester laufen lassen, nicht auf einem Chart des Handelskontos. Keine Kontonummer, kein Kontostand
   in den Bericht.

## 2026-10-27: Probelauf geprüft, nächste Schritte

### Unabhängige Prüfung der Probe (US500, 2026-09-14 bis 09-18)

Deine Befunde bestätigt. Zusätzlich:

- Die M1-Kerzen lassen sich exakt aus den Ticks nachbauen: Open, High, Low und Close (Bid) sowie der
  Spread (kleinster Tick-Spread der Minute) stimmen in allen 6884 Minuten überein. `tick_volume` entspricht
  in 6877 Minuten der Zahl der Ticks.
- Serverzeit = New York + 7 h, in der Probewoche also UTC+3. `mt5_data.py` (neu im Repo) rechnet damit nach
  UTC um und prüft die Regel an den Daten: Wochenbeginn Sonntag 18:00 New York; Anstieg der Ticks je Minute
  bei 08:30 / 09:30 / 10:30 New York ×1,2 / ×2,0 / ×0,9, der Sprung liegt also auf der Kassaeröffnung.
- Spread US500: 0,30 Punkte von 09:30 bis 16:00 New York, sonst 0,50 Punkte (0,2 bzw. 0,33 bp je Seite).
- `dridr.py` liest die Probe über `mt5_data.py` ein; alle drei Sessions (RDR, ADR, ODR) sind vollständig.

### Bitte ändern (Version 1.02)

1. **Teilzeiträume eindeutig benennen.** Deckt eine Datei nur einen Teil ihres Monats (Ticks) oder Jahres (M1)
   ab, heißt sie `<Symbol>_ticks_<JJJJ-MM>_partial.csv` bzw. `<Symbol>_M1_<JJJJ>_partial.csv`. „Fertige Dateien
   überspringen“ gilt nur für Dateien ohne `_partial`. Wird ein Zeitraum vollständig geschrieben, löscht das
   Skript die `_partial`-Datei desselben Zeitraums. (`mt5_data.py` nimmt bei doppelten Minuten die vollständige
   Datei.)
2. **Beim Start auf Verbindung und Kurse warten**, höchstens 60 s: `TERMINAL_CONNECTED`, für jedes Symbol nach
   `SymbolSelect` ein `SymbolInfoTick` mit Bid > 0 und `SYMBOL_TRADE_TICK_VALUE` > 0. Erst danach
   `export_info.txt` und `symbols.csv` schreiben. Bei Zeitüberschreitung eine Warnung ins Protokoll, dann
   trotzdem weiter.
3. Kompilieren, kurz testen (ein Symbol, ein Teilmonat und danach derselbe ganze Monat in denselben Ordner:
   die `_partial`-Datei muss verschwinden), committen. Pushen nach OK des Nutzers.

### Voller Export, danach

**Lauf A, zum Hochladen: M1 mit Spread**

- Symbole: `US500, USTEC, US30, US2000, EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD, USDCAD, USDCHF, XAUUSD, XAGUSD,
  BTCUSD, ETHUSD`. Die Namen bitte am Server prüfen (Meldung „gibt es auf diesem Server nicht“), Abweichungen
  hier notieren.
- Von `2015.01.01 00:00` bis `2026.10.01 00:00`; das Skript beginnt beim ältesten Balken des Servers.
- Ticks aus, Ordner `HistoryExport_M1`.

**Lauf B: Ticks**

- Symbole: `US500, USTEC, US2000`, von `2025.10.01 00:00` bis `2026.10.01 00:00`.
- M1 aus, Ordner `HistoryExport_Ticks`.
- Für die Backtests reicht M1 (Spread je Minute). Die Ticks dienen als Referenz für Spreads und Ausführung.

**Hochladen**

- Nur nach OK des Nutzers.
- Je Symbol ein ZIP mit allen M1-Jahren, je Symbol und Monat ein ZIP mit den Ticks, jede Datei unter 100 MB.
- Ziel ist ein eigenes privates Repo des Nutzers, z. B. `Bit-pusher/market-data`, auf das die Claude GitHub
  App Zugriff hat. Kein Git LFS. Den Repo-Namen hier eintragen.
- `export_info.txt` und `symbols.csv` beider Läufe mit hochladen.

### Frage an den Nutzer (bitte weitergeben)

Kontotyp bei IC Markets: Raw Spread oder Standard? Und welche Kommission fällt je Lot und Seite für FX und
Metalle an, welche für Index-CFDs? Das steht in der Kontraktspezifikation oder bei einem früheren Trade.
Davon hängen die Kosten in den FX-Tests ab.

## 2026-10-26

- Auftrag: siehe `local_agent_prompt.md`. Bitte zuerst nur Belege sammeln (Experten-Protokoll, Journal,
  `compile.log`) und in `export_report.md` berichten, bevor du das Skript änderst.
- An `HistoryExport.mq5` arbeitet bis auf Weiteres nur der lokale Agent; die Cloud-Sitzung ändert die
  Datei nicht, damit es keine Konflikte gibt.
