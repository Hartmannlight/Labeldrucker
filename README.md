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
