# Docker- und IPP-Integrationstest

Diese Tests sprechen den tatsächlich laufenden `ippeveprinter`, die PrintHub-
API und den virtuellen Zebra-Drucker an. Sie sind damit mehr als Unit-Tests der
Konvertierungsfunktionen.

Der Workflow `.github/workflows/platform-integration.yml` führt denselben
Kernpfad bei jedem `main`-Push und Pull Request unter Linux mit den exakt im
Hauptrepository fixierten Submodule-Commits aus.

## Voraussetzungen

Die vier Submodule unter `components/` sind wie in der Haupt-README beschrieben
initialisiert. Docker Compose v2 ist verfügbar und Port 8631 ist frei.

## Stack bauen und starten

```powershell
docker compose up --build -d
docker compose ps
```

Alle vier Dienste müssen `healthy` sein. Das Gateway läuft im Container und ist
zusätzlich über `ipp://localhost:8631/ipp/print` auf dem Host erreichbar.

## Unit- und Konfigurationstests

```powershell
python -m unittest discover -s ipp-gateway/tests -v
docker compose config --quiet
docker compose exec ipp-gateway ipptool -t `
  ipp://127.0.0.1:8631/ipp/print `
  /usr/share/cups/ipptool/get-printer-attributes.test
```

Der letzte Befehl muss `[PASS]` liefern. Er prüft unter anderem, dass keine
doppelten IPP-Attribute existieren und dass die konfigurierte Labelgröße und
Auflösung veröffentlicht werden.

Zusätzlich wird die Erreichbarkeit aus einem zweiten Container geprüft. Damit
wird insbesondere verhindert, dass der veröffentlichte Docker-Port intern nur
auf Loopback lauscht:

```powershell
docker compose run --rm --no-deps `
  --volume ./ipp-gateway/tests:/tests:ro `
  --entrypoint python ipp-gateway `
  /tests/network_probe.py ipp-gateway 8631 localhost
```

Der Probe-Client verbindet sich über das Compose-Netz mit `ipp-gateway`, sendet
aber wie CUPS den veröffentlichten Hostnamen `localhost` im HTTP- und IPP-
Protokoll. Bei einem anderen `PRINTHUB_IPP_HOSTNAME` ist das letzte Argument
entsprechend anzupassen.

Unter Docker Desktop prüft derselbe Client zusätzlich den auf dem Host
veröffentlichten Port – also genau den Weg, den ein lokales CUPS verwendet:

```powershell
docker compose run --rm --no-deps `
  --volume ./ipp-gateway/tests:/tests:ro `
  --entrypoint python ipp-gateway `
  /tests/network_probe.py host.docker.internal 8631 localhost
```

## Chrome-Systemdialog manuell prüfen

Die Datei `fixtures/chrome-label-50x25.html` ist eine statische, skriptfreie
Ein-Seiten-Vorlage mit `@page { size: 50mm 25mm; margin: 0; }`. Sie verhindert,
dass der Browsertest von einer zufälligen Webseite oder einem nicht
reproduzierbaren Dokument abhängt.

Unter Windows 11 zuerst in einer administrativen PowerShell die lokale Queue
einrichten und danach das benutzerspezifische Windows-PrintTicket validieren:

```powershell
.\scripts\install_windows_ipp_printer.ps1
.\scripts\install_windows_ipp_printer.ps1 -CheckOnly
```

Danach die HTML-Datei in Chrome öffnen, `Strg+P` wählen und zunächst nur den
Dialog kontrollieren:

1. Ziel ist `PrintHub 50x25 Label`.
2. Papierformat ist 50 × 25 mm und die Vorschau zeigt genau eine Seite.
3. Ränder stehen auf `Keine`; Skalierung bleibt bei 100 %.
4. Der Dialog bietet keinen Farbdruck und keine Duplexausgabe an.
5. Für ein Foto `Weitere Einstellungen` beziehungsweise den Systemdialog mit
   `Strg+Umschalt+P` öffnen. `Druckqualität: Hoch` wählt Floyd-Steinberg-
   Dithering; `Entwurf` wählt die harte Schwarz-Weiß-Schwelle ohne Dithering.
   `Normal` lässt PrintHub automatisch entscheiden. Chrome zeigt keinen eigenen
   Schalter mit dem Namen `Dithering` an.

Bei `Querformat` darf der Windows-/Chrome-Druckpfad die physischen Seitenmaße
als ungefähr 25,025 x 50,049 mm statt 50 x 25 mm liefern. PrintHub erkennt
diesen eng tolerierten, exakt vertauschten Fall und dreht die Seite. Ein echtes
Fremdformat bleibt angehalten; diese Ausnahme ist kein automatisches `fit`.

Nur wenn Größe und Vorschau stimmen, genau eine Kopie senden. Der anschließend
angelegte PrintHub-Job, die Fleet-Zustellung, der Agent-Job und die physische
Kennzeichnung `CHROME IPP` werden gemeinsam im Hardware-Nachweis festgehalten.
Zeigt der Dialog A4 oder eine unbekannte Größe, nicht drucken: Mit der
Gateway-Standardrichtlinie `hold` wäre der Auftrag zwar geschützt, der
Client-Fähigkeitstest wäre dennoch fehlgeschlagen.

Bricht Windows den Auftrag vor `Create-Job` mit PrintService-Ereignis 372 und
`0x80040003` ab, zuerst das benutzerspezifische PrintTicket kontrollieren. Seine
Medienoption muss exakt 50.000 x 25.000 Mikrometer aus den aktuellen
Druckerfähigkeiten referenzieren; ein älteres 2-x-1-Zoll-Ticket mit
50.800 x 25.400 Mikrometern ist nicht kompatibel. Das Installationsskript
korrigiert das für Chrome maßgebliche Ticket des aktuellen Benutzers. Jeder
Windows-Benutzer führt es einmal im eigenen Konto aus; eine reine
Neuinstallation kann den gerundeten globalen Treiberstandard erneut erzeugen.
Im Gateway muss der verschlüsselte Verbindungsaufbau außerdem mit `Connection
now encrypted` enden.

## Echtes PDF durch die gesamte Pipeline senden

Die Testdatei ist ein gültiges einseitiges PDF mit 50 × 50 mm Seitengröße.

```powershell
docker compose cp ipp-gateway/tests/print-job.test `
  ipp-gateway:/tmp/print-job.test
docker compose cp ipp-gateway/tests/fixtures/label-50mm.pdf `
  ipp-gateway:/tmp/label-50mm.pdf
docker compose exec ipp-gateway ipptool -t `
  -f /tmp/label-50mm.pdf `
  ipp://127.0.0.1:8631/ipp/print `
  /tmp/print-job.test
```

Erwartetes Ergebnis: zwei bestandene `ipptool`-Tests. Der neueste Eintrag unter
`GET http://localhost:8001/v1/print-jobs` hat `source_kind: "document"` und genau
einen Eintrag in `downstream_jobs`. Direkt nach der Annahme darf der Status noch
`queued` sein; nach der Übertragung an den virtuellen Zebra müssen der logische
Status, `downstream_job_state` und `downstream_jobs[0].state` den Wert
`transport_accepted` tragen. `bytes_sent` ist dann größer als null. Das ist die
ehrliche Transportbestätigung; eine physische Ausgabe kann RAW TCP allein nicht
bestätigen.

## A4 auf einem 50 × 50-mm-Label prüfen

```powershell
docker compose cp ipp-gateway/tests/fixtures/a4.pdf `
  ipp-gateway:/tmp/a4.pdf
docker compose exec ipp-gateway ipptool -t `
  -f /tmp/a4.pdf `
  ipp://127.0.0.1:8631/ipp/print `
  /tmp/print-job.test
Invoke-RestMethod http://localhost:8001/v1/print-jobs | `
  Select-Object -First 1 id,status,bytes_sent,warning
```

Der PrintHub-Job muss `held` sein, `bytes_sent` muss leer bleiben und die
Warnung muss 210 × 297 mm sowie 50 × 50 mm nennen. Anschließend kann genau
dieser Job bewusst freigegeben werden:

```powershell
$jobId = (Invoke-RestMethod http://localhost:8001/v1/print-jobs)[0].id
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8001/v1/print-jobs/$jobId/release" `
  -ContentType application/json `
  -Body '{"scaling":"fit"}'
```

Die direkte Freigabeantwort ist zunächst `queued`. Nach der Übertragung müssen
der logische Status und alle Downstream-Statusfelder `transport_accepted` sein.
`fill` ist ebenfalls zulässig, kann aber Randinhalt abschneiden.

## Testumfang im geprüften Stand

- Gateway-Unit-Tests inklusive Format-, PPD-, Größen- und Idempotenzprüfung
- offizieller CUPS-`ipptool`-Attributtest
- PDF- und PostScript-Druck durch den laufenden Docker-Stack
- A4-Mismatch mit `held` und anschließender `fit`-Freigabe
- Backend-, SDK- und Studio-Test-/Build-Suiten

Die Drucktests erzeugen echte, persistente PrintHub-Jobdatensätze und Einträge
im virtuellen Drucker. Für wiederholte Tests sollte deshalb eine dafür gedachte
Entwicklungsinstanz verwendet werden.
