# PrintHub ohne Thingdex-Inventar

Stand: 27. August 2026

Diese Variante betreibt nur die Etiketten- und Druckfunktionen. Sie enthält
keine Thingdex-API, keine Inventardatenbank und kein PostgreSQL.

## Benötigte Repositories und Branches

| Repository | Branch | Zweck | geprüfter Commit |
| --- | --- | --- | --- |
| [LabelArchitect](https://github.com/Hartmannlight/LabelArchitect) | `main` | „PrintHub Studio“: Vorlagen, Designer, Quick Print und Druckerübersicht | `28b909c` |
| [printhub-sdk](https://github.com/Hartmannlight/printhub-sdk) | `main` | TypeScript-API-Client; Build-Abhängigkeit von PrintHub Studio | `406eac0` |
| [PrintHub-ZPL-ll](https://github.com/Hartmannlight/PrintHub-ZPL-ll) | `main` | API, Vorlagen, langlebige Druckjobs und Drucker-Registry | `5b902a7` |
| [ZPL-II-Printer-Emulator](https://github.com/Hartmannlight/ZPL-II-Printer-Emulator) | `main` | Virtueller Zebra-Drucker mit Webansicht | `6afb22a` |
| [ZebraTamer](https://github.com/Hartmannlight/ZebraTamer) | `main` | Optionaler Agent für reale Zebra-Drucker | `8f7fb62` |

Die Änderungen des Studio-Rewrites sind auf `main` zusammengeführt. Die
aufgeführten Commits bilden den gemeinsam geprüften Stand.

Nicht benötigt werden `Thingdex`, `Thingdex-Home-Inventory`, `ThingdexUI`,
`thingdex-sdk` und PostgreSQL. `LabelGallery` wird ebenfalls nicht benötigt:
dessen Operator-Workflow ist in PrintHub Studio
aufgegangen.

## Verzeichnisstruktur und Checkout

Alle Repositories und dieser Ordner müssen nebeneinander liegen:

```text
printhub-only/
├── LabelArchitect/
├── printhub-sdk/
├── PrintHub-ZPL-ll/
├── ZebraTamer/
├── ZPL-II-Printer-Emulator/
└── printer-only-stack/
```

Checkout in PowerShell:

```powershell
mkdir printhub-only
cd printhub-only
git clone -b main https://github.com/Hartmannlight/LabelArchitect.git
git clone -b main https://github.com/Hartmannlight/printhub-sdk.git
git clone -b main https://github.com/Hartmannlight/PrintHub-ZPL-ll.git
git clone -b main https://github.com/Hartmannlight/ZPL-II-Printer-Emulator.git
git clone -b main https://github.com/Hartmannlight/ZebraTamer.git
```

Danach den Ordner `printer-only-stack` aus diesem Workspace daneben kopieren.

## Konfiguration und Start

Voraussetzung ist Docker mit Compose v2.

```powershell
cd printer-only-stack
Copy-Item .env.example .env
docker compose config
docker compose up --build -d
docker compose ps
```

Danach sind erreichbar:

- PrintHub Studio: `http://localhost:8088`
- PrintHub/OpenAPI: `http://localhost:8001/docs`
- Virtueller Zebra: `http://localhost:9191`

## Schnittstellen: Was kann wie angesprochen werden?

Der Compose-Stack bindet Studio, API und Emulator-Webansicht standardmäßig nur
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
| RAW-TCP/JetDirect Port 9100 | PrintHub → Drucker | Ja | Drucker mit `connection.protocol: raw9100` werden auf dem konfigurierten Host/Port angesprochen, üblicherweise `9100`. PrintHub selbst lauscht **nicht** auf Port 9100. |
| Virtueller Zebra auf Port 9100 | nur im Docker-Netz: `virtual-zebra:9100` | Ja, intern | In der mitgelieferten Compose-Datei wird 9100 nicht auf den Host veröffentlicht; von außen wird über die PrintHub-API gedruckt. |
| CUPS/IPP-Queue als PrintHub-Ziel | – | Nein | Derzeit gibt es keinen `cups`-/`ipp`-Backend-Treiber. Ein Netzwerkdrucker kann unabhängig direkt in CUPS und parallel in PrintHub als `raw9100` eingerichtet werden; PrintHub sendet jedoch nicht über die CUPS-Queue. |
| PrintHub selbst zu CUPS hinzufügen | – | Nein | PrintHub stellt weder IPP noch eine CUPS-kompatible Port-9100-Queue bereit. |

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

Der virtuelle Drucker wird beim ersten Start aus `config/printers.yml` direkt
per `raw9100` in PrintHub registriert. Eine separate ZebraTamer-API wird nur für
reale Drucker benötigt. Die YAML-Datei ist danach kein Laufzeitspeicher mehr.

## Zentrale Druckerverwaltung und Migration

PrintHub verwaltet Drucker in `/data/printers.sqlite3` im bestehenden
`printhub_data`-Volume. Es wird kein zusätzlicher Datenbankdienst benötigt.

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
docker compose logs -f printhub studio virtual-zebra
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
- `ZPLGRID_ENABLE_LABELARY_*`: nur für PNG-Vorschauen. Für das eigentliche
  Erzeugen und Versenden von ZPL nicht erforderlich.
- `TZ`: Zeitzone für zeitabhängige Template-Makros.

In dieser Konfiguration existieren bewusst weder `DATABASE_URL` noch
PostgreSQL-Zugangsdaten. Die SQLite-Registry liegt im vorhandenen Datenvolume.
