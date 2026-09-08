# PrintHub ohne Fleet: Zielbild und Arbeitspakete

Stand: 2026-09-08. Status: Umsetzungsplan; kein Arbeitspaket ist durch die Erstellung dieses Dokuments erledigt.

Dieses Dokument ist die eigenständige Arbeitsgrundlage für den Umbau des Labeldrucker-Projekts. Es beschreibt Produktziel, verbindliche Verantwortlichkeiten, technische Verträge, Abhängigkeiten und Abnahme. Vorwissen aus einem Chat ist nicht erforderlich. Die Arbeitspakete umfassen die Umsetzung bis zu einem installierbaren und benutzbaren Produkt, einschließlich Datenübernahme, Images, Einrichtung, IPP und Entfernung von PrinterFleet.

## 1. Anlass und Produktziel

Der bisherige Stack trennt PrintHub, PrinterFleet, Fleet Console und ZebraTamer. PrintHub bereitet Dokumente vor. Fleet verwaltet Drucker und Zustellung und spricht Netzwerk-Zebras direkt an. ZebraTamer, teilweise als PrintAgent bezeichnet, betreut lokal angeschlossene Geräte. Dadurch verteilen sich Zebra-Protokoll, Konfiguration und Statuslogik auf mehrere Produkte.

Diese Trennung wird aufgehoben. ZebraTamer wird der vollständige Druckerdienst für Zebra-Geräte, unabhängig von USB oder Ethernet. PrintHub arbeitet direkt mit einer oder mehreren Druckerdienst-Instanzen. Später kann ein eigener Niimbot-Dienst denselben gemeinsamen Vertrag implementieren. PrinterFleet und Fleet Console werden vollständig aus dem Produkt entfernt.

Das fertige Produkt muss ohne Thingdex benutzbar sein:

- Ein Anwender lädt das Release-Paket und startet im Wesentlichen mit `docker compose up -d`.
- Studio, PrintHub, ZebraTamer und IPP starten mit leeren Datenverzeichnissen, auch ohne eingerichteten Drucker.
- Eine verständliche Oberfläche führt durch Druckeranlage, Materialangaben, Testdruck und optionale IPP-Freigabe.
- Ethernet-Zebras benötigen keinen Pi am Drucker. Die zentrale ZebraTamer-Instanz spricht ihre IP und ihren Port an.
- USB-Zebras können am Stack-Host oder an einem entfernten Pi mit ZebraTamer angeschlossen sein.
- Templates, Bilder und Dokumente können über Oberfläche oder API gedruckt werden; freigegebene Drucker sind zusätzlich über IPP verwendbar.
- Neustarts, Offline-Geräte und verlorene Antworten führen weder zu still verloren gegangenen Jobs noch zu automatischen Doppeldrucken.
- AMD64 und ARM64 erhalten fertige Container-Images. Ein älterer Pi 2 kann weiterhin als ARMv7-ZebraTamer-Geräteserver dienen.
- Eine zweite, nur Rasterbilder akzeptierende Gerätefamilie lässt sich ohne Zebra-Sonderfälle in PrintHub anbinden.

### Nicht Bestandteil dieses Refactorings

- Implementierung oder Reverse Engineering der echten Niimbot-B1-Bluetooth-Kommunikation.
- Vollständiger Stack für 32-Bit-Pis; ARMv7 betrifft zunächst den bestehenden ZebraTamer-Binary-Pfad.
- Fertiges SD-Karten-/Betriebssystem-Image für Pis. Gemeint sind hier Container-Images und der kleine native Geräteserver.
- Enterprise-Funktionen wie Mandanten-/Standortverwaltung, PostgreSQL-Cluster, verteilte Worker oder automatische Drucker-Pools.
- Ein eigener ZPL-Renderer als Ersatz für Labelary.
- Funktionsänderungen an Thingdex außerhalb der Entkopplung und Erhaltung seiner öffentlichen PrintHub-Anbindung.

## 2. Verbindliche Zielarchitektur

```text
Browser / LabelArchitect Studio -----------------------+
Externe API-Nutzer, optional Thingdex ------------------+--> PrintHub
Betriebssystem-Druckdialog --> IPP-Gateway -------------+       |
                                                              +--> ZebraTamer auf dem Server
                                                              |      +--> Ethernet-Zebra:9100
                                                              |      +--> weiterer Ethernet-Zebra
                                                              |      +--> lokaler USB-Zebra
                                                              |
                                                              +--> ZebraTamer auf einem Pi
                                                              |      +--> dortiger USB-Zebra
                                                              |
                                                              +--> späterer Niimbot-Dienst
                                                                     +--> Bluetooth-Gerät
```

Ein Pfeil vom PrintHub zu einem Druckerdienst bezeichnet die gemeinsame HTTP-API. Die Verbindung vom Druckerdienst zur Hardware ist dessen Implementierungsdetail. Es entsteht kein neuer zentraler Fleet-Ersatzdienst.

| Bestandteil | Besitzt und verantwortet | Gehört nicht hinein |
| --- | --- | --- |
| PrintHub | Templates, aufgelöste Variablen, Quelldokumente, Layout, Rendering, Dithering, unveränderliche Druckartefakte, logische Aufträge, Druckerdienst-Verbindungen, öffentliche Druckerzuordnungen, aggregierte Statussicht | Zebra-/Niimbot-Geräteprotokoll, direkte TCP-/USB-/Bluetooth-Verbindungen zur Hardware, persistente Hardwarevorgaben |
| ZebraTamer | Zebra-Geräte, TCP-/USB-Endpunkte, Geräteprofile, reale Konfiguration, eingelegte Medien und Verbrauch, physische Warteschlangen, Status, Wartung, ZPL- und Rasterannahme | Templates, Labelary, Dokument-Layout, Niimbot-Treiber, standortübergreifendes Routing |
| Niimbot-Dienst, später | Niimbot-Geräte, Bluetooth, Gerätepakete, lokale Jobs, Fähigkeiten und Medien nach demselben allgemeinen Vertrag | ZPL-Konfiguration, Zebra-Abfragen, PrintHub-Templates |
| LabelArchitect / Studio | Gemeinsamer Einstieg für Gestaltung, Druck, Druckerauswahl, Einrichtung und Auftragsübersicht | Geräteprotokoll oder direkte Browserzugriffe auf USB/TCP/Bluetooth |
| IPP-Gateway | IPP-Endpunkte, Freigaben, IPP-Spool, Protokollübersetzung, Zuordnung zum PrintHub-Auftrag und Rückmeldung | Eigenes Rendering, Hardwarezugriff, zweite unabhängige physische Druckwarteschlange |
| Labeldrucker-Repository | Git-Submodule, getestete Komponentenstände, Release-Compose, Einrichtungs- und Betriebsdokumentation, Integrationstests | Eine zusätzliche PrinterFleet-Anwendung |

### Datenhoheit und Identität

1. Ein physischer Drucker hat genau einen zuständigen Druckerdienst. Druck, Wartung und Abfragen laufen durch dessen Koordinator.
2. Eine Druckerdienst-Instanz hat eine dauerhaft gespeicherte `service_id`. Zusammen mit ihrer lokalen `printer_id` ergibt sich die stabile Druckeridentität. Eine IP-/URL-Änderung ändert diese Identität nicht.
3. PrintHub speichert die Zuordnung seiner öffentlichen Drucker-ID zu dieser Identität. Bestehende öffentliche IDs bleiben bei der Migration erhalten.
4. PrintHub kennt Dienst-URL und Dienstzugang, aber keine Hardware-Endpunkte als eigene Registry. Der Einrichtungsdialog darf Hardwarewerte an die passende Verwaltungs-API weiterreichen; gespeichert und validiert werden sie im Druckerdienst.
5. Auflösung, Geräteoptionen, eingelegte Rolle und Medienrevision gehören zum Druckerdienst. PrintHub hält eine gekennzeichnete Lesekopie mit Herkunft und Zeitstempel sowie den Snapshot eines konkreten Auftrags.
6. Benutzerangaben, gemessene Werte und unbekannte Werte bleiben unterscheidbar. Fehlende Statusantworten dürfen nicht als leeres Papierfach oder sicher bereites Gerät interpretiert werden.
7. Pro Dienst-Datenverzeichnis wird zunächst genau eine schreibende Instanz unterstützt. Zweiter Prozessstart mit demselben Verzeichnis muss verhindert werden. Keine verteilten Leases erforderlich.
8. Derselbe Netzwerkdrucker darf nicht versehentlich als zwei aktive Ziele angelegt werden. Endpunkt-/Seriennummern-Abgleich unterstützt die Erkennung; die Software kann Fremdprogramme im LAN nicht global sperren.

### Repository- und Image-Entscheidung

- `Labeldrucker` bleibt das übergeordnete Repository mit Git-Submodulen.
- `PrintHub-ZPL-ll` bleibt zunächst der vorhandene Repository-Pfad für PrintHub. Eine kosmetische Repository-Umbenennung ist kein Abschlusskriterium.
- `LabelArchitect`, `ZebraTamer` und `printhub-sdk` bleiben eigene Komponenten.
- IPP-Code zieht in das PrintHub-Repository, zum Beispiel unter `ipp-gateway/`, und wird dort als **eigenes Image** gebaut und veröffentlicht. Dafür wird kein weiteres Repository angelegt.
- Die Spezifikation des gemeinsamen Druckerdienstvertrags wird versioniert im PrintHub-Repository gepflegt. Implementierungen anderer Sprachen übernehmen Spezifikation und Testfälle, keine Python-Laufzeitabhängigkeit.
- Der spätere Niimbot-Dienst erhält ein eigenes Repository/Image. In diesem Refactoring entsteht nur ein expliziter Testdienst für den Vertrag.
- Thingdex und Thingdex-Home-Inventory entfallen als notwendige Submodule/Build-Eingaben des Druckerprodukts. Bestehende Checkouts mit eigenen Änderungen dürfen dabei nicht gelöscht werden.
- Der Zebra-Emulator bleibt als optionale Entwicklungs-/Demo-Komponente erhalten.
- Die Anwender-Compose verwendet freigegebene Images. Lokale Builds mit Submodulen bekommen einen getrennten Entwicklungsweg.

## 3. Bestandsaufnahme und Einstiegspunkte

Die Pfade beziehen sich auf den am 2026-09-08 untersuchten Arbeitsstand. Vor einer Umsetzung sind sie gegen den dann aktuellen Stand zu prüfen. Bereits vorhandene Änderungen und vorgemerkte Löschungen anderer Arbeiten dürfen nicht überschrieben werden.

| Bereich | Vorhandene Implementierung | Bedeutung für den Umbau |
| --- | --- | --- |
| Stack | `compose.yaml`, `.env.example` | Baut derzeit überwiegend lokal, enthält Fleet/Fleet Console und Abhängigkeiten vom virtuellen Zebra |
| Alte Architektur | `docs/DESIGN.md` | Schreibt den direkten Fleet-Netzwerkpfad vor; wird beim endgültigen Schnitt entfernt |
| Zebra-Transport | `components/ZebraTamer/src/transport.rs`, `config.rs` | Transportabstraktion vorhanden; `char_device` und `usb_bulk`, noch kein TCP |
| Zebra-Laufzeit | `src/main.rs`, `worker.rs`, `persist.rs`, `model.rs` in ZebraTamer | Mehrere Worker, gespeicherte Jobs, Idempotenz und Wiederanlauf vorhanden; keine pauschale Neuentwicklung erforderlich |
| Zebra-Verwaltung | `src/device.rs`, `media.rs`, `api.rs`, `webui.*` | Gerätekonfiguration mit Rücklesen, Materialverwaltung und eingebettete UI vorhanden; Druckeranlage bislang aus Konfiguration |
| Druckformate | `components/ZebraTamer/src/driver.rs` | Zebra akzeptiert derzeit `application/zpl`; unimplementierter Niimbot-Platzhalter vorhanden |
| Fleet-Gerätelogik | `printer-fleet/printer_fleet/transports.py`, `drivers.py`, `status.py`, `maintenance.py` | TCP, Raster-zu-ZPL, Status und definierte Wartungsaktionen als Übernahmequellen |
| Fleet-Betrieb | `service.py`, `repository.py`, `postgres_repository.py`, `auth.py`, `discovery.py`, `agent.py` | Zustellregeln, Datenübernahme, Zugriffsschutz und Dienstanbindung analysieren; nicht vollständig kopieren |
| PrintHub-Kopplung | `components/PrintHub-ZPL-ll/zplgrid/fleet/`, `zplgrid/api.py` | Gegen gemeinsame Druckerdienst-Anbindung ersetzen; Aufträge und Statusabfragen sind derzeit Fleet-abhängig |
| PrintHub-Rendering | `zplgrid/labelary.py`, `printing/documents.py`, `printing/raster.py`, `printing/service.py` | Labelary-Anbindung und lokale Dokument-/Rasteraufbereitung bereits vorhanden |
| PrintHub-Jobs | `zplgrid/print_jobs_store.py`, Jobverarbeitung in `zplgrid/api.py` | Persistenz vorhanden; unveränderliche Artefakte, Hintergrundübergabe und belastbare Wiederaufnahme vervollständigen |
| IPP | `ipp-gateway/Dockerfile`, `entrypoint.py`, `submit_job.py`, `tcp_proxy.py` | Startet CUPS `ippeveprinter`, erzeugt PPD und reicht Dokumente an PrintHub; aktuell ein konfiguriertes Ziel pro Instanz |
| IPP-Dokumentverarbeitung | `zplgrid/printing/documents.py`, `pwg.py` | PDF, PostScript, PNG/JPEG, PWG/URF werden in PrintHub behandelt; beim Verschieben des Gateways erhalten |
| Veröffentlichungen | Root-`.github/workflows/`, `pipeline/` und Komponenten-Workflows | IPP, PrintHub, Studio und ZebraTamer haben AMD64-/ARM64-Pfade; Angaben in READMEs sind teilweise überholt |
| Pi 2 | ZebraTamer `deploy/pi2/`, CI/Binary-Releases | ARMv7-Binary-Pfad erhalten; kein Beleg für einen ARMv7-Gesamtstack |

IPP wurde nicht vollständig entfernt. Sein eigener Python-Code ist klein, weil CUPS das IPP-Protokoll und PrintHub die Dokumentaufbereitung übernimmt. Das bestehende IPP-Image heißt im Release-Workflow `ghcr.io/hartmannlight/printhub-ipp`. Der ZebraTamer-Workflow enthält Container-Veröffentlichung unter `ghcr.io/hartmannlight/print-agent`; widersprüchliche README-Angaben müssen korrigiert werden.

## 4. Gemeinsamer Druckvertrag und Verhaltensregeln

Diese Regeln sind verbindliche Eingaben für AP-01. Exakte JSON-Schemas und Routen werden dort festgeschrieben, bevor mehrere Komponenten implementiert werden.

### 4.1 Gemeinsame API und optionale Erweiterungen

Der Dienst meldet Protokollversion, `service_id`, Produktname, Version und Liste seiner Drucker. Ein Drucker meldet seine lokale ID, Anzeigenamen, Auflösung, maximalen Druckbereich, eingelegte Medien samt Revision, Status mit Zeitstempel und akzeptierte MIME-Typen. Fähigkeiten sind explizit `supported`, `unsupported` oder `unknown`; reine Boolesche Werte dürfen Unbekanntes nicht still als Unterstützung behandeln.

Der gemeinsame Vertrag umfasst Auftragseingang, Auftragsabfrage, paginierte Historie und Fehlerformat. Für Idempotenz muss ein Auftrag auch bei verlorener Annahmeantwort wiederauffindbar sein. Asynchrone Abfragen per HTTP sind zunächst ausreichend; Webhooks sind keine Voraussetzung.

Zebra-Konfiguration, Kalibrierung, Netzwerk-Konfigurationsetikett und andere herstellerspezifische Aktionen liegen in einer klar benannten optionalen Erweiterung. Allgemeine Verwaltungsfunktionen wie Warteschlangenpause oder Medienänderung werden über Fähigkeiten angeboten. Ein Rasterdienst muss weder Zebra-Snapshots noch ZPL-Einstellungen liefern.

Die PrintHub-API für Studio und externe Nutzer bleibt eine eigene öffentliche Schnittstelle. Sie darf gemeinsame Funktionen eines Dienstes vermitteln. Herstelleraktionen werden explizit angebunden, nicht als beliebiger URL-/Raw-Byte-Proxy.

### 4.2 Formate und Aufbereitung

Gemeinsame Formate:

- `application/zpl`: natives Zebra-Artefakt, ausschließlich an Dienste, die es akzeptieren.
- `application/vnd.printhub.raster-page+json`: vorhandenes neutrales Rasterformat, Version 1. Enthält `width_px`, `height_px`, `dpi`, `copies` und `black_bits_base64`.
- Rasterbits sind zeilenweise, MSB-first; Bit 1 bedeutet Schwarz. Zeilenlänge ist `ceil(width_px / 8)`. Nicht verwendete Bits der letzten Bytes müssen einen definierten weißen Wert haben.
- Der gemeinsame Auftragsumschlag ergänzt Identität, Prüfsumme, Druckerbezug, Beschreibungsdaten, Optionen und Medien-/Profilrevision. Er ist nicht Niimbot-spezifisch.

Ein logischer Auftrag enthält eine geordnete Liste vorbereiteter Seiten/Labels. Der Dienst akzeptiert die vollständige Liste dauerhaft, bevor er die erste Seite druckt; eine geeignete Upload-/Commit-Variante ist zulässig. Seiten eines Auftrags dürfen auf demselben Drucker nicht mit Seiten anderer Aufträge vermischt werden. Zwischen Seiten ist koordinierte Wartung/Pause zulässig, sofern sie die Jobsemantik nicht verletzt.

Kopien und Reihenfolge werden einmal im Vertrag definiert: uncollated/seiteweise Kopien und collated/Dokumentsätze dürfen nicht unbemerkt vertauscht werden. Ein nativer ZPL-Auftrag darf Kopien nicht gleichzeitig über eingebettetes `^PQ` und eine zweite Wiederholungsschleife vervielfachen. AP-01 legt die verbindliche Repräsentation fest; AP-04 und AP-08 setzen sie identisch um.

| Eingabe und Ziel | Aufbereitung in PrintHub | Verarbeitung im Dienst |
| --- | --- | --- |
| Template → Zebra, Standard | Variablen auflösen, ZPL erzeugen | ZebraTamer sendet natives ZPL |
| Template → Zebra, Bildmodus | ZPL erzeugen, Labelary rendern, auf Zielraster bringen | ZebraTamer kodiert Raster als Zebra-Grafikdruck |
| Template → reiner Rasterdienst | ZPL erzeugen, Labelary rendern, auf Zielraster bringen | Dienst verpackt Pixel im eigenen Geräteprotokoll |
| PDF/Bild/Raster → geeigneter Drucker | Lokal dekodieren/rasterisieren, skalieren und dithern | Dienst kodiert das fertige Raster für sein Gerät |

Bilddruck auf den derzeit unterstützten Zebras verwendet weiterhin eine ZPL-Grafikverpackung, beispielsweise `^GF`. ZebraTamer übernimmt diese Kodierung; Layout, Skalierung und Dithering bleiben in PrintHub. Kein Gerätetreiber ruft Labelary auf.

Labelary ist eine externe Abhängigkeit für Template-zu-Bild und entsprechende Vorschauen. Ausfall/Rate-Limit muss vor Druckübergabe verständlich behandelt werden. Druckinhalte verlassen bei Nutzung des öffentlichen Dienstes den eigenen Host; die Einrichtung erklärt dies und erlaubt eine alternative konfigurierte Renderer-URL. Kein eigener Renderer muss entwickelt werden. Fertige PDF-/Bildaufträge und natives Zebra-Drucken bleiben ohne Labelary möglich, soweit sie keine entsprechende Vorschau anfordern.

### 4.3 Haltbare Jobs und Wiederholung

| Zustand/Ereignis | Verbindliche Bedeutung |
| --- | --- |
| In PrintHub angenommen | Logischer Auftrag und Eingaben dauerhaft gespeichert; noch keine Behauptung über Hardwarezustellung |
| Vorbereitet | Template-Revision, aufgelöste Variablen einschließlich Makros/Zähler, Druckersnapshot und exakte Artefakte dauerhaft festgehalten |
| Beim Dienst `queued` | Auftrag, Idempotenzkennung und vollständige Artefakte dort dauerhaft gespeichert; keine bloße Annahme in RAM |
| Wartend/pausiert/Medienkonflikt | Keine weitere physische Übertragung, bis die dokumentierte Bedingung erfüllt ist |
| Übertragung aktiv | Daten könnten die Hardware erreicht haben; Abbruch kann unklaren Ausgang erzeugen |
| `transport_accepted` | Transport hat die vollständigen Daten angenommen; kein Nachweis eines Papierausdrucks |
| `completed_observed` | Belastbare Geräte- oder eindeutig gekennzeichnete Bedienerbestätigung liegt vor |
| `outcome_unknown` | Daten könnten angekommen sein; keine automatische physische Wiederholung |
| `failed` | Terminaler Fehler; Ursache und bisherige Zustellevidenz bleiben separat erhalten, besonders bei Mehrseitenjobs |

- Derselbe Idempotenzschlüssel mit demselben Ziel, Artefakt und wirksamen Optionen ergibt denselben Auftrag. Abweichungen ergeben einen Konflikt, beispielsweise HTTP 409.
- PrintHub darf bei verlorener Antwort denselben Inhalt mit derselben Kennung erneut übermitteln. Das ist keine neue physische Druckausführung.
- Nach dauerhafter Dienstannahme besitzt der Dienst die physische Warteschlange. PrintHub beobachtet diesen Auftrag, statt einen Ersatzauftrag zu erzeugen.
- Sicher vor dem ersten Byte gescheiterter Verbindungsaufbau kann mit begrenztem Backoff wiederholt werden. Bereits angenommene Seiten und unklare Übertragungen dürfen nicht automatisch erneut gedruckt werden.
- Ein Benutzer-Neudruck ist ein neuer Auftrag mit Referenz auf den ursprünglichen Auftrag und sichtbarer Information über mögliches Doppelmaterial.
- Ein Dienst-Timeout bei der Statusabfrage eines bekannten aktiven Jobs bedeutet zunächst „Status nicht erreichbar“, nicht automatisch „Druckausgang unbekannt“ oder „fehlgeschlagen“.
- Medien-/Profiländerung nach Vorbereitung: vor Hardwareausgabe Revision prüfen, gegebenenfalls anhalten. Nicht still unter derselben Kennung neu rendern oder ein anderes Ziel wählen.
- Idempotenz muss Aufräumen und Wiederanlauf überstehen. Nach Löschung großer Payloads bleiben ausreichend lange bzw. für alte Schlüssel dauerhaft ablehnende Metadaten erhalten; niemals einen alten Schlüssel still als Neudruck akzeptieren.

## 5. Übersicht und Abhängigkeiten

Alle Pakete beginnen mit Status „offen“. „Abhängig von“ bezeichnet fachlich notwendige Ergebnisse, nicht die Pflicht, jedes vorbereitende Lesen erst später zu beginnen. Umsetzung erfolgt jeweils in den betroffenen Komponenten; deren Tests und Verträge müssen zusammenpassen. Die Liste erlaubt Arbeitsteilung, fordert aber keine parallelen Agenten.

| ID | Arbeitspaket | Abhängig von |
| --- | --- | --- |
| AP-00 | Ausgangszustand und Funktionsinventar sichern | — |
| AP-01 | Druckerdienstvertrag und Konformitätsspezifikation | AP-00 |
| AP-02 | ZebraTamer-Persistenz und physische Warteschlange | AP-01 |
| AP-03 | ZebraTamer-TCP-Transport | AP-01, AP-02 |
| AP-04 | ZebraTamer-Rasterannahme und Zebra-Kodierung | AP-01, AP-02 |
| AP-05 | ZebraTamer-Geräteanlage, Medien und Wartung | AP-02, AP-03 |
| AP-06 | Gemeinsame ZebraTamer-API und Dienstzugriffsschutz | AP-01, AP-02; Abschluss mit AP-04, AP-05 |
| AP-07 | PrintHub-Druckerdienste und Druckerkatalog | AP-01, AP-06 |
| AP-08 | PrintHub-Artefakte und zielabhängiges Rendering | AP-01, AP-07 |
| AP-09 | PrintHub-Auftragsübergabe und Statusabgleich | AP-02, AP-06, AP-07, AP-08 |
| AP-10 | Gemeinsame Studio-Oberfläche und Einrichtung | AP-05, AP-07, AP-08, AP-09 |
| AP-11 | IPP ins PrintHub-Repository übernehmen | AP-00 |
| AP-12 | Mehrere IPP-Freigaben und durchgängiger Jobstatus | AP-01, AP-07, AP-09, AP-11 |
| AP-13 | Datenmigration, Sicherung und Wiederherstellung | AP-02, AP-05, AP-07, AP-09 |
| AP-14 | Komponenten-Images und Pi-Artefakte veröffentlichbar machen | Betroffene Komponentenpakete, AP-11, AP-12 |
| AP-15 | Einfacher Compose-Start und Betriebsprofile | AP-06, AP-10, AP-12, AP-14 |
| AP-16 | Reinen Rasterdienst und Vertragstests bereitstellen | AP-01; Integration mit AP-07, AP-08, AP-09 |
| AP-17 | Gesamtintegration und Hardwareabnahme | AP-03 bis AP-16 |
| AP-18 | Fleet, Fleet Console und Thingdex-Pflichtkopplung entfernen | AP-13, AP-15, AP-17 |
| AP-19 | Anwenderdokumentation und Produktrelease abnehmen | AP-18; finale Prüfungen aus AP-17 |

Die Umstellung darf schrittweise auf einem Entwicklungsstand erfolgen. Ein Release erhält jedoch nur einen aktiven physischen Zustellweg pro Drucker. AP-18 ist kein erster Schritt: Fleet darf erst entfernt werden, wenn sein benötigtes Verhalten ersetzt und die Übernahme bestehender Daten möglich ist.

## 6. Arbeitspakete

### AP-00 — Ausgangszustand und Funktionsinventar sichern

**Zweck:** Verhindern, dass beim Entfernen von Fleet unbemerkt Druckfunktionen, Daten oder bereits begonnene Änderungen verloren gehen.

**Umfang und Vorgehen:**

- Aktuellen Root-/Submodulstand, uncommittete Änderungen und vorgemerkte Löschungen erfassen. Vorhandene fremde Änderungen erhalten; keine pauschalen Restore-/Clean-Aktionen.
- Tatsächlich vorhandene APIs, Druckpfade, Images, Compose-Varianten, Installationsskripte und CI-Prüfungen inventarisieren. Historische Dokumente nur als Hinweise behandeln.
- Den bestehenden Pfad Template → Fleet → Zebra sowie IPP → PrintHub → Fleet → Emulator reproduzierbar erfassen. Bereits bestehende Fehler getrennt von Regressionen protokollieren.
- Bestehende Einstellungen, Datenverzeichnisse, öffentliche Drucker-IDs, ausstehende Jobs und relevante Legacy-Datenformate ermitteln. Keine Zugangsdaten in den Bericht übernehmen.
- Die Funktionszuordnung aus Abschnitt 3 gegen den Code prüfen und erforderliche Ergänzungen dieses Plans mit Begründung dokumentieren.

**Ergebnis und Abnahme:** Ein kurzes, versioniertes Inventar mit Komponentenständen, Testbefehlen, Datenquellen und bekannten Fehlern liegt vor. Jeder zu entfernenden Nutzerfunktion ist entweder ein Nachfolger oder eine ausdrücklich in diesem Plan erlaubte Streichung zugeordnet.

### AP-01 — Druckerdienstvertrag festlegen

**Zweck:** ZebraTamer und ein späterer Niimbot-Dienst müssen dieselben allgemeinen Druckfunktionen anbieten können, ohne einander im Code zu kennen.

**Betroffen:** PrintHub-Vertragsdokumentation/OpenAPI, ZebraTamer-API, passende SDK-Modelle und gemeinsame Testfixtures.

**Umfang und Vorgehen:**

- In einem versionierten Vertrag die Regeln aus Abschnitt 4 einschließlich Routen, JSON-Schemas, Fehlern und Versionsaushandlung präzisieren. Den neuen Dienstvertrag wegen der geänderten Semantik ausdrücklich gegenüber ZebraTamers Legacy-API versionieren.
- Druckerkatalog, optionale Fähigkeiten, unbekannte Beobachtungen, Medien-/Profilrevisionen und stabile Identitäten beschreiben. Zwei Instanzen dürfen dieselbe lokale Drucker-ID besitzen.
- Auftragsumschlag, ZPL/Raster, Prüfsummen, maximale Größen, vollständige Annahme mehrerer Seiten, Kopien/Sortierung, Auftragsabfrage und Idempotenz-Lookup spezifizieren.
- Zustandsübergänge für Upload, Annahme, Pausieren, Versand, Teilfehler, Abbruch und Wiederanlauf definieren. Warteschlangenpause ist von einem geräteeigenen Zebra-Pausezustand zu unterscheiden.
- Gemeinsame Endpunkte von optionalen Verwaltungs-/Zebra-Erweiterungen trennen. Nicht unterstützte Aktionen werden eindeutig abgewiesen.
- Beispielantworten für einen Zebra-Dienst und einen reinen Rasterdienst liefern; beide müssen ohne erfundene Hardwarewerte gültig sein.

**Ergebnis und Abnahme:** Maschinenlesbare Schemas, eine kompakte API-Beschreibung und positive/negative Testfixtures liegen vor. Zwei unabhängig implementierte Dienste können dieselben PrintHub-Aufträge nach den Beispielen annehmen. Offene Kernfragen zu Idempotenz, Kopien oder Zustandsbedeutung sind vor AP-02/AP-08 entschieden.

### AP-02 — ZebraTamer-Persistenz und physische Warteschlange vervollständigen

**Zweck:** Fleet besitzt heute zusätzliche Zustellgarantien. Nach seinem Entfall muss ZebraTamer angenommene Jobs allein zuverlässig verwalten.

**Betroffen:** ZebraTamer `persist.rs`, `model.rs`, `worker.rs`, `main.rs`, Auftragseingang in `api.rs`.

**Umfang und Vorgehen:**

- Vorhandene Persistenz wiederverwenden oder gezielt weiterentwickeln. Ob dateibasiert oder eingebettete Datenbank: Annahme, Artefakt, Idempotenzindex und Queue müssen nach Abstürzen konsistent sein. Kein Datenbankserver erforderlich.
- Dauerhaft geordnete FIFO-Warteschlangen je Drucker und vollständige Jobannahme herstellen. Wiederanlauf darf nicht von Dateisystem-Auflistungsreihenfolge abhängen.
- Einen schreibenden Prozess je Datenverzeichnis sicherstellen. Nebenläufige Annahme desselben Schlüssels ergibt genau einen Auftrag.
- Druck, Status und Wartung koordinieren; verschiedene Drucker bleiben unabhängig. Queue-Pause/Fortsetzen und Abbruch noch nicht übertragener Arbeit implementieren.
- Verbindungsfehler vor Byteübertragung getrennt von Teilübertragung erfassen. Die Größe des hochgeladenen Payloads ist kein Nachweis tatsächlich an die Hardware geschriebener Bytes.
- Begrenzte Backoffs und Neustartregeln aus Abschnitt 4 umsetzen. Bei Teiljobs Fortschritt erhalten und keinen kompletten Job automatisch erneut ausgeben.
- Speicher-/Queue-Grenzen, Aufräumen terminaler Payloads, Ereignishistorie und Idempotenz-Metadaten regeln. Schreibfehler dürfen nicht als erfolgreiche Annahme quittiert werden.

**Ergebnis und Abnahme:** Tests decken konkurrierende Annahme, verlorene HTTP-Antwort, Prozessabbruch in jeder Zustellphase, FIFO nach Neustart, Pause, unabhängige Drucker, volle Datenträger und Wiederholung alter Schlüssel nach Aufräumen ab. Angenommene Arbeit bleibt auffindbar; unklare Übertragungen drucken nicht automatisch erneut.

### AP-03 — Ethernet-/TCP-Unterstützung in ZebraTamer

**Zweck:** Derselbe ZebraTamer soll Netzwerk-Zebras ohne vorgeschalteten Pi betreuen und seine vorhandene Abfrage-/Konfigurationslogik wiederverwenden.

**Betroffen:** ZebraTamer `transport.rs`, `config.rs`, `worker.rs`; Fleet-TCP-Code als Referenz, nicht als neue Abhängigkeit.

**Umfang und Vorgehen:**

- Einen bidirektionalen TCP-Transport mit Host, Port 9100 als Standard, Verbindungs-/Schreib-/Antwortzeitlimits und begrenzten Antwortgrößen hinzufügen.
- Gesamtes Zeitbudget sowie erstes Antwortbyte und Ende/Leerlauf der Antwort unterscheiden. Verzögerte und mehrteilige Antworten vollständig behandeln; EOF, Teilantwort und Timeout bleiben unterscheidbar.
- Defekte Verbindungen verwerfen. Ein kontrollierter Neuaufbau muss sowohl Druck als auch Abfragen wieder ermöglichen. Statusantworten dürfen nicht einem späteren Befehl fälschlich zugeordnet werden.
- Die vorhandene `PrinterTransport`-Abstraktion für Druck, Konfiguration und Status nutzen. Auch ein transparenter TCP-Serial-Adapter kann mit explizitem Port und dokumentierten Geräteeinstellungen unterstützt bleiben.
- Vorhandene Verlustschätzungen für Hostboot/Reconnect prüfen: TCP-Sessionwechsel sind kein Beleg für Medienvorschub oder Druckerneustart. Schätzungen nur bei passenden Ereignissen und mit gekennzeichneter Herkunft anwenden.
- USB-/Character-Device-Pfade erhalten. Hardwaremodell und Transportwahl bleiben getrennte Konfigurationen.

**Ergebnis und Abnahme:** Ein kontrollierter TCP-Testserver prüft Druck, verzögerte Antworten, Abbruch vor/bei Übertragung, Wiederverbindung und begrenzte Timeouts. Derselbe Gerätecode arbeitet über USB und TCP. Reconnects allein reduzieren keinen Medienbestand. Ein realer Ethernet-Zebra wird in AP-17 abgenommen.

### AP-04 — Rasterannahme und Zebra-Grafikkodierung

**Zweck:** PDF-/Bilddruck funktioniert bisher über Fleets Raster-zu-ZPL-Kodierung. Diese Funktion muss ZebraTamer übernehmen und über den neutralen Vertrag anbieten.

**Betroffen:** ZebraTamer `driver.rs`, Auftragseingang, neue Raster-/ZPL-Kodierung; Referenz `printer-fleet/printer_fleet/drivers.py`.

**Umfang und Vorgehen:**

- Neben nativem ZPL das Rasterformat aus AP-01 akzeptieren. Version, Abmessungen, DPI, Bitreihenfolge, Padding, Byteanzahl, Prüfsumme und Gerätebereich prüfen, bevor Hardware-I/O beginnt.
- Raster in passende Zebra-Grafikbefehle kodieren. Kopien, Seitenreihenfolge, Druckbereich und Orientierung folgen ausschließlich der vereinbarten Jobsemantik.
- Kein erneutes Skalieren oder Dithern im Treiber. Auflösungskonflikte oder zu breite Bilder führen zu einem klaren Fehler/Hold.
- Vorhandene Geräte-Defaults nicht bei jedem Job ungefragt überschreiben. Fleets bisher injizierte Dunkelheit, Geschwindigkeit, Modus, Rotation und Kopien nicht blind kopieren; dauerhaftes Geräteprofil und explizite Joboptionen unterscheiden.
- Labelanzahl/Verbrauch aus dem tatsächlich vorbereiteten Job ableiten; Übertragung bleibt von bestätigtem Verbrauch unterscheidbar.
- Den reservierten `niimbot_b1`-Treiber und dessen spezielle MIME-Erwartung aus ZebraTamer entfernen, sobald kein aktiver Vertrag darauf angewiesen ist.

**Ergebnis und Abnahme:** Native ZPL-Jobs und Rasterjobs drucken über denselben Worker. Tests prüfen unter anderem Breiten außerhalb eines Vielfachen von acht, Schwarz/Weiß-Polarität, Mehrseiten/Kopien, unveränderte Geräte-Defaults und Ablehnung fehlerhafter Raster vor I/O. Grafikausgabe wird mit Emulator und Hardware überprüft.

### AP-05 — ZebraTamer-Geräteanlage, Medien und Wartung

**Zweck:** Ein Anwender soll nach dem Start Drucker einrichten können, ohne eine TOML-Datei oder Fleet Console bearbeiten zu müssen.

**Betroffen:** ZebraTamer Konfiguration, Worker-Verwaltung, `device.rs`, `media.rs`, `api.rs`, eingebettete WebUI.

**Umfang und Vorgehen:**

- Persistente Verwaltungs-API und einfache UI für Anlegen, Bearbeiten und Deaktivieren von Zebra-Druckern schaffen. TCP benötigt Host/Port; USB bietet gefundene Geräte samt eindeutigen Merkmalen an.
- Leere Druckerliste und Hot-Addition unterstützen. Neue/entfernte Worker, Polling und Discovery müssen dem aktuellen Inventar folgen. Änderungen am Endpunkt bei aktiver Arbeit werden kontrolliert angehalten oder abgelehnt.
- Bestehende Datei-Konfiguration über einen dokumentierten Import-/Seed-Weg übernehmen. Danach gibt es eine eindeutige persistente Quelle; Umgebungs-/Seed-Werte dürfen UI-Änderungen nicht bei jedem Start überschreiben.
- Gerätemodell, bestätigtes Profil und beobachtete Daten getrennt halten. „Verbindung prüfen“ führt keinen Testdruck oder automatische Kalibrierung aus.
- Bestehende Konfigurationsbearbeitung mit frischem Rücklesen, Revisionsprüfung, gezieltem Setzen und geprüftem Speichern erhalten.
- Fleets definierte Aktionen für Konfigurationsetikett, Netzwerk-Konfigurationsetikett und Medienkalibrierung in ZebraTamer integrieren. Aktionen laufen durch den Gerätekoordinator und dokumentieren Medienbewegung und Ergebnis.
- Eingelegte Rolle, Farbe, Maße, Bestandsänderung, Verbrauchsschätzung und Medienkonflikte mit Revision anbieten. Wartende Jobs bei relevantem Medienwechsel anhalten.
- Historie bei Deaktivierung erhalten; Entfernen eines Druckers mit offenen Jobs darf sie nicht verwaisen lassen.

**Ergebnis und Abnahme:** Ethernet- und USB-Zebra sind ohne Konfigurationsdatei anlegbar. UI-Änderungen überstehen Neustarts. Zwei gleichartige USB-Geräte werden nicht verwechselt. Medienwechsel, Wartung und Jobs verlieren keine Änderungen und überschreiben einander nicht.

### AP-06 — Gemeinsame ZebraTamer-API und Zugriffsschutz

**Zweck:** ZebraTamer wird ein direkt verwendbarer Netzwerkdienst. Die neue API muss herstellerneutral konsumierbar und vollständig geschützt sein.

**Betroffen:** ZebraTamer API/Discovery/WebUI, Service-Konfiguration, gemeinsame Vertragstests.

**Umfang und Vorgehen:**

- AP-01 auf ZebraTamer abbilden: Identität, Katalog, Fähigkeiten, generische Jobannahme, Status, Historie, Idempotenz-Lookup und optionale Verwaltungsfunktionen.
- Bestehende `agent_id` installationsübergreifend eindeutig in `service_id` überführen; keine neue Identität allein durch Umbenennung generieren. Alte URLs dürfen nur in einem befristeten, dokumentierten Migrationspfad bestehen.
- Druckannahme, Payload-Download, Jobs, Medien und Administration konsistent authentifizieren. Ein ungeschützter Legacy-ZPL-Endpunkt darf den Schutz nicht umgehen.
- Einfache Dienstberechtigungen für Lesen/Drucken und Administration vorsehen; keine komplexe Mandantenverwaltung. Setup erzeugt individuelle Zugangsdaten und speichert sie dauerhaft, ohne Standard-Admin-Passwort.
- Versions-/Identitätsprüfung beim Verbindungsaufbau, aussagekräftige Fehler, begrenzte Eingaben und nachvollziehbare Verwaltungsereignisse bereitstellen. Payloads und Zugangsdaten nicht ungefiltert protokollieren.
- Standalone-WebUI erhalten. Ein zentraler Stack kann dieselben APIs über den PrintHub-Einstieg nutzen; Remote-Dienste bleiben unabhängig betreibbar.

**Ergebnis und Abnahme:** ZebraTamer besteht die gemeinsame Vertragssuite. Druckjobs ohne Berechtigung, unzulässige Administration, Identitätswechsel und Legacy-Umgehung werden verhindert. Eine korrekt konfigurierte entfernte Instanz lässt sich von PrintHub anbinden.

### AP-07 — PrintHub-Druckerdienste und Druckerkatalog

**Zweck:** Druckerauswahl und Zuordnung müssen Fleet überleben, während Hardwaredetails in den Druckerdiensten bleiben.

**Betroffen:** PrintHub `zplgrid/fleet/` als zu ersetzender Bereich, Drucker-API, neue persistente Dienst-/Druckerzuordnungen, SDK.

**Umfang und Vorgehen:**

- Eine kleine interne Druckerdienst-Abstraktion implementieren: Dienstinformationen, Drucker auflisten/lesen, Auftrag übergeben/abfragen, erlaubte Verwaltungsfunktionen. Benennung und Fehler dürfen Fleet nicht weiter als Produkt voraussetzen.
- Dienstverbindungen mit URL, erwarteter Identität, Protokollversion und geschützt gespeicherten Zugangsdaten verwalten. Bekannte lokale ZebraTamer-Instanz beim Erststart verbinden.
- Remote-URL manuell hinzufügen können. Discovery ist eine bequeme Ergänzung; mDNS-Erreichbarkeit ist keine Startvoraussetzung. Gefundene unbekannte Geräte werden erst nach Nutzerentscheidung nutzbar.
- Öffentliche Drucker-IDs, Anzeigenamen, Standarddrucker, Sichtbarkeit und IPP-Freigabe in PrintHub halten; Hardware-Endpoint und Gerätekonfiguration nicht als zweite Quelle anlegen.
- Fähigkeiten, Medien und Status mit Herkunft/Zeitstempel projizieren. Offline-Dienste bleiben mit ihren bekannten Druckern sichtbar. Veraltete Werte werden markiert.
- Konflikte durch doppelte Dienstidentitäten und doppelte physische Drucker erkennen und vor zweitem aktivem Zustellweg klären.
- Öffentliche PrintHub-Auswahlendpunkte und SDK soweit sinnvoll kompatibel halten; unvermeidliche Änderungen ausdrücklich versionieren und alle eigenen Nutzer migrieren.

**Ergebnis und Abnahme:** Zwei ZebraTamer-Instanzen mit identischen lokalen IDs sowie der spätere Test-Rasterdienst erscheinen korrekt getrennt. URL-Wechsel erhält Identitäten, Offline-Ziele bleiben sichtbar, und PrintHub benötigt keine Fleet-Verbindung für Druckeroperationen.

### AP-08 — Unveränderliche Artefakte und zielabhängiges Rendering

**Zweck:** Ein ausgefülltes Template soll auf Zebra nativ und auf einem reinen Bilddrucker als Raster verwendbar sein. Wiederholte Übermittlung darf seinen Inhalt nicht verändern.

**Betroffen:** PrintHub Templateverarbeitung in `api.py`, `labelary.py`, `printing/`, Job-/Artefaktspeicher.

**Umfang und Vorgehen:**

- Eine explizite Ausgabeentscheidung anhand der akzeptierten Formate einführen: Zebra standardmäßig ZPL, reiner Rasterdienst immer Raster; optionaler Bildmodus für Zebra.
- Template-Revision, Variablen, Makros, Datums-/Zählerwerte und wirksames Ticket einmal festhalten. Mehrfache Übermittlung desselben Auftrags darf weder neue Zählerwerte erzeugen noch geänderte Templates laden.
- Exakte Artefakte und Prüfsummen vor der Dienstübergabe dauerhaft speichern. Entsprechende Auftragszustände erlauben Wiederanlauf ohne erneute inhaltliche Auswertung.
- Für Template-zu-Raster bestehende Labelary-Anbindung nutzen. Physische Größe und Zielauflösung abstimmen; begrenzte Renderer-Auflösungen dürfen nicht still falsche Labelmaße ergeben.
- Ergebnis für Vorschau und Druck konsistent aufbereiten. Caching berücksichtigt Inhalt, Renderer-Konfiguration, Maße, Auflösung und Renderingoptionen. Leere/ungültige oder abgeschnittene Antworten werden abgewiesen.
- Bestehende lokale PDF-, PostScript-, Bild- und PWG/URF-Verarbeitung erhalten. Skalierungsregeln `hold`/`fit`/`fill`, Dithering und Jobgrenzen gelten unabhängig vom Eingang und Gerätehersteller.
- Renderer-Nutzung transparent konfigurieren. Timeout, Rate-Limit und Ausfall lassen einen nachvollziehbaren nicht übertragenen Job zurück.

**Ergebnis und Abnahme:** Dasselbe Template erreicht Zebra als ZPL und den Rastertestdienst als korrektes Bild. Ein Neustart oder Übermittlungsretry verändert weder Pixel/ZPL noch Makro-/Zählerwerte. PDF-/Bilddruck benötigt Labelary nicht. Unpassende Medien oder überschrittene Labelgrenzen führen vor Geräte-I/O zu Hold/Fehler.

### AP-09 — PrintHub-Auftragsübergabe und Statusabgleich

**Zweck:** Die logische Auftragshistorie bleibt zentral nutzbar, während jeder Dienst seine physische Ausführung besitzt.

**Betroffen:** PrintHub `print_jobs_store.py`, Verarbeitung und Reconciliation in `api.py`, neue Dienstadapter, optionale Integrationsevents.

**Umfang und Vorgehen:**

- Einen dauerhaften Hintergrundablauf für Vorbereitung, Übergabe und Statusabgleich bereitstellen. Die HTTP-Annahme muss nicht bis zum Druck oder einem langen Renderer-Aufruf warten.
- Annahme auf PrintHub-Ebene mit Inhaltsprüfung idempotent machen; gleicher Schlüssel mit geänderten Eingaben ist kein still akzeptierter alter Job.
- Stabile Übergabekennung vor Versand speichern. Verlorene Antworten durch Lookup/Wiederholung derselben Kennung auflösen; neue technische Versuche erzeugen keine neuen physischen Aufträge.
- Dienst-ID, lokale Job-ID, Seitenfortschritt und Ergebnis dauerhaft zuordnen. Zustände gemäß Abschnitt 4 auf die Nutzeransicht abbilden.
- Hintergrundabgleich muss auch ohne offene Browserseite und nach Neustart funktionieren. Keine Begrenzung auf eine kleine UI-Historienseite bei der Wiederaufnahme offener Jobs.
- Medienwechsel, Dienstausfall, unklaren Druckausgang und teilgedruckte Dokumente unterscheiden. Freigabe/Abbruch/Neudruck bieten genau die durch Zustellstand erlaubten Optionen.
- Wiederaufnahme nach Medienänderung mit neuer Artefaktversion nur für sicher nicht ausgegebene Arbeit; alte Kennungen und Ergebnisse bleiben nachvollziehbar.
- Externe PrintHub-Nutzer erhalten denselben Status. Thingdex-Events bleiben optional; Start/Druck hängt nicht von deren Empfänger ab.

**Ergebnis und Abnahme:** Verlorene Antwort direkt nach Annahme, Neustart vor/nach Übergabe, offline bleibender Dienst und Teiljobfehler erzeugen keinen automatischen Doppeldruck. Mehr als 200 offene/alte Jobs beeinträchtigen Recovery nicht. Oberfläche und API zeigen identische nachvollziehbare Zustände.

### AP-10 — Studio als gemeinsamer Produkteinstieg

**Zweck:** Nach dem Entfernen von Fleet Console bleiben Einrichtung und Administration erreichbar. Anwender benötigen keine Kenntnisse der internen Dienste.

**Betroffen:** LabelArchitect, PrintHub-Verwaltungsendpunkte, SDK, ZebraTamer-Erweiterung.

**Umfang und Vorgehen:**

- Einen Druckerbereich mit Dienstanbindung, Druckerübersicht, Material, Status, Standarddrucker, Warteschlangensteuerung und IPP-Freigabe integrieren.
- Einen Erststart ohne Drucker abbilden: Ethernet-Zebra hinzufügen, lokalen USB-Zebra auswählen oder entfernten Druckerdienst verbinden. Testdruck ist eine explizite Nutzeraktion.
- Gemeinsame Formulare verwenden generische Daten. Zebra-Gerätekonfiguration/Wartung wird nur für entsprechende Fähigkeiten angeboten und an ZebraTamer vermittelt.
- Reinen Rasterdrucker ohne ZPL-Konfiguration vollständig in Auswahl, Vorschau und Druck anbieten. Unterstützte Formate und Renderingfehler verständlich darstellen.
- Auftragsansicht für Vorbereitung, Hold, Offline-Warten, Dienstannahme, Transportannahme, Bestätigung und unklaren Ausgang umsetzen. „Erfolgreich gedruckt“ nur bei entsprechender Evidenz anzeigen.
- Medienrevisionen und Änderungen anderer Sitzungen berücksichtigen. Bestätigungsdialoge nur bei tatsächlichen Geräte-/Auftragsfolgen; keine technischen Protokollbegriffe als Voraussetzung zur Bedienung.
- Gleicher Browserursprung für Oberfläche/API, funktionierende Remote-Links, keine in ausgeliefertes JavaScript eingebauten Dienstgeheimnisse.
- Fleet-Console-Verlinkungen, SDK-Modelle und eigene UI-Tests auf den neuen Weg migrieren. ZebraTamers Standalone-UI bleibt benutzbar.

**Ergebnis und Abnahme:** Ein neuer Nutzer kann nach Compose-Start einen Drucker einrichten, Material bestätigen, Template ausfüllen, drucken und Ergebnis prüfen. Zebra und Rastertestdienst benötigen denselben normalen Druckablauf. Kein notwendiger Schritt führt zu Fleet Console oder verlangt manuelle API-Aufrufe.

### AP-11 — IPP-Code ins PrintHub-Repository übernehmen

**Zweck:** IPP ist ein Eingang von PrintHub und wird mit diesem entwickelt, behält aber wegen CUPS/Discovery sein eigenes Laufzeitimage.

**Betroffen:** Root-`ipp-gateway/`, PrintHub-Repository, Docker-/Release-Workflows, Integrationstests.

**Umfang und Vorgehen:**

- Dockerfile, Gateway-Code und relevante Tests/Fixtures ins PrintHub-Repository verschieben. Die vorhandene Funktion zunächst erhalten und funktionierende Baseline-Tests mitnehmen.
- Eigenen IPP-Buildkontext und Image-Release dort einrichten. Root-Compose und CI konsumieren anschließend das passende Image bzw. den neuen Entwicklungs-Buildkontext.
- Dokumentaufbereitung in PrintHub belassen. Durch den Verzeichniswechsel weder PDF/Raster-Dekodierung duplizieren noch Formate streichen.
- TLS-/Spool-Datenpfade und bestehende Queue-IDs bei der Verschiebung erhalten bzw. ausdrücklich migrieren.
- Den alten Root-Ordner erst nach Umstellung aller Build-/Testverweise entfernen. Übergangsduplikate nicht als dauerhafte zweite Implementierung pflegen.

**Ergebnis und Abnahme:** Ein eigenständiges IPP-Image lässt sich aus dem PrintHub-Repository bauen. Bisher unterstützte IPP-Dokumente erreichen weiterhin PrintHub. Der Root-Build benötigt den alten Gateway-Ordner nicht mehr.

### AP-12 — IPP-Freigaben, Discovery und Jobstatus vervollständigen

**Zweck:** IPP muss zum Produkt mit mehreren nachträglich eingerichteten Druckern passen und den tatsächlichen Auftragsfortschritt nachvollziehbar melden.

**Betroffen:** IPP-Gateway, PrintHub-Freigabe-/Job-API, gemeinsame Studio-Einstellungen, Deployment-Netzwerk.

**Umfang und Vorgehen:**

- Eine persistente Freigabe pro ausgewähltem PrintHub-Drucker mit stabiler Queue-ID, erreichbarer URI und Namen abbilden. Ein Gateway-Container verwaltet mehrere Freigaben; Nutzer editieren keine Compose-Datei pro Drucker.
- Mit null Freigaben gesund starten. Hinzufügen, Deaktivieren, Offline-Ziel und Medienänderungen zur Laufzeit verarbeiten.
- DPI, eingelegtes Medium und akzeptierte Eingabeformate als echte IPP-Fähigkeiten ausgeben. Keine Formate oder Statusgarantien bewerben, die der Eingang nicht unterstützt.
- Eignung des bisherigen `ippeveprinter` für mehrere verwaltete Queues und dauerhafte Jobstatus-Synchronisation konkret prüfen. Falls dessen Kindprozess-Modell nicht genügt, innerhalb des Gateways eine geeignete CUPS-/IPP-Serverintegration wählen und begründen. Ein erfolgreich beendetes Weiterleiterskript allein ist keine ausreichende Endzustandsintegration.
- IPP-Job-ID/UUID und PrintHub-Job-ID dauerhaft verknüpfen. Wiederholung nach Gateway-Neustart verwendet dieselbe Kennung; Dokumentinhalt allein darf zwei bewusst verschiedene Druckaufträge nicht zusammenfassen.
- Holds, Fehler, Abbruch und Fortschritt während der Joblebensdauer aktualisieren. Physisch unbestätigte Ausgabe bekommt eine dokumentierte, ehrliche IPP-Abbildung und sichtbare PrintHub-Details; keinen nicht bestätigten Papierausdruck behaupten.
- Capability-Aktualisierungen dürfen keine laufenden Jobs verlieren. IPP-Spool erst nach gesicherter Übergabe bzw. dokumentierter Aufbewahrungsregel entfernen.
- DNS-SD/mDNS und angekündigte Hostnamen aus einem echten LAN testen. Containerinternes Avahi oder ein offener TCP-Port allein beweist keine Client-Erkennung.
- Direkte Einrichtung über eine stabile IPP-URI als Alternative anbieten, wenn Multicast auf der Hostplattform nicht durchgereicht wird.

**Ergebnis und Abnahme:** Zwei unterschiedliche freigegebene Drucker sind gleichzeitig benutzbar. Hinzufügen nach leerem Start, Medienwechsel, held Job, Abbruch, Neustart und verlorene Antwort sind geprüft. Mindestens ein echter Betriebssystemclient und ein CUPS/ipptool-Client drucken über den vollständigen neuen Pfad; angekündigte LAN-Adressen sind erreichbar.

### AP-13 — Datenmigration, Sicherung und Wiederherstellung

**Zweck:** Fleet kann erst gelöscht werden, wenn bestehende Drucker, Einstellungen und Auftragsinformationen sicher übernommen oder nachvollziehbar archiviert sind.

**Betroffen:** Fleet-Datenexport als einmaliges Werkzeug, PrintHub- und ZebraTamer-Daten, bestehende Konfigurationen, Betriebsdokumentation.

**Umfang und Vorgehen:**

- Einen wiederholbaren Dry-Run-Importer mit Migrationsbericht schaffen. Quellen umfassen vorhandene Fleet-SQLite-Daten und, sofern benutzt, PostgreSQL über einen versionierten Export; Zielbetrieb benötigt PostgreSQL nicht.
- Direkte TCP-Ziele nach ZebraTamer übertragen; vorhandene Agent-Ziele an ihre bisherigen Instanzen binden. Öffentliche PrintHub-Drucker-IDs und Dienstidentitäten erhalten.
- Medienquelle, Geräteprofil, Offsets, Defaults und Zugriffsdaten feldweise zuordnen. Konflikte berichten. Fleets relatives Dunkelheitskommando `^MD` ist beispielsweise nicht ohne Prüfung identisch mit ZebraTamers absolutem `~SD`.
- Keine persistente Hardwarekonfiguration während eines Datenimports still auf das Gerät schreiben. Übernommene Werte sind entweder bestätigte Profile, explizite Jobvorgaben oder vor Anwendung zu prüfende Legacy-Werte.
- Alte Zustellungen mit bekannten Ergebnissen archivieren/zuordnen. Aktive oder unklare Zustellungen beim Schnitt anhalten und berichten; nie automatisch als neue Dienstjobs erneut einspeisen.
- Umstellung mit gestoppter Annahme/alten Workern, konsistenter Sicherung, Import, Vergleich und kontrolliertem Start beschreiben. Kein unbefristeter Dual-Write.
- Sicherung und Restore von PrintHub, ZebraTamer und IPP einschließlich Identitäten, Artefakten, Idempotenzdaten und nötigen Geheimnissen bereitstellen. Restore überschreibt keine bestehenden Daten ungefragt.
- Rollback-Verfahren definieren: nach im neuen System angenommenen Jobs keine alte Sicherung blind als aktiven Queue-Stand starten. Zuerst neue Zustellungen abgleichen/anhalten.

**Ergebnis und Abnahme:** Frischinstallation und Migration mit realitätsnahen Fixtures funktionieren. Wiederholter Import erzeugt keine doppelten Drucker. Zuordnungs-/Konfliktbericht ist vollständig. Restore erhält Identitäten und Doppeldruckschutz. Keine Migration oder Rollback-Probe löst unbestellte Hardwareausgabe aus.

### AP-14 — Images und Pi-Artefakte bereitstellen

**Zweck:** Anwender sollen keine Compiler, Node-Abhängigkeiten oder Git-Submodule zum Start benötigen.

**Betroffen:** Komponenten-Dockerfiles, CI-/Release-Workflows, Root-Release-Metadaten, ZebraTamer-Binary-Paketierung.

**Umfang und Vorgehen:**

- Für PrintHub, Studio, ZebraTamer und IPP getestete AMD64-/ARM64-Images aus den zuständigen Repositories bauen. Versionen und unterstützte Plattformen eindeutig veröffentlichen.
- Bestehende Build-, Test- und Herkunftsnachweise erhalten, soweit sie weiterhin passen. Keine Veröffentlichung eines Images, das nicht dem geprüften Artefakt entspricht.
- ZebraTamer-Produkt-/Imagebezeichnungen konsistent dokumentieren. Falls `print-agent` umbenannt wird, einen ausdrücklichen Upgradepfad liefern; Pfade und Identitäten nicht beiläufig ändern.
- ARMv7-Binary und systemd-/USB-Einrichtung für den kleinen Pi-Geräteserver erhalten und gegen den neuen Vertrag prüfen. ARMv7-Unterstützung nicht nur aus erfolgreichem Cross-Compile behaupten.
- IPP-Veröffentlichung vollständig dem PrintHub-Repository zuordnen. Root-Release referenziert ein zusammen getestetes Set konkreter Versionen/Digests.
- Anwender-Compose, Beispielkonfiguration und Versionsübersicht als kleines Release-Paket bereitstellen. Registry-Download und Plattformauswahl aus sauberer Umgebung prüfen.

**Ergebnis und Abnahme:** Alle erforderlichen Images sind für beide Standardarchitekturen beziehbar und startfähig. Ein Release benennt genau die gemeinsam geprüften Komponenten. Der Pi-Geräteserverpfad ist separat dokumentiert; kein README widerspricht dem tatsächlichen Veröffentlichungsweg.

### AP-15 — Compose-Erststart und Betriebsprofile vereinfachen

**Zweck:** Aus den Komponenten muss ein Produkt entstehen, das mit wenigen Schritten auf PC/Server oder einem 64-Bit-Pi nutzbar ist.

**Betroffen:** Root-Compose, Release-Paket, Bootstrap, Umgebungsvariablen, persistente Volumes, Netzwerkzugang.

**Umfang und Vorgehen:**

- Standard-Compose mit Images für Studio, PrintHub, ZebraTamer und IPP erstellen. Fleet, Thingdex, externe Datenbank und Emulator sind keine Startabhängigkeiten.
- Ersten Start mit leerem Druckerkatalog zulassen. Healthchecks unterscheiden Dienstbereitschaft von Drucker-/Renderer-Erreichbarkeit.
- Individuelle interne Zugangsdaten automatisch erzeugen und in geeigneten persistenten Datenpfaden teilen. Erneuter Start überschreibt weder Passwörter noch Identitäten; Browser-Setup benötigt keine Handarbeit in mehreren Secret-Dateien.
- Eindeutigen authentifizierten Einstieg anbieten. Standard-PC-Zugriff, LAN-Zugriff auf dem Pi und Reverse-Proxy/TLS-Betrieb mit wenigen erklärten Optionen unterstützen. Keine unbeabsichtigt öffentlichen Admin- oder Raw-ZPL-Zugänge.
- USB als verständliche zusätzliche Hosteinrichtung behandeln: stabile Geräteauswahl, Rechte und Linux-Geräteweitergabe. Den gesamten Stack nicht pauschal privilegiert starten. Windows/Docker-Desktop-USB-Voraussetzungen ausdrücklich vom Ethernet-Start trennen.
- Entfernten ZebraTamer als kleines eigenständiges Compose-/systemd-Beispiel anbieten. Mehrere Instanzen benötigen weder Fleet noch eine zweite PrintHub-Installation.
- Emulator/Demo und lokale Builds in optionale Entwicklungsprofile oder getrennte Compose-Dateien auslagern. Ein Demo-Gerät wird nicht unbemerkt zum Standarddrucker einer echten Installation.
- Alle Dienste bei SIGTERM sauber beenden; Volumes, Backup, Update und Datenverzeichnis-Migration mit stabilen Namen unterstützen.

**Ergebnis und Abnahme:** In einer leeren AMD64-/ARM64-Umgebung startet `docker compose up -d` aus dem Release-Paket ohne Git-/Build-Werkzeuge. Die UI erklärt die noch fehlende Druckereinrichtung. Ethernet benötigt keine Host-Gerätefreigabe. Neustart und Update erhalten Einrichtung, Templates, Rollen und Jobs.

### AP-16 — Rastertestdienst und gemeinsame Konformitätstests

**Zweck:** Die Niimbot-Erweiterbarkeit muss während des Refactorings nachweisbar sein, obwohl dessen echte Hardwarekommunikation später entwickelt wird.

**Betroffen:** Gemeinsame Fixtures/Schemas, Testdienst im Testbereich, PrintHub-/ZebraTamer-/Studio-Integration.

**Umfang und Vorgehen:**

- Einen kleinen, ausdrücklich simulierten Druckerdienst bereitstellen, der ausschließlich das neutrale Rasterformat annimmt und empfangene Pixel sowie Jobdaten überprüfbar speichert.
- Keine ZPL-Konfiguration, Zebra-Identifikation oder erfundene Niimbot-Kommandos implementieren. Der Dienst ist kein produktiv nutzbarer Niimbot-Treiber und wird nicht als solcher angeboten.
- Gemeinsame Tests für Identität, Fähigkeiten, Annahme, Idempotenz, Status, unbekannte optionale Funktionen und Fehlerantworten gegen ZebraTamer und Simulator ausführen.
- Steuerbare Fehlerfälle hinzufügen: verlorene Antwort nach Annahme, Offline-Zeit, langsamer Job und explizit simulierter unklarer Ausgang. Simulierte Druckbestätigung im Bericht als Simulation kennzeichnen.
- Template → Labelary-Adapter → Raster → Testdienst und Dokument → Raster → Testdienst integrieren. Im normalen CI deterministische Renderer-Fixtures verwenden; Live-Renderer-Prüfung separat.

**Ergebnis und Abnahme:** Der Testdienst ist über denselben PrintHub-/Studio-Ablauf wie Zebra nutzbar. Seine gespeicherten Bilder entsprechen den erwarteten Druckrastern. Keine generische Produktionsfunktion verlangt eine Zebra-spezifische Antwort oder kennt `niimbot_b1` als Sonderfall.

### AP-17 — Gesamtintegration und reale Geräte abnehmen

**Zweck:** Einzelne Unit-Tests beweisen weder ein benutzbares Produkt noch einen korrekten physischen Druckpfad.

**Betroffen:** Root-Integrationstests, Komponenten-Vertragstests, Release-Kandidat, Hardwareprotokoll.

**Umfang und Vorgehen:**

- Eine automatisierte Testmatrix für den neuen Gesamtpfad aufbauen. Bisherige Fleet-Tests nach Verhalten zuordnen; wertvolle Fehlerfalltests übertragen, obsolete Implementierungsassertionen entfernen.
- Auf frischen Volumes Einrichtung, Templatebearbeitung, ZPL-/Rasterdruck, Dokumentdruck, mehrere Drucker, IPP und Neustart prüfen.
- Fehler nach dauerhafter Annahme, während Geräteausgabe, bei Renderer-Ausfall und nach Medienwechsel gezielt injizieren. Erwartete Hardware-/Simulator-Auftragsanzahl prüfen, nicht nur HTTP-Statuscodes.
- Integration mit mindestens einem realen Ethernet-Zebra und einem realen USB-Zebra bzw. dem vorhandenen Pi-Geräteserver durchführen. Modell, Transport, Firmware soweit bekannt, Medium, DPI und exakte Softwareversionen erfassen.
- Druckmaß, Ausrichtung, Schwarz/Weiß, Barcode-Lesbarkeit, Kopien und Medienbuchhaltung prüfen. Nicht antwortender USB-Rückkanal ist ein dokumentierter Fähigkeitszustand, kein Grund für erfundene Statuswerte.
- IPP von einem echten LAN-Client inklusive Einrichtung, Freigabewechsel und Statusverhalten prüfen. AMD64 und ARM64 wenigstens durch reproduzierbare Start-/Integrationsprüfungen abdecken; Pi-Betrieb real prüfen.
- Einen Kurztest der bestehenden öffentlichen API-Nutzung ohne Thingdex sowie optional der bisherigen Thingdex-Anbindung vorsehen. Der Standalone-Test startet keinen Thingdex-Dienst.

**Ergebnis und Abnahme:** Die Matrix aus Abschnitt 7 ist mit Ergebnissen und Belegen ausgefüllt. Nicht verfügbare Hardwaretests sind als offen markiert und dürfen nicht als bestanden gelten. Ein Paketstatus „Code fertig“ ersetzt keine fehlende Produktabnahme.

### AP-18 — Fleet und Pflichtkopplungen vollständig entfernen

**Zweck:** Nach erfolgreichem Ersatz darf die alte Architektur weder im Laufzeitpfad noch in den Bedienungsanweisungen weiterleben.

**Betroffen:** Root-`printer-fleet/`, `fleet-console/`, `config/printers.yml`, Compose/CI/Release, PrintHub-Fleet-Adapter, Studio/SDK, `.gitmodules`, `docs/DESIGN.md`.

**Umfang und Vorgehen:**

- Nach AP-13/AP-17 die produktiven Fleet-/Fleet-Console-Quellen, Buildziele, Jobs, Ports, Umgebungsvariablen, Secret-Vorlagen und Abhängigkeiten entfernen.
- PrintHub-Fleet-Ports/-Adapter sowie Fleet-spezifische API-/UI-Namen vollständig ersetzen. Eine bloße Umbenennung der alten gesamten Control Plane zählt nicht als Umsetzung.
- Root- und Komponenten-Workflows auf das verbleibende Produkt ausrichten. Der IPP-Build verwendet den in AP-11 festgelegten Ort; Emulator bleibt optional.
- Thingdex und Thingdex-Home-Inventory aus dem notwendigen Submodul-/Build-/Releasepfad lösen. Lokale fremde Änderungen oder persistente Daten nicht mitentfernen.
- Alte `docs/DESIGN.md` entfernen und alle Links/Architekturprüfungen umstellen. Eine kurze, aktuelle Architekturquelle wird in AP-19 geliefert.
- Einmalige Migrationstools dürfen als Legacy-Import bestehen bleiben, benötigen aber keinen laufenden Fleet-Server. Alte Jobinformationen bleiben als solche gekennzeichnet lesbar.
- Bestehende Docker-Volumes, Datenbanken, Backups und veröffentlichte historische Images nicht automatisch löschen. Das Entfernen einer Compose-Referenz ist kein Auftrag zur Vernichtung der Daten.

**Ergebnis und Abnahme:** Der neue Stack baut/startet/testet ohne Fleet und Thingdex. Eine gezielte Suche findet Fleet nur in historischen Migrationsinformationen, Importern und diesem Umbauplan. Es existiert kein erreichbarer alter Druckpfad und keine notwendige Fleet-UI mehr. Der finale Code-/Submodulstand durchläuft erneut die relevante Gesamtintegration.

### AP-19 — Dokumentation, Upgrade und Produktrelease abschließen

**Zweck:** Ein technisch funktionierender Entwicklungsstand ist erst dann ein fertiges Produkt, wenn ein neuer Nutzer ihn installieren und ein bestehender Nutzer sicher umsteigen kann.

**Betroffen:** Root-README, kurze Architektur-/Betriebsdokumentation, Komponenten-READMEs, Release-Paket und Versionshinweise.

**Umfang und Vorgehen:**

- Eine neue kurze Architekturübersicht aus Abschnitt 2 bereitstellen. Sie ersetzt die alte Fleet-Vorgabe; dieses Dokument bleibt als abgeschlossener Umsetzungsnachweis erhalten.
- Drei nachvollziehbare Anleitungen liefern: Standardstart mit Ethernet-Zebra, kompletter Stack auf 64-Bit-Pi mit USB und entfernter Pi nur mit ZebraTamer.
- Einrichtung mehrerer Drucker, Medienwechsel, IPP-Freigabe, Labelary-Nutzung, Umgang mit unklarem Ergebnis und bewusster Neudruck erklären.
- Entwickleranleitung mit Git-Submodulen, lokalen Builds, Simulatoren und neuer Druckerdienst-Implementierung erstellen. Echten Niimbot-Treiber ausdrücklich als zukünftige Erweiterung kennzeichnen.
- Backup/Restore, Update, Migration von Fleet, Rollback-Grenzen und unterstützte Host-/CPU-Plattformen dokumentieren. Bestehende Dokumente zu Binaries/Images gegen die Workflows prüfen.
- Ein gemeinsam getestetes Versionsset und das Anwenderpaket veröffentlichungsfertig erstellen. Ein abschließender Installationsdurchlauf benutzt ausschließlich dieses Paket und die darin referenzierten Images.
- Status jedes Arbeitspakets mit Komponentenrevisionen, Prüfbelegen und verbleibenden Einschränkungen aktualisieren. Release nur nach erfüllter Produktabnahme als fertig bezeichnen.

**Ergebnis und Abnahme:** Eine Person ohne Chat-/Repository-Vorwissen kann der Release-Anleitung folgen, einen Drucker einrichten und erfolgreich drucken. Alle erforderlichen Dateien und Images sind verfügbar. Dokumentation beschreibt den tatsächlichen Release-Stand und keine zukünftige Wunschfunktion.

## 7. Verbindliche Produkt-Abnahmematrix

Diese Matrix wird bei AP-17/AP-19 um Datum, exakte Versionen, Ergebnis und Beleg ergänzt. „Nicht geprüft“ ist nicht „bestanden“.

| Prüffall | Erwartetes Ergebnis | Nachweis |
| --- | --- | --- |
| Frischer Standardstart | Vier Produktdienste starten ohne Fleet, Thingdex, Drucker oder Emulator; UI zeigt Einrichtung | AMD64 und ARM64 |
| Erststart auf Pi | UI über dokumentierten Netzwerkweg erreichbar; persistente Einrichtung nach Neustart erhalten | Realer 64-Bit-Pi |
| Ethernet-Zebra | IP/Port in UI anlegen; Template nativ und als Raster ausgeben | Emulator plus reale Hardware |
| USB-Zebra | Eindeutige Auswahl und erforderliche Rechte; Druck und mögliche Abfragen funktionieren | Reale Hardware, lokal oder Pi |
| Entfernte Instanz | Dienst verbinden; URL-Wechsel erhält Druckerzuordnung und Jobhistorie | Integrationstest |
| Zwei gleiche lokale IDs | Keine Kollision zwischen zwei Diensten | Vertragstest |
| Reiner Rasterdrucker | Template und PDF/Bild funktionieren ohne Zebra-Erweiterungen | AP-16-Testdienst |
| Kopien/Mehrseiten | Erwartete Anzahl/Reihenfolge; keine Vermischung mit anderem Auftrag | Simulator und ausgewählte Hardwareprobe |
| Druckmaße | Ziel-DPI, physische Maße, Ausrichtung und Barcode-Lesbarkeit stimmen | Reale Etikettenprüfung |
| Kein Labelary | Native Zebra-/lokale Dokumentpfade funktionieren; benötigtes Template-Rendering meldet klaren Ausfall | Deterministischer Ausfalltest |
| Medien-/Labelkonflikt | A4-zu-Label, Jobgrenze oder veraltete Medienrevision stoppt vor unbeabsichtigter Ausgabe | Integrationstest |
| Drucker offline | Andere Drucker arbeiten weiter; Job bleibt nachvollziehbar wartend/fehlgeschlagen gemäß Policy | Fehlerfalltest |
| Verlorene Annahmeantwort | Dieselbe Kennung ergibt denselben physischen Job | Fehlerfalltest mit Ausgabezählung |
| Abbruch bei Übertragung | Unklarer Ausgang sichtbar; kein automatischer Neudruck | Fehlerfalltest und gezielte Hardwareprobe |
| Neustart mit Queue | Reihenfolge, Idempotenz, Artefakte und Seitenfortschritt erhalten | Crash-/Recovery-Test |
| Pause/Abbruch | Noch nicht ausgegebene Arbeit bleibt gestoppt; aktive Ausgabe wird ehrlich behandelt | Integrationstest |
| TCP-Reconnect | Verbindung erholt sich; kein unbegründeter Rollenverbrauch | Transport-/Medientest |
| IPP ohne Drucker | Gateway gesund ohne Freigabe, spätere Freigabe wirksam | Integrationstest |
| Mehrere IPP-Drucker | Stabile, getrennte Queues; Dokumente erreichen das gewählte Ziel | LAN-Client und ipptool |
| IPP-Status | Hold/Fehler/Abbruch/Übergabe nachvollziehbar, keine erfundene Papierbestätigung | Client- und API-Vergleich |
| Zugriffsschutz | Kein unberechtigter Druck/Admin-/Payloadzugriff; keine Legacy-Umgehung | API-Tests |
| Upgrade/Migration | Alte IDs und Einstellungen erhalten; unklare Altjobs werden nicht ausgesendet | Dry-Run plus Restore-Probe |
| Backup/Restore | Daten/Identitäten wiederherstellbar, alter Schlüssel erzeugt keinen Doppeldruck | Integrationsprobe |
| Öffentliche API | Externer Nutzer kann ohne Thingdex Auftrag senden und Status lesen | API-/SDK-Test |
| Finaler Release-Start | Fertiges Paket nutzt ausschließlich passende Images; kein lokaler Quellbuild erforderlich | Saubere Installationsumgebung |

## 8. Definition von „Refactoring abgeschlossen“

### Implementierungsstand 2026-09-08

| Pakete | Stand | Nachweis / verbleibende Grenze |
| --- | --- | --- |
| AP-00 bis AP-10 | Implementiert und automatisiert geprüft | Inventar und Verträge liegen unter `docs/implementation` bzw. in den Komponenten; Zebra-, Raster-, Persistenz-, Dienstkatalog-, Artefakt-, Cancel-, USB-, Job-, SDK- und Studio-Tests sind grün. |
| AP-11 bis AP-12 | Kanonischer Code implementiert und simuliert geprüft | IPP liegt ausschließlich im PrintHub-Repository; die alte Root-Kopie ist entfernt. Zwei dynamische Queues, Dokumentjobs, dauerhafte IPP-/PrintHub-/Downstream-Zuordnung sowie ein Standard-CUPS-Abbruch bis zum nachgelagerten Job wurden mit `ipptool` geprüft; echter LAN-Client bleibt offen. |
| AP-13 | Implementiert und geprüft | Fleet-Dry-Run sowie prüfsummenverifiziertes Backup/Restore bestehen ihre Tests; unklare Altjobs werden nicht automatisch neu eingereiht. |
| AP-14 | Build-/Releasecode implementiert | Native AMD64-/ARM64-Matrix, SBOM, Scan und Kandidatenpaket sind definiert; ARM64-Runner, Registry-Veröffentlichung und realer Pi wurden in dieser lokalen Abnahme nicht ausgeführt. |
| AP-15 bis AP-16 | Implementiert und lokal abgenommen | Standard-, Demo- und USB-Overlay sind gültig; der isolierte Demo-Stack und neutrale Rasterdienst bestanden Template-, Dokument-, Idempotenz- und Fehlerpfade. |
| AP-17 | Simulatoranteil abgeschlossen | Reale Zebra-, USB-, Pi-, Druckmaß-, Barcode- und LAN-mDNS-Prüfungen bleiben ausdrücklich offen. |
| AP-18 | Implementiert | Fleet/Fleet Console, Laufzeitkopplungen und alte Designvorgabe sind entfernt; Thingdex bleibt nur optionaler API-Nutzer/Submodul. Persistente Altvolumes wurden nicht gelöscht. |
| AP-19 | Dokumentation und Kandidatenpaket implementiert | Installation, Betrieb, Entwicklung, Migration und Release-Kandidat sind beschrieben. Eine kopierte Paketstruktur startete ohne Komponentenquellen und ohne Build; veröffentlichte Archive auf sauberem Zielhost bleiben bis Hardware-/ARM-Abnahme offen. Der vollständige Stand steht in `docs/implementation/COMPLETION_AUDIT_2026-09-08.md`. |

Das Refactoring ist erst abgeschlossen, wenn alle folgenden Bedingungen erfüllt sind:

- [ ] Alle Arbeitspakete sind mit Implementierungsstand und Prüfbelegen abgeschlossen.
- [x] Das Produkt startet aus der Release-Paketstruktur ohne Komponentenquellen und führt durch die Einrichtung.
- [ ] ZebraTamer betreut USB- und Ethernet-Zebras einschließlich vorhandener Gerätekonfiguration und Medienverwaltung.
- [x] Templates, Dokumente und Bilder werden korrekt über die neue Dienstschnittstelle gedruckt.
- [x] Ein reiner Rasterdienst ist ohne Zebra-Sonderbehandlung integriert und getestet; echte Niimbot-Kommunikation bleibt ausdrücklich ausgenommen.
- [x] Gemeinsame Oberfläche und mehrere IPP-Freigaben sind nutzbar und zeigen belastbare Zustände.
- [x] Idempotenz, Wiederanlauf, Medienrevisionen und unklare Druckausgänge sind durch Fehlerfalltests abgesichert.
- [x] Bestehende Daten lassen sich übernehmen und sichern; aktive/unklare Altjobs werden nicht automatisch erneut gedruckt.
- [x] Fleet, Fleet Console, ihre Laufzeitabhängigkeiten und die alte `DESIGN.md` sind entfernt.
- [x] Thingdex ist optionaler API-Nutzer und keine Installations-, Build- oder Startvoraussetzung.
- [ ] AMD64-/ARM64-Images und der vereinbarte Pi-Geräteserverpfad sind geprüft und dokumentiert.
- [ ] Reale USB-/Ethernet-/Pi-/IPP-Abnahmen sind protokolliert oder das Release wird ausdrücklich noch nicht als vollständig abgenommen bezeichnet.
- [ ] Die letzte Installationsprobe verwendet exakt die ausgelieferten Dateien und Images.

## 9. Referenzen für die Umsetzung

- Bestehender Code und die Einstiegspunkte aus Abschnitt 3 sind die Grundlage für die Übernahme vorhandenen Verhaltens.
- [Labelary API](https://labelary.com/service.html): unterstützte Renderingparameter, Ausgabeformate und Grenzen. Bei Umsetzung die dann aktuellen Angaben prüfen; keine hier festgeschriebene Annahme über Preise oder Limits.
- [CUPS ippeveprinter](https://openprinting.github.io/cups/doc/man-ippeveprinter.html): bisheriger IPP-Server und dessen Einbindung. Der vorhandene Einsatz beweist nicht automatisch Eignung für AP-12.
- Neue Laufzeitverträge und Anwenderanleitungen müssen beim Abschluss die tatsächliche Implementierung beschreiben. Historische Fleet-Dokumentation darf keine widersprechende Vorgabe für neue Arbeitspakete bleiben.
