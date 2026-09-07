# PrintHub einrichten

Dieser Guide ist der kürzeste unterstützte Weg vom Git-Checkout zu einem
laufenden PrintHub. Alle Komponenten werden aus diesem Repository orchestriert.
Die unter `components/` eingebundenen Git-Submodule bleiben eigenständige
Repositories, werden beim Checkout aber auf exakt geprüfte Versionen gesetzt.

## 1. Den passenden Betriebsfall wählen

| Ziel | Compose-Dateien | Zusätzliche Hardwarekonfiguration |
| --- | --- | --- |
| Lokal testen, ohne echten Drucker | `compose.yaml` | keine |
| Zebra über Ethernet/WLAN oder RS232-Bridge | `compose.yaml` | Drucker in Fleet Console registrieren |
| Zebra per USB am Docker-Host | `compose.yaml`, Profil `usb-agent` | USB-Gerät und PrintAgent konfigurieren |
| Stabiler Unternehmensbetrieb mit veröffentlichten Images | `deploy/compose.standalone.yaml` | Secrets, Image-Digests und Druckerregistry |

Ein Netzwerkdrucker braucht keinen eigenen Container. PrinterFleet verbindet
sich direkt zu seinem RAW-TCP-Port, bei Zebra üblicherweise Port 9100. Der
PrintAgent ist nur für Geräte notwendig, auf die der zentrale Server nicht
direkt zugreifen kann, beispielsweise USB, Bluetooth oder lokales RS232.

## 2. Lokaler Schnellstart

Voraussetzungen sind Git, Docker und Docker Compose v2.

```powershell
git clone --recurse-submodules https://github.com/Hartmannlight/Labeldrucker.git
Set-Location Labeldrucker
Copy-Item .env.example .env
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Unter Linux/macOS lautet der Kopierbefehl `cp .env.example .env`. Sobald alle
Healthchecks grün sind, stehen diese Oberflächen bereit:

- PrintHub Studio: <http://localhost:8088>
- PrinterFleet Console: <http://localhost:8089>
- PrintHub API/OpenAPI: <http://localhost:8001/docs>
- virtueller Zebra: <http://localhost:9191>
- IPP-Drucker: `ipp://localhost:8631/ipp/print`

Die Entwicklungsanmeldung für Fleet Console ist
`development-fleet-admin-token`. Sie ist ausschließlich für den lokalen
Schnellstart gedacht.

Der erste Testdruck geht an `virtual-zebra` und erscheint in dessen
Weboberfläche. Damit lässt sich die gesamte Kette aus Studio, PrintHub,
PrinterFleet und Treiber ohne Hardware prüfen.

## 3. Was in `.env` angepasst wird

`.env.example` ist vollständig kommentiert. Die Kopie `.env` wird von Git
ignoriert. Für einen normalen lokalen Start müssen keine Werte geändert werden.

| Variable | Standard | Ändern, wenn ... |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `printhub-only` | mehrere getrennte Instanzen auf demselben Host laufen |
| `PRINTHUB_STUDIO_PORT` | `8088` | der Studio-Port belegt ist |
| `PRINTER_FLEET_CONSOLE_PORT` | `8089` | der Fleet-Console-Port belegt ist |
| `PRINTHUB_API_PORT` | `8001` | der API-Port belegt ist |
| `VIRTUAL_ZEBRA_WEB_PORT` | `9191` | der Emulator-Webport belegt ist |
| `PRINTHUB_IPP_PORT` | `8631` | der IPP-Port belegt ist |
| Variablen mit Suffix `_BIND` | `127.0.0.1` | ein Dienst bewusst aus dem LAN erreichbar sein soll |
| `PRINTHUB_IPP_HOSTNAME` | `localhost` | IPP-Clients einen anderen DNS-Namen verwenden |
| `PRINTHUB_IPP_PRINTER_ID` | `virtual-zebra` | IPP an einen registrierten echten Drucker senden soll |
| `PRINTHUB_IPP_MISMATCH_POLICY` | `hold` | abweichende Seiten ausdrücklich automatisch skaliert werden sollen |
| `PRINTER_FLEET_AGENT_URLS` | leer | externe PrintAgents ohne mDNS fest eingetragen werden |

Nur Host-Ports werden geändert. Die Container-Ports und internen Dienstnamen
bleiben unverändert, weil sie Teil des internen Servicevertrags sind.

Für LAN-Zugriff sollten nur die wirklich benötigten Bind-Adressen auf
`0.0.0.0` gesetzt werden. IPP benötigt zusätzlich einen vom Client auflösbaren
`PRINTHUB_IPP_HOSTNAME`. Entwicklungs-Tokens, die ungeschützte Fleet Console
und das automatisch erzeugte IPP-Zertifikat sind kein geeigneter
Unternehmens-Ingress.

## 4. Komponenten und Ports

| Komponente | Aufgabe | Host-Port im Schnellstart | Muss aus dem LAN erreichbar sein? |
| --- | --- | --- | --- |
| PrintHub Studio | Vorlagen, Designer, Vorschau, Druckfreigabe | `8088/tcp` | nur für Bedienplätze |
| PrintHub API | logische Jobs, Dokumente, Vorschauen | `8001/tcp` | nur für integrierende Anwendungen |
| PrinterFleet Console | physische Drucker, Status, Wartung | `8089/tcp` | nur für Administratoren |
| PrinterFleet API | Katalog und dauerhafte Zustellqueue | keiner, nur Docker-Netz | nein |
| IPP Gateway | CUPS-/Windows-/Chrome-Druckereingang | `8631/tcp` | ja, wenn Clients auf anderen Rechnern drucken |
| virtueller Zebra | Entwicklungs-Webansicht | `9191/tcp` | nein |
| virtueller Zebra RAW | emulierter Druckertransport | keiner; intern `9100/tcp` | nein |
| PrintAgent | Edge-Zugriff auf USB/lokale Geräte | keiner; intern `8080/tcp` | nur für PrinterFleet |
| echter Zebra RAW | physischer Druckertransport | normalerweise `9100/tcp` am Drucker | nur für PrinterFleet |

PostgreSQL wird nur im Produktionsprofil verwendet und nicht auf dem Host
veröffentlicht. Das Entwicklungsprofil speichert Fleet in einem eigenen
SQLite-Volume.

## 5. Ethernet-, WLAN- oder RS232-Bridge-Drucker

1. Den Grundstack wie oben starten.
2. Fleet Console auf <http://localhost:8089> öffnen und anmelden.
3. Einen Drucker anlegen. Für Zebra Ethernet/WLAN wird
   `connection.protocol = raw_tcp`, die IP beziehungsweise der DNS-Name des
   Druckers und normalerweise Port `9100` verwendet.
4. Für eine transparente RS232-zu-Ethernet-Bridge
   `connection.protocol = serial_over_tcp` und deren tatsächlichen TCP-Port
   verwenden. Baudrate und serielle Parameter werden an der Bridge gepflegt.
5. Medium, DPI und Treiber (`zpl`) eintragen, Verbindung prüfen und anschließend
   einen markierten Testjob senden.
6. Soll Chrome/CUPS diesen Drucker verwenden,
   `PRINTHUB_IPP_PRINTER_ID` in `.env` auf seine Fleet-ID setzen und
   `docker compose restart ipp-gateway` ausführen.

Die zentrale Fleet-Instanz verwaltet beliebig viele Netzwerkdrucker. Für jeden
Drucker existiert eine unabhängige, geordnete Queue; ein nicht erreichbarer
Drucker blockiert die anderen nicht.

## 6. USB-Drucker am Docker-Host

USB bleibt bewusst in einem separaten Edge-Prozess. Dadurch erhalten PrintHub
und PrinterFleet niemals direkten Gerätezugriff.

1. Vorlage kopieren; die Zieldatei ist bereits durch `.gitignore` geschützt:

   ```powershell
   Copy-Item deploy/secrets/print-agent-usb.toml.example `
     deploy/secrets/print-agent-usb.toml
   ```

2. In `deploy/secrets/print-agent-usb.toml` mindestens `agent_id`,
   `admin_token`, `id`, Modell, USB Vendor-/Product-ID und Seriennummer
   eintragen. Vendor und Product werden dort dezimal angegeben.
3. Das konkrete Linux-Gerät ermitteln, beispielsweise mit `lsusb`; unter
   Docker Desktop für Windows muss es zuvor mittels `usbipd` an WSL
   durchgereicht werden. Der frisch erzeugte Geräteknoten gehört zunächst
   häufig `root:root` mit Modus `0600`. Der non-root-Agent mit GID `999` benötigt
   deshalb nach jedem Attach gezielt Gruppenrechte auf genau diesem Knoten:

   ```powershell
   usbipd bind --busid BUS-ID                 # einmalig als Administrator
   usbipd attach --wsl --busid BUS-ID
   $usbDevice = "/dev/bus/usb/001/002"        # nach jedem Attach neu prüfen
   wsl -d docker-desktop -u root -- chown 0:999 $usbDevice
   wsl -d docker-desktop -u root -- chmod 0660 $usbDevice
   ```

   `usbipd list` zeigt die Windows-BUS-ID. Bus- und Gerätenummer des
   Linux-Knotens können sich nach Abziehen oder Neustart ändern. Keinesfalls
   pauschal den ganzen USB-Bus freigeben oder den Agent privilegiert starten.
4. In `.env` setzen:

   ```dotenv
   PRINT_AGENT_USB_DEVICE=/dev/bus/usb/001/002
   PRINT_AGENT_CONFIG_PATH=./deploy/secrets/print-agent-usb.toml
   PRINTER_FLEET_AGENT_URLS=http://print-agent:8080
   ```

5. Grundstack mit aktiviertem USB-Profil starten:

   ```powershell
   docker compose --profile usb-agent up --build -d
   docker compose --profile usb-agent ps
   ```

   Das Profil besitzt absichtlich nur nicht funktionsfähige Platzhalter als
   Defaults. Ohne einen realen `PRINT_AGENT_USB_DEVICE` und eine kopierte,
   ausgefüllte TOML darf der USB-Start fehlschlagen; der normale Stack ohne das
   Profil bleibt davon unabhängig startbar.

6. Den erkannten Agent-Drucker in Fleet Console registrieren. Danach dessen
   öffentliche Fleet-ID als `PRINTHUB_IPP_PRINTER_ID` verwenden und das
   IPP-Gateway neu starten.

Nach einem USB-Neuanschluss den aktuellen `/dev/bus/usb/BBB/DDD`-Knoten und
dessen Rechte immer erneut prüfen. Hat sich der Pfad geändert, zusätzlich
`PRINT_AGENT_USB_DEVICE` korrigieren und `print-agent` neu erstellen.

## 7. IPP bei CUPS oder Windows hinzufügen

Linux/CUPS:

```sh
sudo lpadmin -p printhub-label -E \
  -v ipp://localhost:8631/ipp/print \
  -m everywhere
lpstat -p printhub-label
```

Windows 11, in einer administrativen PowerShell:

```powershell
.\scripts\install_windows_ipp_printer.ps1
.\scripts\install_windows_ipp_printer.ps1 -CheckOnly
```

Chrome verwendet anschließend die Systemqueue. Dithering wird nicht über
einen eigenen Chrome-Schalter gewählt, sondern im Systemdialog mit
`Strg+Umschalt+P` über `Druckqualität`: `Entwurf` ist harte Schwarz-Weiß-
Schwelle, `Hoch` ist Fotoausgabe mit Floyd-Steinberg-Dithering und `Normal`
lässt PrintHub automatisch entscheiden.

## 8. Produktionsbetrieb

Der Schnellstart baut lokale Submodule und verwendet absichtlich einfache
Entwicklungszugänge. Für einen stabilen Unternehmensbetrieb dient
`deploy/compose.standalone.yaml`. Dieses Profil baut keinen Quellcode, sondern
akzeptiert ausschließlich digest-fixierte Images und dateibasierte Secrets.

Die Schritte sind:

1. `deploy/.env.production.example` nach `deploy/.env.production` kopieren.
2. Alle Image-Platzhalter durch Digests aus einer veröffentlichten
   Compatibility Release ersetzen.
3. Die Beispiele unter `deploy/secrets/` in Dateien ohne `.example` kopieren,
   zufällige Tokens einsetzen und die Pfade in der Environment-Datei setzen.
4. Konfiguration validieren und starten:

   ```powershell
   python scripts/validate_release_env.py deploy/.env.production `
     --manifest PFAD_ZU_COMPATIBILITY_JSON
   docker compose --env-file deploy/.env.production `
     -f deploy/compose.standalone.yaml `
     --profile studio --profile fleet-console --profile ipp up -d
   ```

5. Nur wenn ein USB-Gerät genau an diesem Host hängt, zusätzlich
   `-f deploy/compose.print-agent.yaml` verwenden.

Die vollständigen Release-, Backup-, Secret- und Thingdex-Regeln stehen in
[`architecture/DEPLOYMENT_PROFILES.md`](architecture/DEPLOYMENT_PROFILES.md).

## 9. Betrieb prüfen und stoppen

```powershell
docker compose ps
docker compose logs --tail 100 printhub printer-fleet ipp-gateway
Invoke-RestMethod http://localhost:8001/health
```

Normal stoppen, ohne Daten zu löschen:

```powershell
docker compose down
```

Named Volumes enthalten Vorlagen, Jobs, Fleet-Registry und TLS-Identität. Ein
`docker compose down -v` löscht diese Daten und gehört nicht in den normalen
Betriebsablauf.
