# Bericht des lokalen Agenten: `HistoryExport.mq5`

Neueste Einträge oben. Antworten der Cloud-Sitzung bitte in `cloud_notes.md`.

## 2026-10-27: Belege und Diagnose

### Umgebung

- Ein Terminal: MetaTrader 5 Build 6230, Server `ICMarketsSC-MT5-2` (Raw Trading Ltd).
- Serverzeit beim Export UTC+3 (`export_info.txt`: `server_utc_offset_hours_now=+3.00`).
- Das Skript liegt beim Nutzer in `MQL5\Experts` statt in `MQL5\Scripts`, läuft aber als Skript
  (Journal: `script HistoryExport (EURUSD,H1) loaded successfully`). Inhaltlich gleich mit dem Stand im
  Repo vor dieser Änderung.

### Kompilieren

```
metaeditor64.exe /compile:"<Datenordner>\MQL5\Experts\HistoryExport.mq5" /log:"compile.log"
Result: 0 errors, 0 warnings, 1037 ms elapsed, cpu='X64 Regular'
```

Kein Kompilierproblem.

### Lauf vom 2026-10-26, 11:53 bis 12:00

Eingaben laut Protokoll und `symbols.csv`: EURUSD, XAUUSD, US500, 2015.01.01 bis jetzt, alle Ticks,
M1 und Spezifikationen.

Experten-Protokoll `MQL5\Logs\20261026.log` (Auszug, Muster wiederholt sich für jeden Monat):

```
11:55:05.680  HistoryExport: 3 Symbole, 2015.01.01 bis 2026.10.26 (Serverzeit)
11:55:05.733  EURUSD M1 2015.01.01: Versuch 1, Fehler 4401
11:55:06.745  EURUSD M1 2015.01.01: Versuch 2, Fehler 4401
11:55:08.745  EURUSD M1 2015.01.01: Versuch 3, Fehler 4401
11:55:11.755  EURUSD M1 2015.01.01: Versuch 4, Fehler 4401
11:55:15.746  EURUSD M1 2015.01.01: Versuch 5, Fehler 4401
11:55:20.769  EURUSD M1 2015.01.01: Versuch 6, Fehler 4401
11:55:26.769  EURUSD M1 2015.02.01: Versuch 1, Fehler 4401
...
11:59:12.306  EURUSD M1 2015.12.01: Versuch 6, Fehler 4401
11:59:18.312  EURUSD M1 2015: 0 Kerzen
11:59:18.313  EURUSD M1 2016.01.01: Versuch 1, Fehler 4401
...
12:00:31.503  EURUSD M1 2016.04.01: Versuch 5, Fehler 4401
12:00:32.716  HistoryExport abgebrochen: 0 Ticks, 0 M1-Kerzen, 0 Fehler. Ordner: ...\Common\Files\HistoryExport\ICMarketsSC-MT5-2
```

Journal `Logs\20261026.log`: keine Fehler. Skript geladen 11:53:19, entfernt 12:00:32, danach hat der Nutzer
das Terminal geschlossen (12:00:34, `exit with code 0`).

Ausgabeordner `Common\Files\HistoryExport\ICMarketsSC-MT5-2\`: `export_info.txt` (428 B), `symbols.csv`
(1180 B, alle drei Symbole), leerer Ordner `EURUSD\`, keine `.part`-Dateien.

„Max. Bars im Chart“ (`config\common.ini`): `MaxBars=100000000`, also praktisch unbegrenzt.

Lokal geladene Historie (`bases\ICMarketsSC-MT5-2\history\<Symbol>\<Jahr>.hcc`):

| Symbol | M1-Historie im Terminal | Tick-Monatsdateien |
|---|---|---|
| EURUSD | 2023–2026 | keine |
| XAUUSD | 2017–2026 | 2025-01 bis 2026-10 |
| US500 | keine | keine |

### Diagnose

- **Vermutung 1 bestätigt: Historie nicht vom Server geladen.** `CopyRates` nach Datum liefert für Zeiträume
  vor dem ältesten lokalen M1-Balken −1 mit 4401 und stößt dabei keinen Download älterer Daten an. Der Server
  hat die Daten: `SERIES_SERVER_FIRSTDATE` liegt für EURUSD auf oder vor 2015-01-01, sonst hätte der Export
  später begonnen. `CopyRatesRetry` wertet 4401 nach sechs Versuchen (rund 21 s je Monat) als „keine Daten“:
  2015 endet mit „0 Kerzen“, die `.part`-Datei wird gelöscht und der Fehlerzähler bleibt 0. Bei EURUSD
  hätte das Skript für 2015 bis 2022 etwa 96 × 21 s ≈ 34 min ohne Ergebnis verbracht. Der Nutzer hat nach
  7 min bei 2016-04 abgebrochen.
- **4404 verworfen:** `MaxBars` ist 100 Mio., im Protokoll steht kein 4404.
- **Symbolname verworfen:** Alle drei Symbole stehen in `symbols.csv`, keine Meldung „gibt es auf diesem
  Server nicht“.
- **Dateifehler verworfen:** Kein 50xx. `export_info.txt` und `symbols.csv` wurden geschrieben, der Ordner
  wurde angelegt.
- **Ticks:** Der Lauf kam nicht bis zu den Ticks, dazu gibt es noch keine Belege.

### Geplante Änderung

- Vor dem M1-Export die Historie bis „Von“ nachladen, nach dem Muster „CheckLoadHistory“ der
  MQL5-Dokumentation: auf `SERIES_SYNCHRONIZED` warten, dann Balken jenseits des ältesten per Position
  anfordern (`CopyTime(sym, PERIOD_M1, Bars(...), ...)`), bis `SERIES_FIRSTDATE` ≤ „Von“ ist oder der Server
  nichts Älteres mehr liefert.
- Der M1-Export beginnt beim ältesten Balken, der danach im Terminal liegt. Reicht er nicht bis „Von“, steht
  das im Protokoll.
- 4401 innerhalb der geladenen Historie bleibt eine Lücke (0 Kerzen).
- Ticks vorerst unverändert. Prüfung im Probelauf.

### Änderung (Version 1.01)

Umgesetzt wie geplant, Commit „Load the M1 history from the server before exporting it“. Neue Funktion
`LoadM1History`. In `OnStart` beginnt der M1-Export beim danach ältesten Balken im Terminal. Fehlt die
M1-Historie ganz oder reicht sie nicht bis „Von“, steht das im Protokoll und zählt als Fehler, damit ein
neuer Lauf es nachholt. Kompiliert mit `0 errors, 0 warnings`, beim Nutzer in `MQL5\Experts` installiert.

```diff
-#property version     "1.00"
+#property version     "1.01"
@@ nach FirstBarDate()
+datetime LoadM1History(const string sym, const datetime start, const string progress)
+  {
+   long     maxbars   = TerminalInfoInteger(TERMINAL_MAXBARS);
+   long     first     = 0;
+   int      last_bars = 0;
+   uint     last_gain = GetTickCount();
+   datetime times[];
+   while(!IsStopped())
+     {
+      for(int k = 0; k < 200 && !SeriesInfoInteger(sym, PERIOD_M1, SERIES_SYNCHRONIZED) && !IsStopped(); k++)
+         Sleep(50);                                // the series is still being built
+      int bars = Bars(sym, PERIOD_M1);
+      if(!SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE, first))
+         first = 0;
+      if(bars > 0 && first > 0 && (datetime)first <= start)
+         break;
+      if(bars >= maxbars)
+        { Print("Hinweis: ... Max. Bars im Chart ..."); break; }
+      bool grew = (bars > last_bars);
+      if(grew)
+        { last_bars = bars; last_gain = GetTickCount(); }
+      else if(GetTickCount() - last_gain > 60000)
+         break;                                    // nothing older arrived from the server for a minute
+      Comment(...);
+      CopyTime(sym, PERIOD_M1, bars, 1000, times);  // bars beyond the oldest one: starts the download
+      if(!grew)
+         Sleep(100);
+     }
+   if(!SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE, first))
+      first = 0;
+   return (datetime)first;
+  }
@@ OnStart(), M1-Teil
          datetime first = FirstBarDate(sym);
-         int y_from = YearOf((first > InpFrom) ? first : InpFrom);
-         ... ExportM1Year(sym, y, first, digits);
+         datetime start = (first > InpFrom) ? first : InpFrom;
+         datetime loaded = LoadM1History(sym, start, progress);
+         if(loaded == 0)
+            -> "%s M1: keine Historie im Terminal, übersprungen", g_failed++
+         else
+           {
+            if(loaded > start)
+               -> "%s M1: Historie nur ab %s geladen (angefordert ab %s), beim nächsten Lauf erneut versucht", g_failed++
+            int y_from = YearOf((loaded > InpFrom) ? loaded : InpFrom);
+            ... ExportM1Year(sym, y, loaded, digits);
+           }
```

### Nebenbefund, nicht geändert

Eine Datei, die nur einen Teil eines Monats oder Jahres abdeckt (`partial`), wird unter ihrem endgültigen
Namen abgelegt. Ein späterer Lauf mit größerem Zeitraum hält sie dann für fertig und überspringt sie
(`InpSkipDone`). Der Probelauf schreibt deshalb in einen eigenen Ordner `HistoryExport_Probe`. Läufe mit
unterschiedlichen Zeiträumen sollten nicht in denselben Ordner schreiben.

Nachtrag: Im ersten Entwurf gab das Nachladen erst nach 300 Runden ohne neue Balken auf. Jede Runde kann
bis zu 10 s auf `SERIES_SYNCHRONIZED` warten, im schlimmsten Fall also rund 50 min. Jetzt bricht es nach
60 s ohne neue Balken ab (Commit „Give up loading M1 history after a minute without new bars“).

## Probelauf (2026-10-27, 14:10 Ortszeit)

Der Nutzer war nicht am PC. Deshalb lief das Skript über eine Startkonfiguration (`[StartUp]
Script=HistoryExport_Probe`, Chart US500,H1). Gestartet wurde eine Kopie von Version 1.01 mit
voreingestellten Probewerten, die nur in `MQL5\Scripts` liegt und nicht im Repo. Eingaben: US500,
2026.09.13 00:00 bis 2026.09.20 00:00 (Serverzeit), alle Ticks, M1, Spezifikationen, Ordner
`HistoryExport_Probe`.

```
14:10:14.435  HistoryExport: 1 Symbole, 2026.09.13 bis 2026.09.20 (Serverzeit)
14:10:15.896  US500 M1 2026: 6884 Kerzen
14:10:25.843  US500 Ticks 2026-09: 380009
14:10:25.845  HistoryExport fertig: 380009 Ticks, 6884 M1-Kerzen, 0 Fehler. Ordner: ...\Common\Files\HistoryExport_Probe\ICMarketsSC-MT5-2
```

Vor dem Lauf lag für US500 keine Historie im Terminal. Das Nachladen der M1-Daten dauerte 1,5 s.

### Dateien

| Datei | Zeilen ohne Kopf | Größe | Zeitraum (Serverzeit) |
|---|---|---|---|
| `export_info.txt` | – | 428 B | – |
| `symbols.csv` | 1 | 585 B | – |
| `US500/US500_M1_2026.csv` | 6 884 | 358 621 B | 2026-09-14 01:00 bis 2026-09-18 23:54 |
| `US500/ticks/US500_ticks_2026-09.csv` | 380 009 | 16 340 428 B | 2026-09-14 01:00:15.006 bis 2026-09-18 23:54:52.630 |

### Prüfungen

- Die Kopfzeilen entsprechen der Vorgabe.
- **M1:** Zeitstempel streng aufsteigend, keine Duplikate, alle auf voller Minute, OHLC konsistent.
  Spread (Minimum je Kerze) 30 bis 50 Punkte, Median 50 Punkte = 0,50 Indexpunkte.
- **Ticks:** `time_msc` aufsteigend, kein Zeitstempel doppelt, keine doppelte Zeile, kein Bid > Ask, nie
  Bid oder Ask = 0. Spread 30 bis 100 Punkte, Median und 99. Perzentil 50. `last` und `volume_real` sind 0
  (CFD). Flags: 1158 (379 839), 1154 (161), 1028 (9).
- M1 und Ticks decken genau dieselben Minuten ab.
- Handel Montag bis Freitag jeweils 01:00 bis 23:59 Serverzeit, freitags bis 23:55, wie
  `sessions_server_time` in `symbols.csv`. Tägliche Pause 00:00 bis 01:00.

### Abstand Serverzeit zu UTC

- **Aus den Daten: UTC+3 in der Probewoche** (US-Sommerzeit).
  - Die tägliche Pause 00:00 bis 01:00 Serverzeit entspricht der CME-Pause 17:00 bis 18:00 New York
    (EDT, UTC−4), also 21:00 bis 22:00 UTC.
  - Kassamarkt: Die mittlere M1-Spanne springt um 16:30 Serverzeit auf das 2,3-Fache der 15 Minuten davor,
    die Ticks je Minute steigen von 68 auf 160. 9:30 New York = 13:30 UTC = 16:30 bei UTC+3. Um 15:30
    (×1,4) und 17:30 (×1,0) gibt es keinen vergleichbaren Sprung.
  - `export_info.txt` vom 2026-10-26 (Drag & Drop, Terminal lief schon) meldete ebenfalls +3.00.
- **`export_info.txt` dieses Laufs ist falsch:** `server_utc_offset_hours_now=+0.00`, `export_time_server`
  gleich `export_time_utc`. Ebenso steht in `symbols.csv` `tick_value=0` (gestern 0.00892857). Das Skript
  startete 27 s nach dem Terminal. `TimeTradeServer()` kannte den Serverzeitversatz offenbar noch nicht,
  und für die Umrechnung des Tickwerts fehlten noch Kurse. Bei Drag & Drop in ein laufendes Terminal tritt
  das nicht auf. Nicht geändert. Möglich wäre, dass das Skript beim Start wartet, bis das Terminal
  verbunden ist und Kurse vorliegen.

### Ablage

`HistoryExport_Probe_US500_2026-09-13.zip` (2,05 MB) im Download-Ordner des Nutzers, zum Anhängen in der
Cloud-Sitzung. Nicht auf GitHub.

### Offene Fragen an die Cloud-Sitzung

- Welche Symbole und welcher Zeitraum für den vollen Export? Laut einer älteren Symbolliste des Nutzers
  (`Common\Files\symbols_dump.csv` vom 2026-09-14) heißen die US-Indizes `US500`, `USTEC`, `US2000` und
  `US30`. Ob die Liste vom Server `ICMarketsSC-MT5-2` stammt, ist nicht geprüft.
- Soll das Skript beim Start auf Verbindung und Kurse warten, damit `export_info.txt` und `tick_value`
  auch bei einem Start mit dem Terminal stimmen?
