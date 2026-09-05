# Docker- und IPP-Integrationstest

Diese Tests sprechen den tatsächlich laufenden `ippeveprinter`, die PrintHub-
API und den virtuellen Zebra-Drucker an. Sie sind damit mehr als Unit-Tests der
Konvertierungsfunktionen.

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
`GET http://localhost:8001/v1/print-jobs` hat `source_kind: "document"`, den
Status `sent` und eine positive Zahl in `bytes_sent`. Das beweist den Weg
PDF → IPP → Document-API → 1-Bit-Raster → ZPL → virtueller Zebra.

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

Danach muss der Status `sent` sein. `fill` ist ebenfalls zulässig, kann aber
Randinhalt abschneiden.

## Testumfang im geprüften Stand

- Gateway-Unit-Tests inklusive Format-, PPD-, Größen- und Idempotenzprüfung
- offizieller CUPS-`ipptool`-Attributtest
- PDF- und PostScript-Druck durch den laufenden Docker-Stack
- A4-Mismatch mit `held` und anschließender `fit`-Freigabe
- Backend-, SDK- und Studio-Test-/Build-Suiten

Die Drucktests erzeugen echte, persistente PrintHub-Jobdatensätze und Einträge
im virtuellen Drucker. Für wiederholte Tests sollte deshalb eine dafür gedachte
Entwicklungsinstanz verwendet werden.
