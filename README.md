# PrintHub ohne Thingdex-Inventar

Stand: 4. August 2026

Diese Variante betreibt nur die Etiketten- und Druckfunktionen. Sie enthält
keine Thingdex-API, keine Inventardatenbank und kein PostgreSQL.

## Benötigte Repositories und Branches

| Repository | Branch | Zweck | geprüfter Commit |
| --- | --- | --- | --- |
| [LabelArchitect](https://github.com/Hartmannlight/LabelArchitect) | `codex/printhub-studio-rewrite` | „PrintHub Studio“: Vorlagen, Designer, Quick Print und Druckerübersicht | `7c087ef` |
| [printhub-sdk](https://github.com/Hartmannlight/printhub-sdk) | `codex/printhub-studio-rewrite` | TypeScript-API-Client; Build-Abhängigkeit von PrintHub Studio | `577cbc1` |
| [PrintHub-ZPL-ll](https://github.com/Hartmannlight/PrintHub-ZPL-ll) | `codex/printhub-studio-rewrite` | API, Vorlagen, langlebige Druckjobs und Drucker-Registry | `2f15069` |
| [ZPL-II-Printer-Emulator](https://github.com/Hartmannlight/ZPL-II-Printer-Emulator) | `main` | Virtueller Zebra-Drucker mit Webansicht | `6afb22a` |
| [ZebraTamer](https://github.com/Hartmannlight/ZebraTamer) | `main` | Optionaler Agent für reale Zebra-Drucker | `ac14b75` |

Der Emulator-Branch `codex/printhub-studio-rewrite` zeigt aktuell auf denselben
Commit wie `main`. `main` ist deshalb hier die einfachere Wahl.

Nicht benötigt werden `Thingdex`, `Thingdex-Home-Inventory`, `ThingdexUI`,
`thingdex-sdk` und PostgreSQL. `LabelGallery` wird ebenfalls nicht benötigt:
dessen Operator-Workflow ist auf dem Rewrite-Branch in PrintHub Studio
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
git clone -b codex/printhub-studio-rewrite https://github.com/Hartmannlight/LabelArchitect.git
git clone -b codex/printhub-studio-rewrite https://github.com/Hartmannlight/printhub-sdk.git
git clone -b codex/printhub-studio-rewrite https://github.com/Hartmannlight/PrintHub-ZPL-ll.git
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

Der virtuelle Drucker ist direkt per `raw9100` in PrintHub registriert. Eine
separate ZebraTamer-API wird nur für reale Drucker benötigt.

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

Anschließend `/etc/zpl-agent/config.toml` prüfen. Wichtig sind eine dauerhafte
`agent_id`, der korrekte Character-Device-Pfad (zum Beispiel `/dev/usb/lp0`)
und ein erreichbarer REST-Port. Den optionalen `[thingdex]`-Abschnitt weglassen;
dann arbeitet ZebraTamer vollständig ohne Thingdex und ohne Datenbank.

Wenn PrintHub und ZebraTamer nicht zuverlässig per mDNS miteinander sprechen
können (typisch bei Docker oder getrennten Netzen), die Agenten explizit in
`.env` eintragen:

```dotenv
ZPLGRID_ZEBRA_TAMER_AGENTS=http://virtual-zebra:8080,http://192.168.1.50:8080
```

Mehrere URLs werden durch Kommas getrennt. PrintHub erzeugt die öffentliche
Drucker-ID als `<agent_id>--<printer_id>`. Diese ID kann als Standard gesetzt
werden:

```dotenv
ZPLGRID_DEFAULT_PRINTER_ID=werkstatt-pi--zebra-usb
```

Nach einer Änderung:

```powershell
docker compose up -d --force-recreate printhub studio
```

Kontrolle:

```powershell
curl.exe http://localhost:8001/v1/printers
```

Der virtuelle Drucker und alle explizit konfigurierten ZebraTamer-Geräte sollten
in der Antwort sowie in PrintHub Studio unter `/#/printers` erscheinen.

## Wichtige `.env`-Werte

- `ZPLGRID_ZEBRA_TAMER_AGENTS`: explizite Agent-URLs; für Docker der
  zuverlässigste Discovery-Weg.
- `ZPLGRID_DEFAULT_PRINTER_ID`: vorausgewählter Drucker in PrintHub Studio.
- `PRINTHUB_STUDIO_PORT`, `PRINTHUB_API_PORT`, `VIRTUAL_ZEBRA_WEB_PORT`:
  Host-Ports, falls die Defaults bereits belegt sind.
- `ZPLGRID_ENABLE_LABELARY_*`: nur für PNG-Vorschauen. Für das eigentliche
  Erzeugen und Versenden von ZPL nicht erforderlich.
- `TZ`: Zeitzone für zeitabhängige Template-Makros.

In dieser Konfiguration existieren bewusst weder `DATABASE_URL` noch
PostgreSQL-Zugangsdaten.
