# Auftrag: MT5-Historie exportieren und `HistoryExport.mq5` reparieren

Du arbeitest auf meinem Windows-Rechner, auf dem MetaTrader 5 installiert ist. Eine Claude-Sitzung in
der Cloud (Name `microcontroller-c0`) hat das Exportskript geschrieben und wertet die Daten später aus.
Sie kann aber weder MetaEditor noch MetaTrader erreichen. Dein Ziel: **funktionierende Exportdateien**
und ein Bericht an die Cloud-Sitzung. Antworte mir auf Deutsch.

## Ausgangslage

- Skript: `backtest/mt5/HistoryExport.mq5` im Repo https://github.com/Bit-pusher/Microcontroller,
  Branch `claude/gallant-hypatia-484qqo`. Beschreibung: `backtest/README.md`, Abschnitt
  „Eigene Daten: Export aus MetaTrader 5“.
- Ich habe es nach `MQL5\Scripts` kopiert, kompiliert und auf einen Chart gezogen. **Es erzeugt keine
  Daten, und das Protokoll meldet Fehler.** Welche, weiß die Cloud-Sitzung noch nicht.

## Was das Skript liefern soll

Ordner `%APPDATA%\MetaQuotes\Terminal\Common\Files\HistoryExport\<Server>\`:

| Datei | Inhalt |
|---|---|
| `export_info.txt` | Broker, Server, Terminal-Build, Abstand Serverzeit zu UTC beim Export, Zeitraum |
| `symbols.csv` | Spezifikationen und Handelszeiten je Symbol, Trennzeichen `;` |
| `<Symbol>\<Symbol>_M1_<Jahr>.csv` | `time,open,high,low,close,tick_volume,spread,real_volume` (time = Sekunden seit 1970, Serverzeit) |
| `<Symbol>\ticks\<Symbol>_ticks_<Jahr-Monat>.csv` | `time_msc,bid,ask,last,volume_real,flags` (time_msc = Millisekunden seit 1970, Serverzeit) |

Dateien werden als `<Name>.part` geschrieben und erst nach Abschluss umbenannt, damit ein
abgebrochener Lauf fortgesetzt werden kann.

## Vorgehen

1. **MetaTrader finden.** Datenordner unter `%APPDATA%\MetaQuotes\Terminal\<ID>\` (die Datei
   `origin.txt` nennt den Installationsordner mit `terminal64.exe` und `metaeditor64.exe`). Gibt es
   mehrere Terminals, frag mich, welches gemeint ist.
2. **Belege sammeln, bevor du etwas änderst:**
   - Experten-Protokoll `<Datenordner>\MQL5\Logs\<JJJJMMTT>.log` (UTF-16) mit den Zeilen von
     HistoryExport, außerdem das Journal `<Datenordner>\Logs\<JJJJMMTT>.log`.
   - Kompilierlauf auf der Kommandozeile:
     `metaeditor64.exe /compile:"<Datenordner>\MQL5\Scripts\HistoryExport.mq5" /log:"<Pfad>\compile.log"`.
     Dann `compile.log` lesen (Fehler und Warnungen).
   - Was im Ausgabeordner liegt (auch `.part`-Dateien).
   - Die Einstellung „Max. Bars im Chart“ (nur lesen).
3. **Ursache bestimmen.** Schick die genauen Fehlerzeilen und deine Diagnose an die Cloud-Sitzung (siehe
   „Bericht“), bevor du größere Änderungen machst. Vermutungen der Cloud-Sitzung, die du **anhand des
   Protokolls bestätigen oder verwerfen** sollst:
   - Die Historie ist noch nicht vom Server geladen: `CopyRates`/`CopyTicksRange` liefern −1 mit 4401
     (ERR_HISTORY_NOT_FOUND) oder 4403 (ERR_HISTORY_TIMEOUT). Schwachstelle im Skript: Bei M1 wird 4401
     nach den Wiederholungen als „keine Daten“ gewertet (`CopyRatesRetry`), dann bleibt die Datei leer.
     Abhilfe wäre, die Synchronisierung abzuwarten bzw. das Nachladen anzustoßen (z. B.
     `SeriesInfoInteger(..., SERIES_SYNCHRONIZED)` und das Muster „CheckLoadHistory“ aus der
     MQL5-Dokumentation, für Ticks längere Wartezeiten).
   - 4404 (ERR_HISTORY_BARS_LIMIT): „Max. Bars im Chart“ zu klein.
   - Falscher Symbolname (Meldung „gibt es auf diesem Server nicht“) oder Dateifehler (50xx) beim
     Anlegen der Ordner oder Dateien.
4. **Reparieren.** Ändere so wenig wie nötig, kompiliere ohne Fehler und schreibe die Ursache in den
   Commit-Text.
5. **Probelauf.** Ein Symbol, z. B. EURUSD oder ein Index-CFD in der Schreibweise des Brokers, eine Woche
   aus dem letzten Monat, Ticks + M1 + Spezifikationen. Das Skript starte ich selbst per Drag & Drop.
   Sag mir die Eingabewerte; alternativ darfst du eine Voreinstellung (`.set`) vorbereiten. Das Format
   ermittelst du, indem du mich im Eingabedialog *Speichern* drücken lässt.
6. **Ausgabe prüfen:**
   - Alle Dateien vorhanden, Kopfzeilen korrekt, Zeilenzahlen und Zeitraum plausibel.
   - Zeitstempel aufsteigend und ohne Duplikate, Bid ≤ Ask, Spreads plausibel.
   - Den Abstand der Serverzeit zu UTC bestimmen: aus `export_info.txt` und aus den Daten, z. B. Beginn
     der FX-Woche am Sonntag, Eröffnung des US-Kassamarkts 9:30 New York.
7. **Notlösung**, falls das MQL5-Skript nicht schnell zu reparieren ist: ein Python-Exporter mit dem
   offiziellen Paket `MetaTrader5` (`copy_rates_range`, `copy_ticks_range`), gleiche Dateistruktur und
   gleiche Spalten, als `backtest/mt5/history_export.py`. Vor dem Installieren von Paketen fragen.
8. **Abliefern:**
   - Repo klonen bzw. aktualisieren (`git pull`) und nur Dateien unter `backtest/mt5/` ändern. An den
     übrigen Dateien arbeitet die Cloud-Sitzung.
   - Commit auf `claude/gallant-hypatia-484qqo`; pushen erst nach meinem OK.
   - Die Probedaten als ZIP in meinen Download-Ordner legen, damit ich sie in der Cloud-Sitzung anhänge.
     Daten nur nach Rückfrage auf GitHub hochladen (jede Datei unter 100 MB, kein Git LFS).

## Bericht an die Cloud-Sitzung

Wenn dir `ListAgents`/`SendMessage` die Sitzung `microcontroller-c0` anzeigen, schick ihr:
- die gefundenen Fehlerzeilen und die Ursache,
- deine Änderung (Diff),
- das Ergebnis des Probelaufs: Symbole, Zeitraum, Zeilen und Größe je Datei, Abstand der Serverzeit
  zu UTC, Ablageort der Daten.

Erreichst du sie nicht, schreib denselben Inhalt in `backtest/mt5/export_report.md` und sag mir, dass
ich ihn in die Cloud-Sitzung kopieren soll.

## Regeln

- Auf das Handelskonto nur lesend zugreifen: keine Orders, keine Änderungen am Konto.
- Kontonummer, Passwörter und Kontostand gehören in keinen Bericht und keinen Commit.
- MetaTrader nicht beenden und Terminal-Einstellungen (z. B. „Max. Bars im Chart“) nicht ändern, ohne
  mich zu fragen.
