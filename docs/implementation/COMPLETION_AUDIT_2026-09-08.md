# Abschluss-Audit des Fleet-freien Refactorings

Stand: 2026-09-08

Dieser Bericht ordnet jedes Arbeitspaket aus
`docs/REFACTORING_ARBEITSPAKETE.md` dem tatsächlich vorhandenen Ergebnis zu.
Er unterscheidet zwischen **implementiert**, **lokal abgenommen** und
**extern offen**. Ein Hardwaretest wird nicht durch einen Simulator ersetzt.

## Geprüfter Quellstand

Die Umsetzung liegt als noch nicht commitierter Arbeitsstand auf folgenden
Ausgangsrevisionen:

| Repository | Ausgangsrevision |
| --- | --- |
| Labeldrucker | `ce0f45fa513ef347ad555ee5a61cc93fd9bd65c7` |
| PrintHub | `1f1faa4f4e5ff2c2abf5ac526f14c5ebadba8a2c` |
| PrintHub SDK | `30c4f1ecd5e4eb550fa4bc31564ae9582aa9892b` |
| LabelArchitect | `d5a9044b20c6aff039a4800e4c52df44250fe9d8` |
| ZebraTamer | `931d93adccc9f804a5de62332e6f0b535a6a97a7` |
| Zebra-Emulator | `52e79270852238ed0b5381f400f2f4e548921666` |

Unabhängige, bereits vorher vorhandene Änderungen im Root-Worktree wurden
nicht zurückgesetzt oder überschrieben.

## Arbeitspakete

| AP | Implementiertes Ergebnis | Abnahme und Restgrenze |
| --- | --- | --- |
| 00 | Ausgangszustand, Datenquellen und Funktionsersatz sind in `BASELINE_2026-09-08.md` festgehalten. | Abgeschlossen. |
| 01 | Versionierter Druckerdienstvertrag v2, JSON-Schemas, positive/negative Fixtures, Zebra- und Rasterbeispiele sowie OpenAPI-/SDK-Abbildung. | Vertrags-, Adapter- und SDK-Tests grün. |
| 02 | ZebraTamer besitzt haltbare FIFO-Queues, atomare Persistenz, Idempotenz, Prozesssperre, Recovery, Pause und sicheren Abbruch. Queue-Änderungen werden vor Bestätigung gespeichert; ohne haltbaren `writing`-Zustand beginnt kein Hardware-I/O. Fehlgeschlagene atomare Writes erhalten den alten Stand. PrintHub beansprucht Jobs vor Dispatch atomar. | Rust- und Fehlerfalltests einschließlich mehr als 200 Recovery-Jobs grün. Echte Datenträgererschöpfung bleibt ein Betriebs-/Hardwaretest. |
| 03 | ZebraTamer unterstützt bidirektionales TCP mit Port 9100, Zeit-/Größenlimits, vollständigem Schreiben, getrennten Query-Sessions und Reconnect. | Kontrollierte TCP-Tests grün; realer Ethernet-Zebra offen. |
| 04 | ZebraTamer akzeptiert neutrales Raster v1, validiert Profil/Abmessungen/Padding/Prüfsumme und kodiert Zebra-Grafik ohne erneutes Layout oder Dithering. | Raster-, Mehrseiten- und Kopierreihenfolgetests grün; Papierbild offen. |
| 05 | Drucker können persistent per API, ZebraTamer-UI und Studio angelegt/geändert/deaktiviert werden. TCP und USB, Medienrevisionen, Gerätekonfiguration, Queue-Steuerung und drei Zebra-Wartungsaktionen sind angebunden. | Neustart-, API- und UI-Buildtests grün. USB-Erkennung liefert auf dem Testhost korrekt eine leere Liste; zwei reale gleiche USB-Geräte offen. |
| 06 | Gemeinsame v2-API mit stabiler `service_id`, Read/Print/Admin-Scopes, geschützter Legacy-API, begrenzten Eingaben und Zebra-Erweiterungsnamespace. | Autorisierungs- und Vertragstests grün; Remote-LAN-Abnahme offen. |
| 07 | PrintHub verwaltet mehrere Dienstverbindungen, stabile öffentliche Drucker-IDs, URL-/Identitätsprüfung, Anzeigenamen, Sichtbarkeit, Standarddrucker, Offline-Snapshots und doppelte Seriennummernkonflikte. | Persistenz nach Neustart und Konflikt-/URL-Wechseltests grün. |
| 08 | PrintHub speichert aufgelöste Eingaben und unveränderliche Artefakte. Zebra erhält standardmäßig ZPL, kann in Studio aber ausdrücklich als vollständiges Labelbild gewählt werden; reine Rasterdienste erhalten automatisch Labelary-Raster. Dokument/Bild läuft lokal über dieselbe Rasterpipeline. Das Ausgabeformat gehört zur Idempotenzprüfung. | Native, erzwungene Zebra-Raster- und Rasterdiensttests sowie E2E-Jobs grün. Live-Labelary wurde benutzt; die deterministischen Vergleichsmatrizen bleiben im normalen Lauf optional. |
| 09 | Haltbarer Hintergrundworker, stabile Dispatch-Kennung, Retry/Lookup, Dienst-/Job-Zuordnung, Status-Reconciliation, Hold, Cancel, expliziter Reprint und sichere Recovery sind vorhanden. | Unit-/Integrationstests und E2E-Idempotenz grün. Physischer Teiltransfer bleibt Hardwareabnahme. |
| 10 | Studio enthält Druckerdienst-, Drucker-, Medien-, USB-, Queue-, Wartungs-, IPP- und Jobverwaltung. Rasterziele verwenden den normalen Druckablauf; Cancel läuft über den SDK. | Architekturtests, Typecheck und Produktionsbuild grün. Manuelle Browser-Usability mit neuer Person offen. |
| 11 | Der kanonische IPP-Code liegt ausschließlich im PrintHub-Repository und wird von Compose, CI und Imageworkflow als eigenes Image gebaut. Die alte Root-Kopie ist entfernt. | 21 Tests, Imagebuild und Root-Pfadsuche grün. |
| 12 | Ein Gateway verwaltet null bis zwanzig dynamische, stabile Queues, aktualisiert Fähigkeiten, unterstützt direkte URIs und mDNS, übergibt Dokumente an PrintHub und persistiert IPP-ID/UUID ↔ PrintHub-/Downstream-ID atomar. Der IPP-Helfer bleibt ohne künstliche Produktionsfrist aktiv, aktualisiert das Mapping bei jedem Poll, meldet einen noch aktiven Job niemals als abgeschlossen und leitet SIGTERM sowie den von `ippeveprinter` nur als `processing-to-stop-point` gemeldeten Client-Abbruch an PrintHub weiter. | Zwei Queues, Capability-Probe, erfolgreicher IPP-Rasterjob, begrenzter Timeout ohne Falschabschluss und ein Standard-CUPS-Abbruch bis zum nachgelagerten ZebraTamer-Job sind grün. Echter OS-/LAN-Client, mDNS und Abbruch während realer Ausgabe offen. |
| 13 | Wiederholbarer Fleet-Dry-Run/Export sowie prüfsummenverifiziertes Backup/Restore für Produktdaten sind vorhanden; unklare Altjobs werden nur berichtet. | Werkzeugtests grün. Produktive Altinstallation muss vor ihrem Cutover separat gesichert und geprüft werden. |
| 14 | AMD64-/ARM64-Kandidatenmatrix für vier Images, SBOM, Scan, exakte Imagearchive, ARMv7-Cross-Binary und ZebraTamer-Binary-Releasepfad sind definiert. | Lokale AMD64-Images bauen/starten. ARM64-/ARMv7-Runner und Registry-Veröffentlichung können nur im Remote-CI bzw. auf Zielhardware abgenommen werden. |
| 15 | Fleet-freie Basis-Compose, Demo- und USB-Overlay, automatisch persistierte Secrets, leere Ersteinrichtung und entfernter ZebraTamer sind vorhanden. | Kopiertes Produktverzeichnis ohne Komponentenquellen startete alle vier Dienste mit `--no-build` gesund. ARM64-Zielhost offen. |
| 16 | Raster-only-Testdienst implementiert denselben Vertrag ohne Zebra-/Niimbot-Sonderfälle und speichert prüfbare PNG-Ausgaben. | Template- und Dokumentpfad sowie Konformitäts-/Fehlerfälle grün. |
| 17 | Automatisierte Gesamtintegration baut den Fleet-freien Demo-Stack, konfiguriert Medien/IPP, druckt und zählt reale Simulatorausgaben. Hardware-Abnahmeplan ist dokumentiert. | Simulatoranteil abgeschlossen. Reale Ethernet-/USB-/Pi-/Druckmaß-/Barcode-/LAN-Prüfungen ausdrücklich offen. |
| 18 | Fleet, Fleet Console, Laufzeitkopplungen, Secrets/Compose/CI-Pfade und alte Designvorgabe sind entfernt; Thingdex ist optional. | Laufzeitsuche und Demo-Stack sind Fleet-frei. Historische Migrationsbegriffe bleiben absichtlich. |
| 19 | Architektur, Installation, Betrieb, Entwicklung, Release, Migration und Abnahme sind dokumentiert. Das Releaseworkflow paketiert Konfiguration, Remote-Pi-Beispiele, Werkzeuge, Dokumentation und exakt getestete Imagearchive. | Release-Paketstart lokal grün. Produktionsfreigabe bleibt bis zur externen Hardware-/ARM-Abnahme gesperrt. |

## Lokale Prüfergebnisse

- ZebraTamer: `cargo fmt -- --check`, 35 von 35 Tests bestanden.
- PrintHub einschließlich IPP: 155 bestanden, 159 optionale
  Labelary-Vergleichsfälle übersprungen.
- PrintHub SDK: 3 von 3 Tests, generiertes Schema, Typecheck und Build bestanden.
- Studio: 2 von 2 Architekturtests, Typecheck und Produktionsbuild bestanden.
- Produktwerkzeuge: 3 von 3 Migrations-/Backup-Tests bestanden.
- Workflow-YAML sowie Basis-, Demo- und USB-Compose lassen sich vollständig
  parsen.
- Kandidatenimages für PrintHub, Studio, ZebraTamer, IPP, Rastertestdienst und
  virtuellen Zebra wurden lokal gebaut; Basis- und Demo-Stack wurden gesund.
- Der ausführliche Lauf mit Job-IDs und offenem Hardwareanteil steht in
  `docs/acceptance/REFACTORING_2026-09-08.md`.

## Vor einer Produktionsfreigabe zwingend offen

1. ARM64-Imagejobs und ARMv7-Binaryjob im Remote-CI erfolgreich ausführen und
   die erzeugten Artefakte auf sauberer Zielhardware prüfen.
2. Reale Ethernet- und USB-Zebra-Abnahme einschließlich Rückkanal,
   Teilübertragung, Maße, Barcode, Kopien und Medienverbrauch durchführen.
3. Zwei IPP-Queues von mindestens einem echten Betriebssystem-/LAN-Client
   installieren; Discovery, Hold, Cancel und Status mit PrintHub vergleichen.

Bis diese externen Punkte belegt sind, ist der Stand ein benutzbarer,
simulatorgetesteter Release-Kandidat und kein hardwarezertifizierter
Produktionsrelease.
