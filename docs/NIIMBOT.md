# NIIMBOT B1 und Bild-Designer

## Erweiterung

- Studio: **Image designer** (`/#/image-designer`) mit Text, PNG/JPEG, Rechtecken,
  Verschieben, millimetergenauen Eigenschaften, Undo und monochromer Vorschau.
- Entwürfe als JSON speichern/laden, Druckbild als PNG exportieren. Der letzte
  Entwurf bleibt zusätzlich im lokalen Browser gespeichert. Die Entwürfe sind
  nicht Teil der bisherigen serverseitigen ZPL-Vorlagenbibliothek.
  Ein Entwurf darf einschließlich eingebetteter Bilder höchstens 20 MB als
  UTF-8-JSON belegen; Bearbeitung, Export und Import verwenden dasselbe Limit.
  Browser-Speicher kann früher voll sein; dann den Entwurf als Datei sichern.
- Direkter Druck über die bestehende PrintHub-Raster-API. Für diese Entwürfe
  werden weder ZPL II noch Labelary benötigt. Auch Rasterdruck auf Zebra bleibt
  möglich; die Umwandlung in das Geräteformat übernimmt dessen Druckdienst.
- Eigenständiger Dienst unter `services/niimbot`: B1 mit 203 dpi und maximal
  384 Druckpunkten Breite (48 mm nutzbare Breite). **B1 Pro ist ein anderes Modell
  und wird abgewiesen.** Keine behauptete Unterstützung weiterer NIIMBOT-Modelle.
- USB-Serial und Bluetooth LE; Bluetooth Classic/RFCOMM ist nicht implementiert.

## Windows oder nativer Linux-Host

Python 3.11 oder neuer. Auf dem Rechner installieren, an dem der Drucker hängt:

```powershell
python -m venv .venv-niimbot
.venv-niimbot/Scripts/python.exe -m pip install ./services/niimbot
.venv-niimbot/Scripts/python.exe -m serial.tools.list_ports -v
```

Ein eigenes langes Token erzeugen und für diesen Dienst aufbewahren. Beispiel
für PowerShell, **COM5 durch den tatsächlich gefundenen B1-Port ersetzen**:

```powershell
$env:NIIMBOT_TOKEN = (python -c "import secrets; print(secrets.token_hex(32))")
$env:NIIMBOT_ADDRESS = 'COM5'
$env:NIIMBOT_TRANSPORT = 'serial'
$env:NIIMBOT_DATA_DIR = "$PWD/niimbot-data"
$env:NIIMBOT_WIDTH_MM = '40'
$env:NIIMBOT_HEIGHT_MM = '30'
.venv-niimbot/Scripts/python.exe -m uvicorn niimbot_service.app:create_app --factory --host 127.0.0.1 --port 8083 --workers 1
```

Linux: entsprechend `.venv-niimbot/bin/python` und `export NAME=value`
verwenden; Port bevorzugt `/dev/serial/by-id/...`, Benutzer mit Zugriffsrecht
auf das serielle Gerät. Es gibt keine automatische Wahl beliebiger COM-Ports.

Für BLE `NIIMBOT_TRANSPORT=ble` und `NIIMBOT_ADDRESS` auf die Bluetooth-Adresse
des B1 setzen. Mit `python -m bleak` aus derselben Umgebung lassen sich Geräte
finden. Bluetooth muss auf dem Host verfügbar sein (Linux: BlueZ/D-Bus).
Die NIIMBOT-App vorher vom Drucker trennen. BLE auf einem nativen Host ist der
vorgesehene Weg; der USB-Compose-Zusatz reicht keinen Bluetooth-Adapter durch.

In Studio unter **Printers** mit dem PrintHub-Admin-Token entsperren und den
Druckdienst mit URL und eigenem NIIMBOT-Token hinzufügen. Die URL muss **aus
PrintHub heraus** erreichbar sein. Für ein natives PrintHub auf demselben Host:
`http://127.0.0.1:8083`. Für Docker Desktop auf Windows:
`http://host.docker.internal:8083`; hierfür den Dienst auf einer für Docker
erreichbaren Host-Adresse binden (z. B. `--host 0.0.0.0`) und die Firewall auf
das benötigte Netz begrenzen. Auf getrennten Hosts die entsprechende Host-IP
verwenden. Das Loopback-Beispiel oben ist absichtlich nur lokal erreichbar.

Alternativ zum Inline-Token wird `NIIMBOT_TOKEN_FILE` unterstützt (nicht beides).
`NIIMBOT_SERVICE_ID` bleibt über Neustarts stabil. Für weitere Geräte eine eigene
Dienstinstanz mit eigenem Datenverzeichnis, Port, Service-ID und Token verwenden.
Ein OS-Lock verhindert mehrere Worker auf demselben Datenverzeichnis; denselben
physischen Drucker nicht in mehreren Instanzen konfigurieren.

## Linux mit Docker Compose und USB

Die neuen Studio-/PrintHub-Änderungen lokal bauen; vorhandene veröffentlichte
Images enthalten diese Erweiterung noch nicht. Beispiel unter Linux:

```bash
export NIIMBOT_USB_DEVICE=/dev/serial/by-id/DEIN-B1-GERAET
export NIIMBOT_DEVICE_GID=$(stat -Lc '%g' "$NIIMBOT_USB_DEVICE")
export NIIMBOT_WIDTH_MM=40
export NIIMBOT_HEIGHT_MM=30
docker compose -f compose.yaml -f compose.niimbot-usb.yaml up -d --build
```

Der Zusatz erzeugt ein separates Token, hängt den B1 ausschließlich an den
NIIMBOT-Dienst und registriert diesen automatisch bei PrintHub. Bestehende
Zebra-Drucker bleiben verfügbar. Kein privilegierter Container erforderlich.
Die Daten liegen im Volume `niimbot_data`. Bei Backup den Dienst stoppen und
das gesamte Volume sichern (SQLite inklusive WAL-Dateien).

Windows-Docker-Desktop reicht COM-Ports nicht wie Linux-Geräte durch; dort den
nativen Dienst oben verwenden. Bei Kombination mit anderen Compose-Zusätzen
deren `PRINTHUB_ADDITIONAL_PRINT_SERVICES`-Listen zu einer Liste zusammenführen.

## Etiketten und erster Druck

1. Geladene Etikettenbreite quer zum Druckkopf und Länge in Vorschubrichtung
   konfigurieren. Breite höchstens 48 mm; die Papierbreite kann größer als die
   nutzbare Druckbreite sein. Die B1-Auflösung bleibt 203 dpi.
2. Optional `NIIMBOT_DENSITY=1..5` (Standard 3) und
   `NIIMBOT_LABEL_TYPE=1..3` (1: Lücke, 2: Schwarzmarke, 3: Endlos) setzen.
3. Nach Medienwechsel Maße anpassen und den Dienst neu starten. Eine geänderte
   Medienrevision hält bereits wartende Aufträge an, statt sie falsch zu drucken.
4. **Image designer** öffnen, B1 auswählen, **Use loaded label size** anklicken,
   Inhalt gestalten und zunächst eine Kopie drucken. Aktuellen Zustand unter
   **Print jobs** prüfen. Abweichende Etikettengrößen werden zur Prüfung gehalten.

Maße, Etikettentyp und Farbe stammen aus der Konfiguration, nicht aus RFID.
Bereits vorhandene ZPL-Vorlagen benötigen für den B1 weiterhin einen
konfigurierten ZPL-Renderer. Der neue Bild-Designer umgeht diesen Weg vollständig.

## Druckzustände und Fehler

Aufträge werden mitsamt Bildern atomar in SQLite gespeichert und FIFO
verarbeitet. Gleicher Idempotenzschlüssel und gleicher Inhalt ergeben denselben
Auftrag; geänderter Inhalt ergibt HTTP 409. A/B mit zwei Kopien druckt A/B/A/B.
PNG-Raster werden vor dem Queueing auf Größe, DPI, Hash, Polarität und Padding
geprüft. Pro Auftrag maximal 25 verschiedene Seiten und 999 Etiketten insgesamt;
PrintHub hat zusätzlich sein eigenes Standardlimit.

`completed_observed` setzt bestätigte Gerätebefehle, den auf die erwartete
Seitenzahl gestiegenen Druckzähler und den Abschluss des Druckauftrags voraus.
Kommunikationsfehler nach Druckbeginn oder Neustart während einer Übertragung
führen zu `outcome_unknown`. Es gibt keine automatischen physischen Wiederholungen.
Vor explizitem Nachdruck das tatsächliche Etikett prüfen. Ein Fehler vor
Druckbeginn wird als `failed` gespeichert. Wartende/gehaltene Aufträge sind
abbrechbar; laufende Aufträge nicht.

Bei einem bestätigten Fehlschlag vor dem Druckbeginn startet **Retry** in
PrintHub einen neuen Zustellversuch mit eigenem Schlüssel und denselben
gespeicherten Druckdaten. Alte Zustellversuche bleiben intern nachvollziehbar.
Ohne Service-Antwort wird der bestehende Schlüssel beibehalten, um einen
möglicherweise bereits angenommenen Auftrag nicht doppelt auszuführen.

Der Bild-Designer bewahrt bei verlorener API-Antwort den unveränderten Auftrag
und Schlüssel im Browser-Tab auf. **Resolve same request** löst diesen Auftrag
erneut auf, statt einen neuen Druckauftrag zu erzeugen.

## Validierung und Grenzen

Automatische Tests prüfen Paketvektoren, fragmentierte Antworten, Checksummen,
Modellprüfung, B1-Startfolge, Zeilenkodierung, Kopierreihenfolge, Bestätigungen,
Timeouts, SQLite-Neustartverhalten, Idempotenz, API-Schemata und Rastervalidierung.
Ein Hardware-Test mit dem konkreten B1/Firmwarestand bleibt erforderlich; Tests
mit einem simulierten Protokollpartner sind kein Nachweis eines realen Ausdrucks.
Das Projekt verändert weder Firmware noch RFID-Daten.

## Protokollquellen

Die Implementierung wurde aus den dokumentierten Protokollinformationen eigenständig
geschrieben; es wurde kein fremder Treiber eingebunden oder dessen Quellcode kopiert.

- [niimbluelib B1PrintTask](https://github.com/MultiMote/niimbluelib/blob/main/src/print_tasks/B1PrintTask.ts): B1-spezifische Auftragsfolge.
- [niimbot-web-bluetooth Protokoll](https://github.com/iscarelli/niimbot-web-bluetooth/blob/main/docs/protocol-v4.md): Handshake, Modell-ID, Rasterformat, BLE und Bestätigungen.
- [niimprint](https://github.com/AndBondStyle/niimprint): USB-Serial-Verbindung mit 115200 Baud.

Referenzstand: 22.09.2026. Weitere Modelle erst mit eigenem Profil,
Protokolltests und Hardware-Abnahme freigeben.
