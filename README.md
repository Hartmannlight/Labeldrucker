# PrintHub ohne Thingdex-Inventar

Stand: 5. September 2026

Entwicklung baut die ausgecheckten Quellen mit `compose.yaml`. Die getrennten,
image-basierten Produktions- und Thingdex-Integrationsprofile sind in
[`docs/architecture/DEPLOYMENT_PROFILES.md`](docs/architecture/DEPLOYMENT_PROFILES.md)
dokumentiert; deren Platzhalter sind absichtlich nicht produktiv startbar.

Diese Variante betreibt nur die Etiketten- und Druckfunktionen. Sie enthält
keine Thingdex-API, keine Inventardatenbank und kein PostgreSQL.

## Repository-Aufteilung und Submodule

### Was ist das neue Repository?

Der Ordner `Labeldrucker` ist das Git-Repository für den Compose-Stack, die
Betriebsdokumentation und das IPP-Gateway. Dieses bislang lokale Repository wird
unter `Hartmannlight/Labeldrucker` veröffentlicht. Der Unterordner
`ipp-gateway/` ist weiterhin kein eigenes Repository.

Die Gesamtanwendung bleibt bewusst auf mehrere Komponenten verteilt:

- `Labeldrucker`: Docker Compose, IPP-Eingang, vorläufiger PrinterFleet-Quellcode und Betriebsdokumentation
- `PrintHub-ZPL-ll`: Druckjob-API, Rasterpipeline, Vorschau und logische Druckjobs
- `PrinterFleet`: zentrale physische Drucker, Fähigkeiten, Medienzustand und Auslieferungen
- `printhub-sdk`: generierter und kuratierter TypeScript-Client
- `LabelArchitect`: Studio-Oberfläche für Vorschau und Jobfreigabe
- `ZPL-II-Printer-Emulator`: virtueller Drucker für Entwicklung und Tests

Die fünf ausführbaren bzw. gebauten Abhängigkeiten sind unter `components/` als
Git-Submodule eingebunden. Ein `Labeldrucker`-Commit speichert ihre exakten
Commit-IDs, während ihre Quelldateien und Historien in den jeweiligen
Repositories bleiben.

| Repository | Branch | Zweck | geprüfter Commit |
| --- | --- | --- | --- |
| [LabelArchitect](https://github.com/Hartmannlight/LabelArchitect) | `main` | „PrintHub Studio“: Vorlagen, Designer, Quick Print und Druckerübersicht | `4d4c62f` |
| [printhub-sdk](https://github.com/Hartmannlight/printhub-sdk) | `main` | TypeScript-API-Client; Build-Abhängigkeit von PrintHub Studio | `c1a634f` |
| [PrintHub-ZPL-ll](https://github.com/Hartmannlight/PrintHub-ZPL-ll) | `main` | API, Vorlagen, langlebige Druckjobs und Drucker-Registry | `8024b56` |
| [ZPL-II-Printer-Emulator](https://github.com/Hartmannlight/ZPL-II-Printer-Emulator) | `main` | Virtueller Zebra-Drucker mit Webansicht | `d6df4d6` |
| [ZebraTamer](https://github.com/Hartmannlight/ZebraTamer) | `main` | Optionaler Agent für reale Zebra-Drucker | `8f7fb62` |

Die Änderungen des Studio-Rewrites sind auf `main` zusammengeführt. Die
aufgeführten Commits bilden den gemeinsam geprüften Stand.

Nicht benötigt werden `Thingdex`, `Thingdex-Home-Inventory`, `ThingdexUI`,
`thingdex-sdk` und PostgreSQL. `LabelGallery` wird ebenfalls nicht benötigt:
dessen Operator-Workflow ist in PrintHub Studio
aufgegangen.

## Verzeichnisstruktur und Checkout

Ein vollständiger Checkout hat diese Struktur:

```text
Labeldrucker/
├── components/
│   ├── LabelArchitect/             # Git-Submodule
│   ├── printhub-sdk/               # Git-Submodule
│   ├── PrintHub-ZPL-ll/            # Git-Submodule
│   ├── ZebraTamer/                  # Git-Submodule, künftiger PrintAgent
│   └── ZPL-II-Printer-Emulator/     # Git-Submodule
├── ipp-gateway/
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

`ZebraTamer` bleibt zur Laufzeit optional und wird nicht automatisch als
Container gestartet. Sein Quellstand ist jetzt dennoch als Submodul fest
eingebunden, weil er schrittweise zum herstellerneutralen PrintAgent entwickelt
wird. Reale Instanzen werden weiterhin über `ZPLGRID_ZEBRA_TAMER_AGENTS`
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
- PrintHub/OpenAPI: `http://localhost:8001/docs`
- Virtueller Zebra: `http://localhost:9191`
- IPP-/CUPS-Drucker: `ipp://localhost:8631/ipp/print`

PrinterFleet ist absichtlich nur im internen Compose-Netz erreichbar. PrintHub
liest den Druckerkatalog über dessen HTTP-API und übergibt fertige,
prüfsummengeschützte Druckartefakte. Druckeradressen und physische Zustellversuche
gehören damit nicht mehr zum dauerhaften Zielmodell von PrintHub.
Auch Discovery, Gerätestatus, Registry-Import/-Export und physische Retries
werden bei aktiviertem Fleet-Dienst lediglich durch die bisherigen PrintHub-
URLs durchgereicht. Dadurch bleiben Studio und SDK während der Migration
nutzbar, ohne zwei beschreibbare Quellen der Wahrheit zu erzeugen.

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
| Ungespeichertes Template drucken | `POST /v1/printers/{printer_id}/prints/template` | Ja | Template und Variablen werden direkt im Request mitgegeben. |
| RAW ZPL II drucken | `POST /v1/printers/{printer_id}/prints/zpl` | Ja | Body: `{"zpl":"^XA...^XZ"}`. Bei `raw9100` ergänzt PrintHub konfigurierte Gerätewerte, behält die Befehle des Payloads aber bei; an ZebraTamer geht RAW-ZPL unverändert. |
| Drucker und Status | `GET /v1/printers`, `GET /v1/printers/{id}/status` | Ja | Status nur, wenn der registrierte Drucker ihn unterstützt. |
| RAW-TCP/JetDirect Port 9100 | PrinterFleet → Drucker | Ja | Drucker mit `connection.protocol: raw_tcp` oder dem kompatiblen Namen `raw9100` werden zentral auf dem konfigurierten Host/Port angesprochen. Weder PrintHub noch PrinterFleet lauschen selbst als Drucker auf Port 9100. |
| RS232-zu-Ethernet | PrinterFleet → Bridge | Ja | `connection.protocol: serial_over_tcp` nutzt einen transparenten TCP-Bridge-Endpunkt; serielle Parameter werden auf der Bridge konfiguriert. |
| Virtueller Zebra auf Port 9100 | nur im Docker-Netz: `virtual-zebra:9100` | Ja, intern | In der mitgelieferten Compose-Datei wird 9100 nicht auf den Host veröffentlicht; von außen wird über die PrintHub-API gedruckt. |
| PrintHub selbst zu CUPS hinzufügen | `ipp://localhost:8631/ipp/print` | Ja | Driverless IPP-Queue für den mit `PRINTHUB_IPP_PRINTER_ID` ausgewählten PrintHub-Drucker. Akzeptiert PWG Raster, Apple Raster, PDF, PostScript und JPEG. |
| Bestehende CUPS-Queue als PrintHub-Ausgabegerät | – | Nein | Das Gateway ist ein Eingang für Anwendungen und CUPS. PrintHub sendet weiterhin über seine Geräte-Backends wie `raw9100` oder ZebraTamer. |

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

Danach erscheint `printhub-label` im Systemdruckdialog von Chrome. Das Gateway
meldet die in PrintHub konfigurierte bzw. von ZebraTamer gelesene Rollenbreite,
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

Beispiel für unverarbeitetes ZPL II:

```powershell
$body = @{ zpl = '^XA^FO30,30^A0N,40,40^FDHallo^FS^XZ' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8001/v1/printers/virtual-zebra/prints/zpl -ContentType application/json -Body $body
```

Der virtuelle Drucker wird beim ersten Start aus `config/printers.yml` in
PrinterFleet registriert und von dort direkt per `raw9100` angesprochen. Eine
separate ZebraTamer-/PrintAgent-Instanz ist nur für Geräte nötig, die der zentrale
Dienst nicht direkt erreichen kann, etwa USB- oder Bluetooth-Drucker. Die
YAML-Datei ist danach kein Laufzeitspeicher mehr.

## Zentrale Druckerverwaltung und Migration

PrinterFleet verwaltet Drucker und physische Zustellungen in
`/data/fleet.sqlite3` im eigenen `printer_fleet_data`-Volume. PrintHub behält
vorübergehend seine bisherige Registry als Kompatibilitätsfassade für alte
Studio-/SDK-Endpunkte; neue Katalogabfragen und Druckzustellungen laufen bereits
über PrinterFleet. Diese Übergangsphase vermeidet einen nicht rückrollbaren
Big-Bang-Datenumzug.

- Beim ersten Start wird die komplette bisherige YAML einmalig und atomar
  übernommen. Öffentliche IDs, Einstellungen und deaktivierte Geräte bleiben
  erhalten. Die originale Konfiguration bleibt zusätzlich als unveränderter
  Migrationsdatensatz in der Registry gespeichert.
- `config/printers.yml` ist schreibgeschützt eingebunden. Spätere Änderungen
  daran haben auch nach einem Neustart keinen automatischen Einfluss mehr.
- Bei ZebraTamer-Druckern werden Gerätevorgaben und eingelegte Rollen samt Farbe
  ausschließlich in der optionalen ZebraTamer-WebUI unter `/ui/` verwaltet.
  Studio verlinkt diese Oberfläche; **Edit settings** bearbeitet dort nur noch
  Namen, Aktivierung und Job-Standardwerte. Bei anderen Druckern bleiben die
  bisherigen Einstellungen verfügbar. Veraltete parallele Bearbeitungen werden
  mit Konfliktmeldung abgelehnt.
- **Import YAML** fügt Geräte hinzu; abweichende bestehende Einträge oder
  doppelte Geräte brechen den gesamten Import ohne Teiländerungen ab.
- **Export YAML** exportiert nur die gespeicherte Konfiguration, nicht den
  flüchtigen Erreichbarkeitsstatus. Exporte ersetzen kein vollständiges Backup
  des Volumes einschließlich Druckjobs und Vorlagen.
- Discovery aktualisiert bekannte Endpunkte und Erreichbarkeit alle 30 Sekunden
  sowie bei **Discover / refresh agents**. Sie fügt Geräte nicht automatisch
  hinzu. Rollenangaben werden für ZebraTamer-Geräte direkt vom Agenten gelesen;
  alte Medien-, Kalibrierungs- und Druckwerte der Registry bleiben Archivdaten.
- Offline-Geräte bleiben gespeichert. Zwei Agenten mit derselben lokalen
  Drucker-ID erhalten getrennte öffentliche IDs. Wiederholtes Hinzufügen
  desselben Geräts erhält die bestehende ID und alle Einstellungen.

Vor dem ersten Update das bestehende Volume und `config/printers.yml` sichern.
Bei widersprüchlichen doppelten Geräten bricht die Migration sicher ab; die
YAML bleibt unverändert. Vor einem Rollback auf die alte Version die aktuelle
Registry als YAML exportieren, da ältere Versionen SQLite nicht lesen.

Logs und Stoppen:

```powershell
docker compose logs -f printhub printer-fleet studio virtual-zebra ipp-gateway
docker compose down
```

`docker compose down` behält Vorlagen, Druckjobs und Emulatorzustand. Nur
`docker compose down -v` löscht die beiden benannten Volumes und damit diese
Daten.

## Reale Zebra-Drucker mit ZebraTamer

ZebraTamer läuft am besten nativ auf dem Linux-Rechner oder Raspberry Pi, an
dem der USB-Drucker angeschlossen ist. Die Installation aus dem Repository:

```sh
curl -fsSL https://github.com/Hartmannlight/ZebraTamer/releases/latest/download/install.sh | sh
```

Anschließend `/etc/zpl-agent/config.toml` prüfen. Wichtig sind der korrekte
Character-Device-Pfad (zum Beispiel `/dev/usb/lp0`) und ein erreichbarer REST-Port.
Die aktualisierte ZebraTamer-Version unterstützt eine explizite eindeutige
`agent_id`; ohne Angabe erzeugt sie einmalig eine UUID in `data_dir/agent-id`.
Diese Datei dauerhaft erhalten und mitsichern. ZebraTamer arbeitet ohne Thingdex.

Bereits installierte ältere Agenten bleiben adressgebunden nutzbar. Sichere
automatische IP-Wechsel benötigen das ZebraTamer-Update. Beim ersten Erkennen
der neuen Identität am bisherigen Endpunkt bleibt die bestehende Drucker-ID
erhalten. Ein anderer Agent am selben Endpunkt wird nicht still übernommen.

Wenn PrintHub und ZebraTamer nicht zuverlässig per mDNS miteinander sprechen
können (typisch bei Docker oder getrennten Netzen), die Agenten explizit in
`.env` eintragen:

```dotenv
ZPLGRID_ZEBRA_TAMER_AGENTS=http://192.168.1.50:8080
```

Mehrere URLs werden durch Kommas getrennt. Alternativ im Studio **Manual
ZebraTamer URL** verwenden. Vor **Add** die eingelegte Rolle und die tatsächliche
DPI in ZebraTamer einrichten: Medienformat und Farbe kommen vom Agenten,
Gerätewerte aus seiner Abfrage bzw. dem bestätigten Hardwareprofil. Die optionale
WebUI wird dort mit `webui_enabled = true` und einem eigenen `admin_token`
aktiviert und ist unter `http://<agent-host>:8080/ui/` erreichbar. Details stehen
in der ZebraTamer-README. PrintHub sendet für diese Geräte keine automatischen
Intensitäts-, Geschwindigkeits- oder Modusvorgaben mehr; selbst erzeugte Jobs
überschreiben auch nicht die Gerätemaße. Explizites Raw-ZPL bleibt unverändert.
Die öffentliche ID wird von PrintHub vergeben (`zt-…` für neue
Agentendrucker); bestehende IDs bleiben erhalten. Die tatsächliche ID aus
`GET /v1/printers` kann als Standard gesetzt werden, beispielsweise:

```dotenv
ZPLGRID_DEFAULT_PRINTER_ID=virtual-zebra
```

Nach einer Änderung:

```powershell
docker compose up -d --force-recreate printhub studio
```

Kontrolle:

```powershell
curl.exe http://localhost:8001/v1/printers
```

Der virtuelle Drucker und alle bereits registrierten ZebraTamer-Geräte sollten
in der Antwort sowie in PrintHub Studio unter `/#/printers` erscheinen.
Eine Agent-URL konfiguriert nur die Discovery, nicht automatisch Drucker.

## Wichtige `.env`-Werte

- `ZPLGRID_ZEBRA_TAMER_AGENTS`: explizite Agent-URLs; für Docker der
  zuverlässigste Discovery-Weg.
- `ZPLGRID_DEFAULT_PRINTER_ID`: vorausgewählter Drucker in PrintHub Studio.
- `ZPLGRID_DISCOVERY_INTERVAL_SECONDS`: automatische Aktualisierung bekannter
  Agenten; Standard 30 Sekunden, `0` deaktiviert nur die periodische Discovery.
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

In dieser Konfiguration existieren bewusst weder `DATABASE_URL` noch
PostgreSQL-Zugangsdaten. Die SQLite-Registry liegt im vorhandenen Datenvolume.
