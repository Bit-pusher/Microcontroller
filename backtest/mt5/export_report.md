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
+   int      fails     = 0;
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
+      if(bars > last_bars)
+        { last_bars = bars; fails = 0; }
+      else if(++fails >= 300)
+         break;                                    // nothing older arrives from the server
+      Comment(...);
+      CopyTime(sym, PERIOD_M1, bars, 1000, times);  // bars beyond the oldest one: starts the download
+      if(fails > 0)
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

## Probelauf

Ausstehend. Eingaben: Symbolliste `US500` (keine lokale Historie, prüft also das Nachladen; dazu die
Eröffnung des US-Kassamarkts), Von 2026.09.13 00:00, Bis 2026.09.20 00:00 (Serverzeit), alle Ticks, M1,
Spezifikationen, Zielordner `HistoryExport_Probe`, Common\Files.
