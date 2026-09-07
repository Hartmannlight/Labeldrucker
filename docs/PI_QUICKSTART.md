# Raspberry-Pi-Schnellstart

Dieser Weg installiert PrintHub auf einem 64-Bit Raspberry Pi OS oder Debian
mit einem direkt per USB angeschlossenen Etikettendrucker. Er verwendet nur
geprüfte ARM64-/AMD64-Images, SQLite und keine Thingdex- oder Emulator-Dienste.

## Voraussetzungen

- 64-Bit Raspberry Pi OS oder Debian
- Docker Engine mit Compose v2
- Python 3.11 oder neuer
- `avahi-daemon` für genau eine Druckerankündigung im LAN
- angeschlossener USB-Drucker

```sh
sudo apt update
sudo apt install -y avahi-daemon git
git clone --recurse-submodules https://github.com/Hartmannlight/Labeldrucker.git
cd Labeldrucker
```

## 1. Drucker erkennen und Host einrichten

```sh
sudo python3 scripts/pi_quickstart.py --install-host
```

Der Assistent sucht nur USB-Geräte mit Printer-Class-Interface und zeigt
Modell, USB-IDs und Seriennummer an. Bei mehreren Geräten nennt er die
möglichen Nummern; die Auswahl erfolgt dann etwa mit `--device 2`.

Er erzeugt `deploy/quickstart.env` mit zufälligen Zugängen,
`deploy/state/print-agent.toml` mit `usb_bulk` und stabiler
VID/PID/Seriennummer, eine enge udev-Regel sowie genau eine Avahi-Ankündigung
auf dem Host. Zugangsdaten sind von Git ausgeschlossen. Der Container-eigene
DNS-SD-Dienst bleibt deaktiviert. Nach erneutem Anstecken darf sich die
USB-Busnummer ändern; Identität und Rechte werden ohne Compose-Änderung
wiederhergestellt.

## 2. Images laden und Stack starten

```sh
docker compose \
  --env-file deploy/quickstart.images.env \
  --env-file deploy/quickstart.env \
  -f deploy/compose.quickstart.yaml \
  --profile usb-agent --profile ipp pull

docker compose \
  --env-file deploy/quickstart.images.env \
  --env-file deploy/quickstart.env \
  -f deploy/compose.quickstart.yaml \
  --profile usb-agent --profile ipp up -d

docker compose \
  --env-file deploy/quickstart.images.env \
  --env-file deploy/quickstart.env \
  -f deploy/compose.quickstart.yaml \
  --profile usb-agent --profile ipp ps
```

Es wird nichts lokal gebaut. `deploy/quickstart.images.env` bindet jede
Komponente an einen exakten Multi-Arch-Digest. Ein Update ist damit eine
bewusste Änderung und kein unerwartetes `latest`-Update.

## 3. Ersteinrichtung abschließen

1. Für die einmalige Medienkonfiguration einen geschützten SSH-Tunnel öffnen:
   `ssh -L 8090:127.0.0.1:8090 pi@PI-NAME.local`. Danach den PrintAgent lokal
   unter `http://127.0.0.1:8090/ui/` öffnen und Medium sowie Druckverfahren
   eintragen. Sein zufälliges Admin-Token steht auf dem Pi in
   `deploy/state/print-agent.toml`; der Admin-Port wird nicht im LAN exponiert.
2. Studio unter `http://PI-NAME.local:8088` öffnen.
3. Fleet Console unter `http://PI-NAME.local:8089` öffnen. Das zufällige
   Admin-Token steht lokal in `deploy/quickstart.env`.
4. Den entdeckten Agent-Drucker registrieren und Medium, DPI sowie
   Thermodirekt/Thermotransfer prüfen. Die Fleet-ID muss dem Wert
   `PRINTHUB_IPP_PRINTER_ID` entsprechen; andernfalls diesen Wert ändern und
   nur `ipp-gateway` neu erstellen.
5. Erst einen Verbindungscheck, dann ein markiertes Testetikett senden.
   `transport_accepted` bedeutet nur, dass USB die Bytes angenommen hat. Das
   sichtbar korrekte Etikett bestätigt der Bediener.

Der nicht druckende Abschlusscheck fasst die technischen Schritte zusammen:

```sh
sudo python3 scripts/pi_quickstart.py --check
```

Er unterscheidet USB-Erkennung, Agent, Medium, Geräteprobe, Fleet-Registrierung
und IPP-Erreichbarkeit. Das sichtbare Testetikett bleibt ausdrücklich ein
separater manueller Nachweis.

Die IPP-Freigabe heißt dauerhaft **PrintHub Label Printer**. Abmessungen stehen
nicht im Namen, sondern in den IPP-Medienattributen. Nach einem Medienwechsel
behält ein Client daher dieselbe Queue.

`PRINTHUB_MAX_LABELS_PER_JOB=25` in `deploy/quickstart.env` schützt vor
versehentlichen Großaufträgen. PrintHub hält mehrseitige Aufträge vor der
Gerätequeue an und zählt dabei Seiten mal Kopien. Im Studio zeigt der Job die
beiden Zahlen und lässt sich erst nach einer ausdrücklichen Bestätigung
freigeben; IPP-Aufträge können die Grenze nicht selbst umgehen.

## Fehlerdiagnose

```sh
docker compose \
  --env-file deploy/quickstart.images.env \
  --env-file deploy/quickstart.env \
  -f deploy/compose.quickstart.yaml \
  --profile usb-agent --profile ipp logs --tail=200
```

- Kein USB-Drucker erkannt: `lsusb` und `/sys/bus/usb/devices` prüfen.
- Agent sieht das Gerät nicht: udev-Regel mit
  `sudo udevadm control --reload-rules && sudo udevadm trigger` neu laden.
- Zwei Drucker im Netzwerk: frühere manuelle Avahi-/CUPS-Ankündigung entfernen;
  PrintHub selbst kündigt in diesem Profil absichtlich nicht an.
- IPP sichtbar, aber nicht erreichbar: Port `8631/tcp` in der Host-Firewall
  freigeben und prüfen, ob `PI-NAME.local` auf den Pi zeigt.

Automatische Medienvermessung, dynamische IPP-Medien und der geführte
Abschlussdialog werden schrittweise auf diesem Profil aufgebaut. Bis dahin
sind Medium und sichtbares Ergebnis bewusst als Bedienerprüfung dokumentiert.
