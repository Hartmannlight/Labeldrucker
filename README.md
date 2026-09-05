# PrintHub ohne Thingdex-Inventar

Stand: 5. September 2026

Entwicklung baut die ausgecheckten Quellen mit `compose.yaml`. Die getrennten,
image-basierten Produktions- und Thingdex-Integrationsprofile sind in
[`docs/architecture/DEPLOYMENT_PROFILES.md`](docs/architecture/DEPLOYMENT_PROFILES.md)
dokumentiert; deren Platzhalter sind absichtlich nicht produktiv startbar.
Die aktuelle Zuordnung stabiler und nur vorübergehend weitergereichter APIs steht
in [`docs/architecture/API_COMPATIBILITY_MATRIX.md`](docs/architecture/API_COMPATIBILITY_MATRIX.md).
Die Freigabe mit echten Zebra-/Bridge-/Agent-Geräten folgt
[`docs/acceptance/REAL_PRINTER_ACCEPTANCE.md`](docs/acceptance/REAL_PRINTER_ACCEPTANCE.md).

Das Quellcodeprofil betreibt nur die Etiketten- und Druckfunktionen. Es enthält
keine Thingdex-API und nutzt für Fleet lokal SQLite. Das eigenständige
Produktionsprofil nutzt Fleet-PostgreSQL; das optionale Thingdex-Profil besitzt
eine davon vollständig getrennte PostgreSQL-Datenbank.

## Repository-Aufteilung und Submodule

### Was ist das neue Repository?

Der Ordner `Labeldrucker` ist das öffentliche Git-Repository für den
Compose-Stack, die Betriebsdokumentation und das IPP-Gateway. Es liegt unter
`Hartmannlight/Labeldrucker`. Der Unterordner
`ipp-gateway/` ist weiterhin kein eigenes Repository.

Die Gesamtanwendung bleibt bewusst auf mehrere Komponenten verteilt:

- `Labeldrucker`: Docker Compose, IPP-Eingang, PrinterFleet, Fleet Console und Betriebsdokumentation
- `PrintHub-ZPL-ll`: Druckjob-API, Rasterpipeline, Vorschau und logische Druckjobs
- `PrinterFleet`: zentrale physische Drucker, Fähigkeiten, Medienzustand und Auslieferungen
- `printhub-sdk`: generierter und kuratierter TypeScript-Client
- `LabelArchitect`: Studio-Oberfläche für Vorschau und Jobfreigabe
- `ZPL-II-Printer-Emulator`: virtueller Drucker für Entwicklung und Tests

Die sieben ausführbaren bzw. gebauten Abhängigkeiten sind unter `components/` als
Git-Submodule eingebunden. Ein `Labeldrucker`-Commit speichert ihre exakten
Commit-IDs, während ihre Quelldateien und Historien in den jeweiligen
Repositories bleiben.

| Repository | Branch | Zweck | geprüfter Commit |
| --- | --- | --- | --- |
| [LabelArchitect](https://github.com/Hartmannlight/LabelArchitect) | `main` | „PrintHub Studio“: Vorlagen, Designer und Quick Print | `880d76b` |
| [printhub-sdk](https://github.com/Hartmannlight/printhub-sdk) | `main` | TypeScript-API-Client; Build-Abhängigkeit von PrintHub Studio | `f33b456` |
| [PrintHub-ZPL-ll](https://github.com/Hartmannlight/PrintHub-ZPL-ll) | `main` | Dokumente, Vorlagen, Vorschau und logische Druckjobs | `8e1dd41` |
| [ZPL-II-Printer-Emulator](https://github.com/Hartmannlight/ZPL-II-Printer-Emulator) | `main` | Virtueller Zebra-Drucker mit Webansicht | `52e7927` |
| [ZebraTamer](https://github.com/Hartmannlight/ZebraTamer) | `main` | Optionaler PrintAgent für lokal angeschlossene Drucker | `6b6ffad` |
| [Thingdex](https://github.com/Hartmannlight/Thingdex) | `main` | Unabhängiger Inventardienst mit asynchroner PrintHub-Anbindung | `a1f8483` |
| [Thingdex-Home-Inventory](https://github.com/Hartmannlight/Thingdex-Home-Inventory) | `main` | Übergeordnete Produktintegration und Migrationskontext | `a07c133` |

Die Änderungen des Studio-Rewrites sind auf `main` zusammengeführt. Die
aufgeführten Commits bilden den gemeinsam geprüften Stand.

Thingdex und Thingdex-Home-Inventory sind im eigenständigen Druckprofil nicht
laufzeitnotwendig, bleiben aber als exakt versionierter Integrationskontext
eingebunden. `ThingdexUI`, `thingdex-sdk` und `LabelGallery` werden für diesen
Stack nicht gebaut.

## Verzeichnisstruktur und Checkout

Ein vollständiger Checkout hat diese Struktur:

```text
Labeldrucker/
├── components/
│   ├── LabelArchitect/             # Git-Submodule
│   ├── printhub-sdk/               # Git-Submodule
│   ├── PrintHub-ZPL-ll/            # Git-Submodule
│   ├── Thingdex/                    # Git-Submodule, optionale Integration
│   ├── Thingdex-Home-Inventory/     # Git-Submodule, Produktkontext
│   ├── ZebraTamer/                  # Git-Submodule, künftiger PrintAgent
│   └── ZPL-II-Printer-Emulator/     # Git-Submodule
├── ipp-gateway/
├── fleet-console/                  # getrennte physische Druckerverwaltung
├── printer-fleet/                  # eigenständiger Dienst, vorläufig hier inkubiert
└── compose.yaml
```

Checkout einschließlich Submodule:

```powershell
git clone --recurse-submodules https://github.com/Hartmannlight/Labeldrucker.git
cd Labeldrucker
```

Bei einem bereits vorhandenen Checkout werden fehlende Submodule so geladen:

```powershell
git submodule update --init --recursive
```

Der noch im Repository `ZebraTamer` liegende PrintAgent bleibt zur Laufzeit
optional und wird nicht automatisch als
Container gestartet. Sein Quellstand ist jetzt dennoch als Submodul fest
eingebunden, weil er schrittweise zum herstellerneutralen PrintAgent entwickelt
wird. Reale Instanzen werden über `PRINTER_FLEET_AGENT_URLS`
angebunden.

## Konfiguration und Start

Voraussetzung ist Docker mit Compose v2.

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build -d
docker compose ps
```

Danach sind erreichbar:

- PrintHub Studio: `http://localhost:8088`
- PrinterFleet Console: `http://localhost:8089`
- PrintHub/OpenAPI: `http://localhost:8001/docs`
- Virtueller Zebra: `http://localhost:9191`
- IPP-/CUPS-Drucker: `ipp://localhost:8631/ipp/print`

PrinterFleet ist absichtlich nur im internen Compose-Netz erreichbar. PrintHub
liest den Druckerkatalog über dessen HTTP-API und übergibt fertige,
prüfsummengeschützte Druckartefakte. Druckeradressen und physische Zustellversuche
gehören damit nicht mehr zum dauerhaften Zielmodell von PrintHub.
Die getrennte Fleet Console greift über einen same-origin Proxy direkt auf
PrinterFleet zu. Im Entwicklungsprofil kann zum Anmelden
`development-fleet-admin-token` verwendet werden; das Token bleibt nur im Speicher
des Browser-Tabs. Produktionszugänge stammen aus der strukturierten Fleet-
Credential-Datei und müssen über TLS bereitgestellt werden.
Discovery, Gerätestatus, Registry-Import/-Export, Wartung und physische Retries
existieren ausschließlich in PrinterFleet und Fleet Console. PrintHub erhält
nur einen bereinigten Katalog ohne Endpunkte oder Zugangsdaten.

## Schnittstellen: Was kann wie angesprochen werden?

Der Compose-Stack bindet Studio, API, IPP und Emulator-Webansicht standardmäßig nur
an den lokalen Rechner. Für Aufrufe aus dem LAN müssen die `127.0.0.1:`-Bindings
in `compose.yaml` bewusst geändert und der Zugriff passend abgesichert werden.

| Zweck | Adresse / Endpunkt | Unterstützt? | Hinweise |
| --- | --- | --- | --- |
| Studio im Browser | `http://localhost:8088` | Ja | Vorlagen auswählen, ausfüllen und drucken; Designer unter `/#/designer`. |
| Interaktive API-Dokumentation | `http://localhost:8001/docs` | Ja | OpenAPI/Swagger ist die vollständige, laufzeitaktuelle Referenz. |
| Healthcheck | `GET http://localhost:8001/health` | Ja | Antwortet mit `{"status":"ok"}`. |
| Vorlagen auflisten / laden | `GET /v1/templates`, `GET /v1/templates/{id}` | Ja | Die Startseite zeigt genau diese direkt nutzbaren Vorlagen. |
| Vorlage anlegen / ändern | `POST /v1/templates`, `PUT /v1/templates/{id}` | Ja | Enthält Template-JSON, Felddefinitionen, Beispieldaten und Vorschauziel. |
| Template rendern | `POST /v1/renders/zpl`, `POST /v1/renders/png` | Ja | Rendert ohne zu drucken; Variablen dürfen auch Zeilenumbrüche enthalten. |
| Gespeichertes Template drucken | `POST /v1/print-jobs` | Ja | Langlebiger Job mit `printer_id`, `template_id` und `variables`; Status über `GET /v1/print-jobs/{id}`. |
| Ungespeichertes Template drucken | `POST /v1/print-jobs` | Ja | Statt `template_id` wird ein unveränderlicher `template`-Snapshot im langlebigen Job gespeichert. |
| RAW ZPL II drucken | Direkter PrinterFleet-Delivery-Vertrag | Nur für kontrollierte Integrationen | PrintHub veröffentlicht absichtlich keinen beliebigen RAW-ZPL-Endpunkt. PrinterFleet validiert Treiber und Berechtigung. |
| Druckerauswahl | `GET /v1/printers`, `GET /v1/printers/{id}` in PrintHub | Ja | Liefert nur Fleet-Snapshots ohne physische Endpunkte. Status und Administration liegen in Fleet Console. |
| RAW-TCP/JetDirect Port 9100 | PrinterFleet → Drucker | Ja | `connection.protocol: raw_tcp`; Port 9100 ist der Standard. Weder PrintHub noch PrinterFleet lauschen selbst als Drucker auf Port 9100. |
| RS232-zu-Ethernet | PrinterFleet → Bridge | Ja | `connection.protocol: serial_over_tcp` nutzt einen transparenten TCP-Bridge-Endpunkt; serielle Parameter werden auf der Bridge konfiguriert. |
| Virtueller Zebra auf Port 9100 | nur im Docker-Netz: `virtual-zebra:9100` | Ja, intern | In der mitgelieferten Compose-Datei wird 9100 nicht auf den Host veröffentlicht; von außen wird über die PrintHub-API gedruckt. |
| PrintHub selbst zu CUPS hinzufügen | `ipp://localhost:8631/ipp/print` | Ja | Driverless IPP-Queue für den mit `PRINTHUB_IPP_PRINTER_ID` ausgewählten PrintHub-Drucker. Akzeptiert PWG Raster, Apple Raster, PDF, PostScript und JPEG. |
| Bestehende CUPS-Queue als PrintHub-Ausgabegerät | – | Nein | Das Gateway ist ein Eingang. Physische Ausgabe erfolgt ausschließlich über PrinterFleet oder PrintAgent. |

## Aus Chrome und CUPS drucken

Das optionale `ipp-gateway` bildet genau einen PrintHub-Drucker als
driverless IPP-Drucker ab. CUPS handelt das Dokumentformat mit dem Gateway aus.
PWG Raster ist der bevorzugte gemeinsame Weg; das von AirPrint-Clients genutzte
Apple Raster sowie PDF-, PostScript- und JPEG-Dokumente werden ebenfalls
angenommen. PNG und JPEG stehen außerdem direkt über die Raster-API zur
Verfügung. Alle Eingaben durchlaufen dieselbe Schwarz-Weiß-Rasterpipeline und
werden für einen Zebra-Drucker als `^GF`-Grafik ausgegeben. Damit ist dieselbe
Zwischendarstellung später auch für einen Niimbot-Bitmaptreiber nutzbar.

Eine reproduzierbare Prüfung der IPP-Fähigkeiten, eines echten PDF-Druckjobs und
des A4-Sicherheitsfalls ist unter
[`ipp-gateway/tests/README.md`](ipp-gateway/tests/README.md) beschrieben.

Unter Linux kann die Queue so hinzugefügt werden:

```sh
sudo lpadmin -p printhub-label -E \
  -v ipp://localhost:8631/ipp/print \
  -m everywhere
lpstat -p printhub-label
```

Unter Windows 11 kann derselbe lokale Gateway aus einer als Administrator
gestarteten PowerShell als systemweite IPP-Queue eingerichtet werden:

```powershell
Add-Printer -Name "PrintHub 50x25 Label" `
  -IppURL "http://localhost:8631/ipp/print"
Get-Printer -Name "PrintHub 50x25 Label"
```

Windows verwendet dafür den integrierten `Microsoft IPP Class Driver`; ein
herstellerspezifischer Zebra-Treiber ist auf dem Client nicht erforderlich.
Chrome verwendet unter Windows diese Systemqueue. Zum späteren Entfernen dient
`Remove-Printer -Name "PrintHub 50x25 Label"` in einer administrativen
PowerShell. Die Queue ist nicht der Standarddrucker, solange dies nicht separat
im Betriebssystem geändert wird.

Für einen reproduzierbaren Chrome-Test steht die exakt einseitige Datei
[`ipp-gateway/tests/fixtures/chrome-label-50x25.html`](ipp-gateway/tests/fixtures/chrome-label-50x25.html)
bereit. Die Dialog- und Abnahmeschritte sind in
[`ipp-gateway/tests/README.md`](ipp-gateway/tests/README.md) beschrieben.

Danach erscheint die Queue im Systemdruckdialog von Chrome. Das Gateway
meldet die aus PrinterFleet gelesene Rollenbreite,
Rollenhöhe, Auflösung und den monochromen Farbraum an CUPS. Bei einer Änderung
des eingelegten Mediums das Gateway neu starten, damit bereits geöffnete
Druckdialoge die neuen Fähigkeiten abfragen:

```sh
docker compose restart ipp-gateway
```

Die sichere Standardrichtlinie ist `hold`: Eine A4-Seite für ein 50 × 50-mm-
Label wird als langlebiger Job gespeichert und erhält eine exakte Fit-Vorschau,
aber nicht automatisch gedruckt. Die Freigabe erfolgt bewusst mit
`{"scaling":"fit"}` oder `{"scaling":"fill"}`:

```sh
curl -X POST http://localhost:8001/v1/print-jobs/JOB_ID/release \
  -H 'Content-Type: application/json' \
  -d '{"scaling":"fit"}'
```

Jede Dokumentseite wird zu einem Label. Farbige Inhalte werden auf Graustufen
und anschließend auf die Schwarz-Weiß-Ausgabe des Druckers reduziert. Fotos
können über `print-content-optimize=photo` mit Floyd-Steinberg-Dithering
ausgegeben werden; Text, Linien und Barcodes bleiben ohne Dithering scharf.
Die gespeicherte Vorschau zeigt schwarze Druckpunkte auf der in PrintHub
gemeldeten Label-Farbe. Sie entspricht bei angehaltenen Jobs der sicheren
`fit`-Variante; `fill` kann sichtbar Randinhalte abschneiden.

Standardmäßig veröffentlicht Docker IPP nur auf `127.0.0.1` des Hosts. Das
Gateway selbst ist innerhalb des Compose-Netzes ebenfalls erreichbar. Für CUPS auf einem anderen
Rechner müssen `PRINTHUB_IPP_BIND=0.0.0.0` und
`PRINTHUB_IPP_HOSTNAME=<vom-client-auflösbarer-hostname>` gesetzt werden. Dieser
Hostname muss im LAN auf den Docker-Host zeigen; IP-Adressen sind für diese
Option nicht vorgesehen. Das
Gateway besitzt derzeit keine Anmeldung; der Port darf daher nur in ein
vertrauenswürdiges Netz oder hinter eine geeignete Zugriffskontrolle freigegeben
werden.

Die Windows-Einrichtung kann zunächst versuchen, die Verbindung auf HTTPS
anzuheben. Da das lokale Entwicklungs-Gateway kein TLS-Zertifikat besitzt,
bleibt die tatsächlich konfigurierte URL bei `http://localhost:8631`. Diese
Variante ist nur für die Loopback-Bindung vorgesehen; für LAN- oder
Produktionszugriff ist TLS an einem vorgeschalteten, authentifizierenden
Ingress erforderlich.

Der Compose-Stack ordnet denselben Namen innerhalb des Gateway-Containers sowohl
`127.0.0.1` als auch `::1` zu. Diese interne Loopback-Zuordnung ist erforderlich,
weil `ippeveprinter` IPv4- und IPv6-Listener öffnet; Clients im LAN lösen den
Namen dagegen weiterhin auf die Adresse des Docker-Hosts auf.

Im Produktionsprofil ist mDNS bewusst deaktiviert und der IPP-Prozess läuft ab
Containerstart als UID 10002 ohne Linux-Capabilities. Die Queue wird dort über
ihre explizite `ipp://`-Adresse eingerichtet. Nur das Quellcode-
Entwicklungsprofil startet für D-Bus/Avahi kurzzeitig privilegiert und senkt den
eigentlichen IPP-Prozess anschließend auf UID 10002 ab.

Mehrzeilige Werte bleiben im API- und Render-Layer normale JSON-Strings mit
Zeilenumbrüchen. Die Felddefinition `{"type":"textarea","rows":4}` steuert nur
die Darstellung des Formulars in Studio. Dadurch braucht ein Template wie
`briefadresse` genau eine Variable und dieselbe Vorlage funktioniert unverändert
über Weboberfläche und API.

In **Quick print** gilt die gewählte Ausgabegröße immer gemeinsam für Vorschau
und Druckauftrag. Zur Wahl stehen die im Template gespeicherte Originalgröße,
die vom ausgewählten Drucker gemeldete eingelegte Rolle, weitere konfigurierte
Standardgrößen und frei eingebbare Maße. Bei einer Abweichung erklärt Studio, ob das Layout angepasst
wird oder auf dem eingelegten Medium abgeschnitten werden könnte. Virtuelle
Drucker werden in der Auswahl ausdrücklich als solche markiert. Studio startet
bei neuen Browserprofilen im Light Theme; eine anschließend gewählte Darstellung
wird lokal im Browser gespeichert.

Beispiel für eine dreizeilige Adresse über ein gespeichertes Template:

```powershell
$body = @{
  printer_id = 'virtual-zebra'
  template_id = 'briefadresse'
  variables = @{ address = "Erika Mustermann`nMusterstrasse 17`n51147 Koeln" }
  origin = 'powershell'
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8001/v1/print-jobs -ContentType application/json -Body $body
```

Der virtuelle Drucker wird beim ersten Start aus `config/printers.yml` in
PrinterFleet registriert und von dort direkt per `raw_tcp` angesprochen. Eine
separate PrintAgent-Instanz ist nur für Geräte nötig, die der zentrale
Dienst nicht direkt erreichen kann, etwa USB- oder Bluetooth-Drucker. Die
YAML-Datei ist danach kein Laufzeitspeicher mehr.

## Zentrale Druckerverwaltung und Migration

PrinterFleet verwaltet Drucker und physische Zustellungen. Das lokale
Quellcodeprofil nutzt `/data/fleet.sqlite3`; das Produktionsprofil nutzt eine
eigene PostgreSQL-Datenbank mit eigenem Benutzer und Volume. PrintHub besitzt
keine lokale physische Registry mehr. Fleet Console ist die Verwaltungsoberfläche
für Registry, Status, Medienzustand, Wartung, Discovery und Queues.

Ein alter PrintHub-YAML-/JSON-Export oder eine alte `printers.sqlite3` wird
offline und ohne Änderung der Quelle konvertiert:

```sh
python -m printer_fleet.legacy_import \
  --source /backup/printers.sqlite3 \
  --output /backup/printer-fleet-import.json
```

Die Ausgabe kann ein globaler Fleet-Administrator über
`POST /v1/printer-registry/import` atomar importieren. `raw9100` wird zu
`raw_tcp`, `zebra_tamer` beziehungsweise `driver_agent` wird zu `print_agent`.
Fehlt bei einem alten Agent-Gerät die stabile `agent_id`, bricht das Werkzeug
ab: Das Gerät muss über Fleet Console neu entdeckt werden, statt eine Identität
zu erraten. Die Exportdatei enthält physische Endpunkte und ist wie ein Secret
zu behandeln. Vor jeder Migration Datenbank und Quellexport unverändert sichern.

Im Produktionsprofil sind Fleet-API und Fleet-Worker zwei Prozesse desselben
Images. Der Worker allein besitzt Geräte-I/O und Crash-Recovery; ein Neustart
der Verwaltungs-API verändert deshalb keinen laufenden Druckauftrag. Das lokale
Quellcodeprofil hält beide Rollen für einen kleinen Entwicklungsstack weiterhin
in einem Container.

Logs und Stoppen:

```powershell
docker compose logs -f printhub printer-fleet studio virtual-zebra ipp-gateway
docker compose down
```

`docker compose down` behält Vorlagen, Druckjobs und Emulatorzustand. Nur
`docker compose down -v` löscht die beiden benannten Volumes und damit diese
Daten.

## Lokal angeschlossene Drucker mit PrintAgent

Der aus ZebraTamer hervorgegangene PrintAgent läuft nativ auf dem Linux-Rechner
oder Raspberry Pi, an
dem der USB-Drucker angeschlossen ist. Die Installation aus dem Repository:

```sh
curl -fsSL https://github.com/Hartmannlight/ZebraTamer/releases/latest/download/install.sh | sh
```

Anschließend `/etc/zpl-agent/config.toml` prüfen. Wichtig sind der korrekte
Character-Device-Pfad (zum Beispiel `/dev/usb/lp0`) und ein erreichbarer REST-Port.
Der Agent unterstützt eine explizite eindeutige
`agent_id`; ohne Angabe erzeugt er einmalig eine UUID in `data_dir/agent-id`.
Diese Datei dauerhaft erhalten und mitsichern. PrintAgent arbeitet ohne Thingdex
und kommuniziert ausschließlich mit PrinterFleet.

Für einen direkt an Docker Desktop angeschlossenen USB-Drucker steht der
separate Override `compose.usb-agent.yaml` bereit. Docker Desktop unterstützt
kein gewöhnliches Host-USB-Passthrough; das Gerät muss zuerst per USB/IP an die
Linux-VM angehängt werden. Danach wird ausschließlich der konkrete
`/dev/bus/usb/<bus>/<device>`-Knoten dem non-root PrintAgent zugewiesen:

```powershell
Copy-Item deploy/secrets/print-agent-usb.toml.example `
  deploy/secrets/print-agent-usb.toml
# VID, PID, Seriennummer und Geräteprofil in der lokalen Datei verifizieren.
usbipd bind --busid BUS-ID                 # einmalig als Administrator
usbipd attach --wsl docker-desktop --busid BUS-ID
$env:PRINT_AGENT_USB_DEVICE = "/dev/bus/usb/001/002"
$env:ZPL_AGENT_GIT_COMMIT = git -C components/ZebraTamer rev-parse HEAD
wsl -d docker-desktop -u root -- chown 0:999 $env:PRINT_AGENT_USB_DEVICE
wsl -d docker-desktop -u root -- chmod 0660 $env:PRINT_AGENT_USB_DEVICE
docker compose -f compose.yaml -f compose.usb-agent.yaml up -d --build
```

Bus- und Gerätenummer können sich nach Abziehen oder Neustart ändern. Vor jedem
Start anhand von `usbipd list` und `lsusb` neu verifizieren; nie einen breiten
USB-Bus oder `--privileged` an den Agenten durchreichen. Die lokale TOML-Datei
ist über `deploy/secrets/*` von Git ausgeschlossen. Das Beispiel enthält keine
einsatzfähige Geräteidentität. `usb_bulk` greift über `libusb` direkt auf die
Printer-Class-Bulk-Endpunkte zu und funktioniert deshalb auch dann, wenn der
Docker-Desktop-Kernel kein `usblp`-Modul und damit kein `/dev/usb/lp0` anbietet.
Der vollständige `ZPL_AGENT_GIT_COMMIT` wird in die Agent-Identitäts- und
Metrikantwort eingebettet. Ohne die Variable trägt ein gewöhnlicher lokaler
Build bewusst den Marker `development`; für revisionsgebundene Hardwaretests
ist der aus dem gepinnten Submodule gelesene SHA verpflichtend.

Wenn PrinterFleet und PrintAgent nicht zuverlässig per mDNS miteinander sprechen
können, die Agenten explizit in
`.env` eintragen:

```dotenv
PRINTER_FLEET_AGENT_URLS=http://192.168.1.50:8080
```

Mehrere URLs werden durch Kommas getrennt. Alternativ kann ein globaler
Administrator die URL in Fleet Console anstoßen. Medienformat, Farbe und DPI
werden im Agenten bestätigt und als beobachteter Fleet-Zustand geführt. Die
öffentliche Drucker-ID wird bei der Registrierung in PrinterFleet vergeben. Sie
kann als PrintHub-Standard gesetzt werden, beispielsweise:

```dotenv
ZPLGRID_DEFAULT_PRINTER_ID=virtual-zebra
```

Nach einer Änderung:

```powershell
docker compose up -d --force-recreate printer-fleet printhub studio
```

Kontrolle:

```powershell
curl.exe http://localhost:8001/v1/printers
```

Der virtuelle Drucker und alle registrierten PrintAgent-Geräte erscheinen in
der PrintHub-Auswahlliste. Physische Details und Administration bleiben in Fleet
Console. Eine Agent-URL konfiguriert nur Discovery, nicht automatische
Registrierung.

## Wichtige `.env`-Werte

- `PRINTER_FLEET_AGENT_URLS`: explizite Agent-URLs; für Docker der
  zuverlässigste Discovery-Weg.
- `ZPLGRID_DEFAULT_PRINTER_ID`: vorausgewählter Drucker in PrintHub Studio.
- `PRINTER_FLEET_DISCOVERY_INTERVAL_SECONDS`: automatische Aktualisierung bekannter
  Agenten; Standard 30 Sekunden, `0` deaktiviert nur die periodische Discovery.
- `PRINTHUB_FLEET_API_TOKEN`: eingeschränkter `observer`-/`submitter`-Zugang
  von PrintHub zu den erlaubten Sites.
- `PRINTER_FLEET_ADMIN_TOKEN`: lokaler Entwicklungszugang für Fleet Console;
  Produktion verwendet gemountete strukturierte Credentials.
- `PRINTHUB_STUDIO_PORT`, `PRINTHUB_API_PORT`, `VIRTUAL_ZEBRA_WEB_PORT`:
  Host-Ports, falls die Defaults bereits belegt sind.
- `PRINTHUB_IPP_PORT`, `PRINTHUB_IPP_BIND`, `PRINTHUB_IPP_HOSTNAME`:
  Port, Bind-Adresse und die gegenüber CUPS gemeldete Adresse des IPP-Druckers.
- `PRINTHUB_IPP_PRINTER_ID`: der als IPP-Queue veröffentlichte PrintHub-Drucker.
- `PRINTHUB_IPP_MISMATCH_POLICY`: `hold` (sicherer Standard), `fit` oder
  `fill` für abweichende Dokument- und Labelgrößen.
- `ZPLGRID_ENABLE_LABELARY_*`: nur für PNG-Vorschauen. Für das eigentliche
  Erzeugen und Versenden von ZPL nicht erforderlich.
- `TZ`: Zeitzone für zeitabhängige Template-Makros.

Im lokalen Quellcodeprofil existieren bewusst weder `DATABASE_URL` noch
PostgreSQL-Zugangsdaten. Für das Produktionsprofil werden Fleet-Passwort und
Fleet-Datenbank-URL getrennt als Dateien eingebunden; Thingdex besitzt weiterhin
seine eigene Datenbank und kann Fleet-Tabellen weder lesen noch schreiben.
