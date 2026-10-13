# Funktionsinventar und Anforderungen für einen Neuaufbau

Stand der Analyse: 12. September 2026

Dieses Dokument beschreibt die im Workspace vorhandenen Repositories als fachliche und technische Anforderungen. Es ist so formuliert, dass ein neues Implementierungsteam das System anhand der beschriebenen Fähigkeiten, Regeln, Schnittstellen und Betriebsanforderungen neu entwickeln könnte.

## 1. Analysierter Umfang

| Repository / Verzeichnis | Analysierter Commit | Rolle |
| --- | --- | --- |
| `Labeldrucker` | `f229723` | Produktzusammenbau, Deployment, Betrieb und Release-Orchestrierung |
| `components/LabelArchitect` | `0211dc3` | PrintHub Studio: Weboberfläche für Templates, Designer, Drucker und Jobs |
| `components/printhub-sdk` | `a896c7b` | Typisierter TypeScript-Client für PrintHub |
| `components/PrintHub-ZPL-ll` | `303bcf5` | Template-, Render-, Job-, Druckerkatalog- und IPP-Orchestrierung |
| `components/Thingdex` | `a1f8483` | Inventar-Backend und optionale automatische Label-Anbindung |
| `components/Thingdex-Home-Inventory` | `a07c133` | Historisches Übersichts- und Entwicklungs-Orchestrierungs-Repository |
| `components/ZebraTamer` | `043e91a` | PrintAgent für Zebra-Drucker und physische Druckwarteschlangen |
| `components/ZPL-II-Printer-Emulator` | `52e7927` | Virtueller RAW-TCP-ZPL-Drucker für Entwicklung und Tests |

Nicht im Workspace enthalten, aber in historischen Dokumenten erwähnt, sind unter anderem `ThingdexUI`, `thingdex-sdk`, `LabelGallery` und `PrinterFleet`. Ihre dort beschriebenen Fähigkeiten werden nicht als aktuell implementierte Funktionen gewertet.

### Anforderungsbegriffe

- **MUSS** bezeichnet beobachtetes, tragendes Produktverhalten oder eine wichtige Invariante.
- **SOLL** bezeichnet vorhandenes Verhalten, das für funktionale Gleichwertigkeit übernommen werden sollte.
- **KANN** bezeichnet optionale Integrationen, Entwicklungsfunktionen oder bewusst abschaltbare Fähigkeiten.
- Angaben unter „Nicht Bestandteil“ verhindern, dass historische oder fremde Verantwortlichkeiten versehentlich in den Neuaufbau einfließen.

## 2. Gesamtprodukt: fachliches Zielbild

Das Kernprodukt ist ein eigenständig nutzbares System zum Entwerfen, Rendern und Drucken von Etiketten. Es trennt die inhaltliche Druckorchestrierung von der physischen Geräteansteuerung:

1. PrintHub Studio stellt die Benutzeroberfläche bereit.
2. PrintHub speichert Templates und logische Druckjobs, rendert Inhalte und verwaltet einen öffentlichen Druckerkatalog.
3. Ein Print-Service wie ZebraTamer besitzt die physischen Drucker, Geräteeinstellungen, Medieninformationen und die tatsächliche Warteschlange.
4. Ein IPP-Gateway macht ausgewählte PrintHub-Drucker für Betriebssysteme erreichbar.
5. Thingdex kann als unabhängiges Inventarsystem optional Druckaufträge an PrintHub übergeben.

### Systemweite Muss-Anforderungen

- Das Etikettendruckprodukt MUSS ohne Thingdex lauffähig sein.
- PrintHub MUSS ohne externe Datenbank und ohne direkt angeschlossene Hardware nutzbar sein.
- Browsercode DARF keine Geräte- oder Print-Service-Zugangsdaten enthalten.
- Logische Jobs und physische Jobs MÜSSEN getrennte Identitäten und Zustände besitzen.
- Ein erfolgreich übertragener Datenstrom darf nur als `transport_accepted` gelten; er darf nicht als physisch beobachteter Ausdruck ausgegeben werden.
- Ein unbekannter physischer Ausgang DARF nicht automatisch erneut gedruckt werden.
- Wiederholungen MÜSSEN idempotent sein. Derselbe Schlüssel mit geändertem Inhalt MUSS als Konflikt abgelehnt werden.
- Das exakte, unveränderliche Ausgabeartefakt MUSS vor der Übergabe an einen Print-Service gespeichert werden.
- Jeder Print-Service MUSS eine stabile Service-Identität besitzen. Die öffentliche Drucker-ID MUSS aus Service-Verbindung und lokaler Drucker-ID kollisionsfrei ableitbar sein.
- Native ZPL-Drucker SOLLEN ZPL erhalten; reine Rasterdienste MÜSSEN das neutrale einfarbige PrintHub-Rasterformat erhalten.
- Drucker, Medien, Warteschlangen und Gerätestatus MÜSSEN dem jeweiligen Print-Service gehören; Templates und logische Jobs MÜSSEN PrintHub gehören.

## 3. Repository `Labeldrucker`

### 3.1 Zweck

Das Root-Repository ist das installierbare Produktpaket. Es bindet die Kernkomponenten als Git-Submodule ein, definiert die Produktions- und Demoprofile und enthält Betriebs-, Migrations-, Backup-, Release- und Abnahmewerkzeuge.

### 3.2 Produktstart und Dienste

Der Neuaufbau MUSS einen reproduzierbaren Start mit Docker Compose ermöglichen. Das Standardprofil umfasst:

- einen einmaligen Bootstrap-Dienst zur Secret-Erzeugung;
- ZebraTamer als Print-Service;
- PrintHub als API und Orchestrator;
- PrintHub Studio als Weboberfläche;
- das IPP-Gateway;
- getrennte persistente Volumes für PrintHub-Daten, ZebraTamer-Daten, Secrets, IPP-Spool und IPP-TLS-Daten.

Das System MUSS beim ersten Start kryptografisch zufällige, restriktiv gespeicherte Tokens erzeugen, wenn sie noch nicht vorhanden sind. Bestehende Tokens dürfen bei einem Neustart nicht überschrieben werden.

Standardmäßig MÜSSEN Webports an Loopback gebunden sein:

- Studio auf Port `8088`;
- PrintHub API auf Port `8001`;
- ZebraTamer UI/API auf Port `8082`;
- IPP-Queues im Bereich `8631–8650`.

### 3.3 Netzwerk- und Sicherheitsmodell

- Das interne Backend-Netz MUSS ohne allgemeinen externen Netzwerkzugriff betrieben werden.
- Nur PrintHub DARF für optionale Labelary-Aufrufe ein separates Egress-Netz erhalten.
- Container SOLLEN ohne zusätzliche Linux-Capabilities, mit `no-new-privileges` und soweit möglich schreibgeschütztem Root-Dateisystem laufen.
- Secrets MÜSSEN über Dateien oder Secret-Volumes injiziert werden können.
- Admin-Token und Print-Service-Token MÜSSEN getrennt sein.
- Studio DARF kein Token in das ausgelieferte JavaScript kompilieren.

### 3.4 Betriebsprofile

- Das Standardprofil MUSS einen leeren, sicheren Erststart unterstützen, in dem Drucker nachträglich über Studio angelegt werden.
- Ein Demoprofil SOLL einen virtuellen RAW-9100-Zebra-Drucker und einen raster-only Konformitätsdienst ergänzen.
- Ein USB-Profil SOLL ZebraTamer mit einem durchgereichten USB-Gerät und eigener Konfiguration starten können.
- Ein Remote-ZebraTamer-Profil SOLL den Betrieb des Print-Service auf einem separaten Raspberry Pi erlauben.
- AMD64 und ARM64 MÜSSEN als Zielplattformen unterstützt werden; für Raspberry Pi sind native Installationen und Containerbetrieb dokumentiert.

### 3.5 Betrieb, Sicherung und Migration

- Ein Backup-Werkzeug MUSS mehrere benannte Datenquellen in ein Archiv aufnehmen, Prüfsummen erzeugen und eine Wiederherstellung unterstützen.
- Eine Wiederherstellung MUSS unsichere Pfade im Archiv abweisen und darf vorhandene Ziele nicht still überschreiben.
- Das gesamte persistente Datenverzeichnis eines Dienstes MUSS zusammen sicherbar sein, da IDs, Tokens, Jobs und Medienhistorie gemeinsam konsistent bleiben müssen.
- Das Fleet-Migrationswerkzeug SOLL ältere SQLite- oder JSON-Daten lesen und einen versionierten Migrationsplan erzeugen.
- Drucker-IDs und historische Auslieferungen SOLLEN bei der Migration erhalten bleiben.
- Unsichere oder unbekannte frühere Jobausgänge DÜRFEN durch eine Migration nicht erneut in eine aktive Warteschlange gelangen.

### 3.6 Qualität und Release

- Das Repository MUSS komponentenübergreifende Container-Smoke-Tests ausführen können.
- Security-Scans MÜSSEN hoch priorisierte, behebbar erkannte Funde blockieren können.
- Release-Skripte MÜSSEN Branch-, Tag- und Commit-Kontext validieren.
- Release-Artefakte SOLLEN unveränderliche Commit-/Run-bezogene Tags, SBOMs und Provenance-Attestierungen erhalten.
- Hardwarefreie End-to-End-Abnahmen und reale USB-Hardwareabnahmen SOLLEN separat dokumentiert werden.

## 4. Repository `PrintHub-ZPL-ll` – PrintHub

### 4.1 Zweck und Datenhoheit

PrintHub ist der zentrale Dienst für:

- gespeicherte Label-Templates;
- Templatevalidierung und Layoutberechnung;
- ZPL- und PNG-Rendering;
- kurzlebige Druckentwürfe;
- dauerhafte logische Druckjobs und unveränderliche Artefakte;
- öffentliche Druckerprojektion über mehrere Print-Services;
- IPP-Freigaben;
- Statusereignisse an optionale Integrationen.

PrintHub DARF keine Zebra-spezifischen Transportzugänge im Browser offenlegen und SOLL keine physische Gerätewarteschlange selbst besitzen.

### 4.2 Template-Modell

Ein Template MUSS die Schema-Version `1` verwenden und aus einem rekursiven Layoutbaum bestehen:

- Ein `split`-Knoten MUSS genau zwei Kinder besitzen.
- Ein Split MUSS horizontal oder vertikal ausgerichtet sein.
- Ein Split MUSS ein Verhältnis, optionalen Abstand (`gutter_mm`) und optionalen sichtbaren Divider mit Dicke unterstützen.
- Ein `leaf`-Knoten MUSS genau ein Element enthalten.
- Ein Leaf MUSS Padding, Debug-Rahmen und einen Alias unterstützen.
- Hintergründe SOLLEN auf Root-, Split- und Leaf-Knoten möglich sein.

Unterstützte Elementtypen:

- Text;
- QR-Code;
- DataMatrix-Code;
- Bild;
- Linie.

Alle geometrischen Angaben MÜSSEN in Millimetern erfolgen. Das v1-Format unterstützt keine frei drehbaren Layoutelemente.

### 4.3 Text- und Variablenverarbeitung

- Platzhalter MÜSSEN in der Form `{name}` unterstützt werden.
- Doppelte Klammern `{{` und `}}` MÜSSEN als Literale behandelbar sein.
- Fehlende Variablen MÜSSEN abhängig von der Renderoption strikt abgelehnt oder leer ersetzt werden können.
- Zeit- und Zähler-Makros wie `_now_iso` und templatebezogene Counter SOLLEN verfügbar sein.
- Zähler MÜSSEN persistent und gegen konkurrierende Verwendung geschützt sein.
- Text MUSS Wortumbruch, Zeichenumbruch, Abschneiden, Überlauf und Shrink-to-fit abbilden können.
- Maximale Zeilenzahl, horizontale und vertikale Ausrichtung sowie ZPL-Schriftparameter MÜSSEN berücksichtigt werden.
- Unicode/ZPL-UTF-8-Nutzung MUSS korrekt gekennzeichnet werden; nicht zuverlässig darstellbare Glyphen SOLLEN Diagnosen erzeugen.
- Offline-Textmessung MUSS deterministisch funktionieren; Labelary darf für korrekte Grundfunktion keine Pflicht sein.

### 4.4 2D-Codes und Bilder

- QR und DataMatrix MÜSSEN native ZPL-Ausgabe unterstützen.
- Die größtmögliche passende Symbolgröße MUSS anhand des verfügbaren Bereichs bestimmt werden können.
- Ausrichtung MUSS die tatsächliche Tintenfläche und ZPL-Offets berücksichtigen.
- Optional SOLLEN QR/DataMatrix als Rasterbild erzeugt werden können.
- Bilder MÜSSEN als eingebettetes Base64-Material unterstützt werden.
- Bild-URLs DÜRFEN nur über ein explizites Feature-Flag aktiviert werden.
- Bildskalierung, Positionierung und Hintergrundbilder MÜSSEN mit den Template-Defaults zusammenspielen.

### 4.5 Rendering

PrintHub MUSS folgende Renderziele unterstützen:

- ZPL als JSON-Antwort;
- PNG als Binärantwort;
- Zielbreite und Zielhöhe in Millimetern;
- DPI, standardmäßig passend zum ZPL-Drucker;
- X-/Y-Ursprungsversatz;
- Debug-Rendering.

Rendering MUSS strukturierte Diagnosen mit Code, Nachricht, Schweregrad und – soweit verfügbar – Element-ID, Leaf-Alias sowie tatsächlicher/maximaler Zeilenzahl liefern.

Labelary MUSS optional und standardmäßig deaktivierbar sein. PNG-Rendering über Labelary und Template-Previews dürfen separat schaltbar sein.

### 4.6 Template-Speicher

- Templates MÜSSEN neu angelegt, aufgelistet, geladen und aktualisiert werden können.
- Eine Template-ID MUSS eine sichere Slug-ID sein; pfadähnliche IDs MÜSSEN abgelehnt werden.
- Pro Template MÜSSEN Name, Tags, Variablendefinitionen, Template-JSON, Sample-Daten und Preview-Ziel gespeichert werden.
- Listen MÜSSEN nach Tags filterbar sein.
- Ein Template SOLL eine PNG-Vorschau bereitstellen, sofern Preview-Rendering verfügbar ist.
- Mitgelieferte Templates SOLLEN beim ersten Start ergänzt werden, ohne Benutzeränderungen zu überschreiben.

### 4.7 Druckentwürfe

- Ein Draft MUSS Template, aufgelöste Variablen, Zielgröße und Debug-Flag speichern.
- Ein Draft MUSS eine eindeutige ID und ein Ablaufdatum besitzen.
- Studio oder andere Clients MÜSSEN den Draft über die ID laden und in einen Druckdialog überführen können.

### 4.8 Logische Druckjobs

PrintHub MUSS drei Eingabearten unterstützen:

1. gespeichertes oder inline geliefertes Template;
2. bereits vorbereitete Rasterseiten;
3. Dokumente in PDF, PostScript, PNG, JPEG, PWG Raster oder Apple Raster.

Für Templatejobs gilt:

- Genau eine Templatequelle – `template_id` oder Inline-Template – MUSS angegeben sein.
- Variablen, Renderziel und gewünschter Ausgabemodus MÜSSEN Bestandteil des Jobs sein.
- Das Template und die aufgelösten Variablen MÜSSEN als unveränderlicher Snapshot erhalten bleiben.
- Der Ausgabemodus MUSS `auto`, native ZPL oder vollständiges Label-Raster unterscheiden können.

Für Raster- und Dokumentjobs gilt:

- Mehrseitige Jobs und mehrere Kopien MÜSSEN unterstützt werden.
- Die Anzahl physischer Labels MUSS als Seiten × Kopien berechnet werden.
- Ein konfigurierbares Joblimit MUSS vor der Geräteübergabe greifen.
- Eine Überschreitung MUSS einen Hold erzeugen; eine bewusste administrative Freigabe darf das Limit übersteuern.
- Größenabweichungen MÜSSEN vor dem Versand erkannt werden.
- Die Richtlinien `hold`, `fit` und `fill` MÜSSEN explizit auswählbar sein.
- Vertauschte Seitenabmessungen SOLLEN automatisch durch 90-Grad-Drehung passend gemacht werden.
- Quellpixel- und Payloadgrenzen MÜSSEN vor teurer Dekodierung geprüft werden.
- Dithering und Inhaltsoptimierung MÜSSEN als explizite Optionen modelliert werden.

### 4.9 Jobzustände, Persistenz und Wiederholung

- Jobs MÜSSEN dauerhaft gespeichert werden, bevor ein Print-Service aufgerufen wird.
- Ein Hintergrundworker MUSS wartende und auf einen Service wartende Jobs nach einem Neustart wieder aufnehmen.
- Die Wiederherstellung DARF nicht auf die Anzahl der in der UI angezeigten Jobs begrenzt sein.
- Ein Job MUSS seine Versuche, Bytes, Warnungen, Hold-Grund, Fehler und downstream Jobs ausweisen.
- Mehrseitige beziehungsweise mehrfach ausgelieferte Jobs MÜSSEN jeden downstream Zustand einzeln und einen aggregierten Gesamtzustand zeigen.
- Ein Job im nachgewiesenen Fehlerzustand MUSS wiederholbar sein.
- Ein noch nicht versendeter Job MUSS abbrechbar sein.
- Ein unbekannter Ausgang MUSS eine gesonderte, explizit bestätigte Neuauflage aus dem gespeicherten Artefakt erfordern.
- Eine Neuauflage MUSS einen neuen logischen Job und einen neuen Idempotenzschlüssel erzeugen.
- Verlorene HTTP-Antworten MÜSSEN mit demselben downstream Idempotenzschlüssel abgeglichen werden, statt erneut physisch zu drucken.

### 4.10 Print-Service-Verzeichnis und öffentlicher Druckerkatalog

- PrintHub MUSS mehrere Print-Services verwalten können.
- Eine Serviceverbindung MUSS Anzeigename, Basis-URL, Token, Aktivstatus und erwartete stabile Service-ID speichern.
- Das Anlegen und Ändern einer Verbindung MUSS die entfernte Identität prüfen.
- Ein Identitätswechsel an einer bestehenden Verbindung MUSS abgelehnt werden.
- Tokens MÜSSEN getrennt von der öffentlichen Druckerprojektion gespeichert werden und dürfen nie in API-Antworten erscheinen.
- Der Katalog MUSS bei Serviceausfall zuletzt bekannte Druckerdaten als offline/cached anzeigen können.
- Zwei Services dürfen gleich benannte lokale Drucker bereitstellen, ohne ID-Kollision.
- Dieselbe physische Seriennummer, die gleichzeitig über mehrere Services angeboten wird, MUSS als Konflikt blockiert werden.
- Benutzerpräferenzen wie Anzeigename, Sichtbarkeit und Standarddrucker MÜSSEN Neustarts überleben.
- Der Dienst MUSS Drucker je nach akzeptierten MIME-Typen als ZPL+Raster oder raster-only behandeln.

Administrative PrintHub-Funktionen MÜSSEN per Bearer-Token geschützt sein:

- Service hinzufügen, umbenennen, URL/Token ändern, aktivieren/deaktivieren;
- öffentlichen Druckernamen, Sichtbarkeit und Standarddrucker ändern;
- Zebra-Drucker über eine Service-Erweiterung anlegen;
- USB-Geräte eines Print-Service erkennen;
- neue Medien laden;
- Warteschlange pausieren/fortsetzen;
- Wartungsaktionen auslösen.

### 4.11 IPP

- PrintHub MUSS eine persistente Registry von IPP-Freigaben besitzen.
- Eine Freigabe MUSS Queue-ID, Anzeigename, Ziel-Drucker, Aktivstatus, Port und Resource-Pfad besitzen.
- Portzuordnungen MÜSSEN über Neustarts stabil bleiben.
- Das separate IPP-Gateway MUSS mit null oder mehreren Freigaben gesund starten.
- Das Gateway MUSS Freigaben beobachten und seine Listener dynamisch aktualisieren.
- Geänderte Medienfähigkeiten MÜSSEN in der Queue sichtbar werden.
- Direkte IPP-URIs MÜSSEN auch ohne funktionierendes mDNS nutzbar sein.
- mDNS/DNS-SD SOLL optional angeboten werden.
- IPP-Submission MUSS das Originaldokument mit einem haltbaren, aus dem IPP-Job abgeleiteten Idempotenzschlüssel an PrintHub senden.
- Lang laufende Jobs MÜSSEN nach kurzer IPP-Rückmeldung sicher in PrintHub weiterlaufen.

### 4.12 Integrationsereignisse

- PrintHub SOLL Zustandsänderungen für einen Thingdex-Ursprung in einer eigenen Outbox speichern.
- Ereignisse MÜSSEN deterministische IDs und monotone Sequenzen verwenden.
- Die HTTP-Nutzlast MUSS exakt mit HMAC-SHA256 signiert werden.
- Zustellung MUSS unabhängig vom Druckrequest wiederholt werden können.
- Ein terminal fehlgeschlagenes Event darf nicht verloren gehen und MUSS administrativ untersuchbar bleiben.

### 4.13 Öffentliche HTTP-API

Die folgende API ist im exportierten OpenAPI-Vertrag vorhanden und muss bei einem kompatiblen Neuaufbau semantisch erhalten bleiben:

| Methode | Pfad | Funktion |
| --- | --- | --- |
| `GET` | `/health` | Dienstzustand |
| `POST` | `/v1/renders/zpl` | Template nach ZPL rendern |
| `POST` | `/v1/renders/png` | Template nach PNG rendern |
| `POST` | `/v1/drafts` | Druckentwurf anlegen |
| `GET` | `/v1/drafts/{draft_id}` | Druckentwurf laden |
| `POST` | `/v1/print-jobs` | Templatejob erzeugen |
| `GET` | `/v1/print-jobs` | Jobs auflisten |
| `POST` | `/v1/print-jobs/raster` | Rasterjob erzeugen |
| `POST` | `/v1/print-jobs/documents` | Dokumentjob erzeugen |
| `GET` | `/v1/print-jobs/{job_id}` | Job und downstream Zustand laden |
| `POST` | `/v1/print-jobs/{job_id}/release` | Hold mit Skalierungsentscheidung freigeben |
| `POST` | `/v1/print-jobs/{job_id}/retry` | nachgewiesenen Fehler wiederholen |
| `POST` | `/v1/print-jobs/{job_id}/cancel` | noch abbrechbaren Job stoppen |
| `POST` | `/v1/print-jobs/{job_id}/reprint` | bewussten neuen Job aus Artefakt erzeugen |
| `POST` | `/v1/templates` | Template speichern |
| `GET` | `/v1/templates` | Templates auflisten/filtern |
| `PUT` | `/v1/templates/{template_id}` | Template aktualisieren |
| `GET` | `/v1/templates/{template_id}` | Template laden |
| `GET` | `/v1/templates/{template_id}/preview` | Templatevorschau laden |
| `GET` | `/v1/printers` | öffentlichen Druckerkatalog laden |
| `GET` | `/v1/printers/{printer_id}` | Druckerdetails laden |
| `GET` | `/v1/ipp-shares` | IPP-Freigaben laden |
| `PUT/PATCH` | `/v1/ipp-shares/{queue_id}` | IPP-Freigabe anlegen oder aktivieren/deaktivieren |
| `GET/POST` | `/v1/printer-services` | Print-Services auflisten/anlegen |
| `PATCH` | `/v1/printer-services/{connection_id}` | Service ändern |
| `PATCH` | `/v1/printers/{printer_id}/catalog` | öffentliche Druckerpräferenzen ändern |
| `POST` | `/v1/printer-services/{connection_id}/printers/{printer_id}` | Zebra-Drucker beim Service speichern |
| `GET` | `/v1/printer-services/{connection_id}/usb-devices` | USB-Geräte erkennen |
| `PUT` | `/v1/printer-services/{connection_id}/printers/{printer_id}/media` | Medium laden |
| `POST` | `/v1/printer-services/{connection_id}/printers/{printer_id}/queue/{action}` | Queue steuern |
| `POST` | `/v1/printer-services/{connection_id}/printers/{printer_id}/maintenance/{action}` | Wartung auslösen |

## 5. Repository `printhub-sdk`

### 5.1 Zweck

Das SDK ist ein privates, versioniertes TypeScript-Paket, das den eingecheckten PrintHub-OpenAPI-Vertrag in typsichere Clientfunktionen überführt. Es ist die primäre Integrationsschicht für PrintHub Studio.

### 5.2 Anforderungen

- Das SDK MUSS vollständig aus dem synchronisierten OpenAPI-Dokument generierbare Typen enthalten.
- Generierter Code und handgeschriebene Komfort-Clients MÜSSEN getrennt bleiben.
- Die Konfiguration MUSS mindestens Basis-URL, optionalen eigenen `fetch` und zusätzliche Header unterstützen.
- URL-Pfade und Queryparameter MÜSSEN sicher kodiert beziehungsweise von `undefined`-Werten bereinigt werden.
- Nicht erfolgreiche Antworten MÜSSEN als `PrinthubApiError` mit HTTP-Status, verständlicher Nachricht und optionalem strukturiertem Detail propagiert werden.
- Binärantworten wie PNG-Vorschauen MÜSSEN als `Blob` geliefert werden.
- Base64url-kodierte Renderdiagnosen im HTTP-Header MÜSSEN dekodiert werden können.
- Das Paket MUSS Source Maps und TypeScript-Deklarationen erzeugen.
- CI MUSS sicherstellen, dass generierte Artefakte zum OpenAPI-Vertrag passen und der Build auf unterstützten Node-Versionen funktioniert.

### 5.3 Öffentliche Clientbereiche

- `drafts.create()` und `drafts.get()`;
- `templates.list()`, `get()`, `create()`, `update()` und `getPreview()`;
- `renders.renderZpl()`, `renderPng()` und `renderPngDetailed()`;
- `printJobs.list()`, `get()`, `create()`, `createRaster()`, `createDocument()`, `release()`, `retry()` und `cancel()`;
- `printers.list()` und `printers.get()`.

Administrative Funktionen, die Studio derzeit direkt per HTTP aufruft, sind nicht vollständig als Komfort-Client abgebildet. Für einen Neuaufbau SOLLTEN diese entweder bewusst direkt bleiben oder typisiert ins SDK aufgenommen werden.

## 6. Repository `LabelArchitect` – PrintHub Studio

### 6.1 Zweck und Navigation

Studio ist der gemeinsame Produkteinstieg für Desktop und mobile Nutzung. Es MUSS fünf Hauptansichten bereitstellen:

- `/#/templates`: Templatebibliothek;
- `/#/print`: mobiler Schnell-Druck;
- `/#/designer`: visueller Desktop-Designer;
- `/#/jobs`: gehaltene, fehlgeschlagene und aktuelle Jobs;
- `/#/printers`: Print-Services, Drucker, Medien und IPP-Freigaben.

Ein `draft_id` in der URL MUSS direkt den Schnell-Druck öffnen. Die Anwendung MUSS ohne Thingdex funktionieren.

### 6.2 Templatebibliothek

- Gespeicherte Templates MÜSSEN mit Name, Tags, Größe und Anzahl Variablen angezeigt werden.
- Templates MÜSSEN nach Name, ID und Tags durchsuchbar sein.
- Die Liste MUSS manuell aktualisierbar sein.
- Sofern vorhanden, MUSS die serverseitige PNG-Vorschau angezeigt werden.
- Wenn keine Vorschau vorhanden ist, SOLL eine textuelle Vorschau aus Sample-Daten erscheinen.
- Ein Template MUSS für den Schnell-Druck ausgewählt oder im Designer geöffnet werden können.
- Ein neues Template MUSS direkt aus der Bibliothek angelegt werden können.

### 6.3 Schnell-Druck

- Der Nutzer MUSS ein Template und einen sichtbaren, konfliktfreien Drucker auswählen können.
- Bei Draft-Aufruf MUSS das eingebettete Template mit dessen Variablen und Ziel geladen werden.
- Variablenfelder MÜSSEN anhand ihrer Definition erzeugt werden.
- Unterstützte Eingaben SOLLEN Text, mehrzeiliger Text, Auswahloptionen sowie weitere HTML-kompatible Feldtypen umfassen.
- Pflichtfelder MÜSSEN kenntlich gemacht und vor dem Druck validiert werden.
- Sample- und Default-Werte SOLLEN vorausgefüllt werden.
- Der zuletzt gewählte Drucker SOLL lokal im Browser gespeichert werden.
- Das Ausgabeformat MUSS zwischen automatisch, ZPL und vollständigem Raster wählbar sein, soweit der Drucker dies unterstützt.
- Die Ausgabegröße MUSS zwischen Templategröße, geladenem Druckermedium und benutzerdefinierter Größe umschaltbar sein.
- Bei benutzerdefinierter Größe MÜSSEN Breite, Höhe, DPI und Ursprungsoffsets editierbar sein.
- Eine PNG-Vorschau MUSS vor dem Druck erzeugt werden können.
- Textlayoutwarnungen MÜSSEN sichtbar sein.
- Vor einem Druck mit Warnungen MUSS eine ausdrückliche Bestätigung erfolgen.
- Der Druck MUSS einen logischen PrintHub-Job mit Ursprung `printhub-studio` erzeugen.

### 6.4 Visueller Designer

- Der Designer MUSS eine Baumansicht links, einen Canvas in der Mitte und Eigenschaften rechts darstellen.
- Der Canvas MUSS Millimeter in Pixel umrechnen und Split-Grenzen interaktiv verschiebbar machen.
- Optionale Rasterung/Snap und Zoom MÜSSEN unterstützt werden.
- Werkzeuge MÜSSEN Auswahl, vertikalen Split, horizontalen Split, Text, QR, DataMatrix, Bild und Linie umfassen.
- Knoten und Elemente MÜSSEN über stabile IDs auswählbar sein.
- Ein Leaf MUSS in einen Split umgewandelt und mit einem Element belegt werden können.
- Der Eigenschaftenbereich MUSS häufige Optionen priorisieren und seltene Optionen einklappbar anbieten.
- Textparameter MÜSSEN Inhalt, Schrift, Größe, Ausrichtung, Wrap/Fit und Begrenzung abbilden.
- QR- und DataMatrix-Parameter MÜSSEN Inhalt, Größe/Modus und Ausrichtung abbilden.
- Bilder MÜSSEN aus Dateien als Data URL/Base64 übernommen werden können.
- Linien, Padding, Elementgrenzen, Splitverhältnis, Gutter, Divider, Alias und Hintergründe MÜSSEN editierbar sein.
- Der Designer MUSS Undo/Redo auf unveränderlichen Zustandsoperationen anbieten.
- Das Dokument MUSS laufend mit Zod gegen das v1-Schema validiert werden.
- Validierungsfehler MÜSSEN in einem Panel sichtbar sein.
- Template, Theme, Vorschauziel und Variablenwerte SOLLEN in `localStorage` erhalten bleiben.
- JSON-Import und -Export MÜSSEN unterstützt werden.
- Templates MÜSSEN samt Tags, Variablendefinitionen, Sample-Daten und Vorschauziel neu gespeichert oder aktualisiert werden können.
- Der Designer MUSS Templates als Draft an den Operator-/Schnell-Druck übergeben können.
- Globale Designer-Defaults MÜSSEN aus einer zentralen Projektkonfiguration geladen werden und für neue wie geladene Templates gelten.

Erforderliche Tastaturbedienung:

- `Ctrl/Cmd+Z`: Undo;
- `Ctrl/Cmd+Shift+Z` oder `Ctrl/Cmd+Y`: Redo;
- `Ctrl/Cmd+N`: neues Template;
- `Ctrl/Cmd+I`: Import;
- `Ctrl/Cmd+E`: Export;
- `v`, `h`, `t`, `q`, `d`, `i`, `l`: Werkzeuge, sofern kein Eingabefeld fokussiert ist;
- `Escape`: Auswahlwerkzeug.

### 6.5 Druckerverwaltung

- Administrative Funktionen MÜSSEN erst nach Eingabe eines PrintHub-Admin-Tokens zugänglich sein.
- Das Token DARF nur in `sessionStorage` gehalten werden und darf nicht dauerhaft gespeichert oder ins HTML eingebettet werden.
- Bekannte Drucker MÜSSEN Anzeigename, Defaultstatus, Sichtbarkeit, Offline-/Bereitschaftszustand, Identitätskonflikt und unterstützte Formate zeigen.
- Drucker MÜSSEN umbenannt, ein-/ausgeblendet und als Standard gesetzt werden können.
- Queue-Steuerung MUSS Pause und Fortsetzen unterstützen, wenn der Service dies anbietet.
- Wartungsaktionen SOLLEN Konfigurationsetikett, Netzwerketikett und Medienkalibrierung anbieten und eine Bestätigung verlangen.
- Print-Services MÜSSEN mit Name, URL und mindestens 24 Zeichen langem Token verbunden werden können.
- Services MÜSSEN umbenannt, auf eine neue URL verschoben und aktiviert/deaktiviert werden können.
- IPP-Freigaben MÜSSEN mit Queue-ID, Anzeigename und Drucker angelegt sowie aktiviert/deaktiviert werden können.
- Zebra-Drucker MÜSSEN über TCP, Character-Device oder direkten USB-Bulk-Transport angelegt werden können.
- TCP MUSS Host und Port, standardmäßig `9100`, unterstützen.
- Character-Device MUSS einen Gerätepfad unterstützen.
- USB-Bulk MUSS Vendor-ID, Product-ID und optional eindeutige Seriennummer unterstützen.
- USB-Geräteerkennung MUSS angebotene Geräte übernehmen können.
- Beim Anlegen MUSS direkt ein geladenes Medium mit Name, Breite, Höhe, Trackingart, Drucktechnologie, Farbe, Vorschaufarbe, Rollmenge und Warnschwelle definiert werden können.

### 6.6 Jobansicht

- Die Ansicht MUSS aktuelle Jobs mit logischem und downstream Zustand darstellen.
- Hold-Grund, Warnung, Fehler, angeforderte/maximale Labels und downstream Jobs MÜSSEN sichtbar sein.
- Gehaltene Jobs MÜSSEN mit `fit` oder `fill` freigegeben werden können.
- Das Übersteuern des Label-Limits MUSS bestätigt werden.
- Fehlgeschlagene Jobs MÜSSEN wiederholt werden können.
- Noch abbrechbare Jobs MÜSSEN abgebrochen werden können.
- Jobs mit unbekanntem Ausgang MÜSSEN nur über eine bestätigte, neue Reprint-Operation erneut ausgegeben werden.

### 6.7 Laufzeitkonfiguration und Auslieferung

- API-, Render- und Operator-Basis-URLs MÜSSEN sowohl zur Buildzeit als auch zur Containerlaufzeit konfigurierbar sein.
- Nginx SOLL `/api` same-origin zu PrintHub weiterleiten.
- Labelgrößen-Presets MÜSSEN konfigurierbar sein.
- Das UI MUSS eine helle und dunkle Darstellung besitzen.
- Der Designer darf als Desktop-Funktion breiter ausgelegt sein; Bibliothek und Schnell-Druck MÜSSEN mobil nutzbar sein.

## 7. Repository `ZebraTamer` – PrintAgent

### 7.1 Zweck und Abgrenzung

ZebraTamer ist ein kleiner Linux-Edge-Dienst für Zebra-ZPL-II-Drucker. Er besitzt die physischen Drucker, deren persistente Warteschlangen, Geräteeinstellungen, Statusbeobachtungen und geladenen Medien.

Nicht Bestandteil sind:

- eine Datenbank-Serverabhängigkeit;
- CUPS/IPP;
- ein RAW-9100-Listener;
- automatische Wiederholung unsicherer Drucke;
- Skalierung, Rotation oder Dithering von bereits vorbereiteten Rasterseiten.

### 7.2 Transporte

Der Dienst MUSS pro Drucker einen der folgenden Transporte unterstützen:

- Character-Device, zum Beispiel `/dev/usb/lp0`;
- USB-Bulk mit exakter Vendor-/Product-ID und optionaler Seriennummer;
- TCP als Client zu einem Drucker auf RAW-Port `9100` oder konfiguriertem Port.

USB-Bulk MUSS Printer-Class-Endpunkte aus USB-Deskriptoren erkennen. Mehrdeutige VID/PID-Treffer MÜSSEN ohne konfigurierte Seriennummer abgelehnt werden. TCP-Abfragen SOLLEN je Antwortsitzung eine frische Verbindung verwenden und Größen- sowie Timeoutgrenzen durchsetzen.

### 7.3 Parallelität und Warteschlangen

- Jeder Drucker MUSS genau einen begrenzten Worker besitzen.
- Jobs, Statusabfragen, Konfigurationsänderungen, Medienänderungen und Wartung dürfen sich für denselben Drucker nicht überlappen.
- Verschiedene Drucker SOLLEN parallel arbeiten können.
- Warteschlangen und Pausezustand MÜSSEN persistent sein.
- Aktive Jobs MÜSSEN gegen ein konfiguriertes Queue-Limit geprüft werden.
- Noch nicht übertragene Jobs MÜSSEN abbrechbar sein.
- Nach Neustart MÜSSEN wartende Jobs fortgesetzt werden.
- Unterbrochene Uploads MÜSSEN fehlschlagen.
- Beim Schreiben oder Verifizieren unterbrochene Jobs MÜSSEN `outcome_unknown` werden und dürfen nicht automatisch wiederholt werden.
- Bereits als `transport_accepted` gespeicherte Jobs MÜSSEN terminal bleiben.

### 7.4 Jobannahme und Idempotenz

- Native Nutzlasten mit `application/zpl` MÜSSEN angenommen werden.
- Das neutrale `application/vnd.printhub.raster-page+json` MUSS angenommen werden.
- ZPL-Uploads SOLLEN gestreamt, auf Platte gespeichert und gehasht werden, ohne den vollständigen Body im Arbeitsspeicher zu behalten.
- Jeder aufrufende Client MUSS einen `X-Idempotency-Key` senden können.
- Gleicher Schlüssel plus gleicher Drucker und gleicher Payload MUSS den ursprünglichen Job liefern.
- Gleicher Schlüssel mit anderem Drucker oder Inhalt MUSS HTTP `409` liefern.
- Rasterbreite, -höhe, DPI, Zeilenpadding und Gerätegrenzen MÜSSEN vor Queue-Aufnahme geprüft werden.
- Rasterseiten MÜSSEN unverändert als Zebra-`^GF` kodiert werden; Weißpadding und Profilabweichungen MÜSSEN abgelehnt werden.

### 7.5 Druckerstatus und Fähigkeiten

- Der Agent MUSS eine stabile `agent_id` melden.
- Eine explizite ID MUSS verwendet werden können; andernfalls MUSS beim ersten normalen Start eine UUID erzeugt und gespeichert werden.
- `--check-config` DARF keine Identität erzeugen oder Daten verändern.
- Eine ungültige persistierte Identität MUSS den Start abbrechen und darf nicht still ersetzt werden.
- Der Agent MUSS Druckerliste, Druckerdetails, Snapshot und Capabilities anbieten.
- Zebra-Probes MÜSSEN mindestens `~HS`, `~HD`, `~HM`, `~HB`, `^HH` sowie R/E/B/Z-Verzeichnisabfragen unterstützen.
- Optionale SGD-, `~HQ`- und Odometer-Funktionen dürfen erst nach erfolgreicher Antwort als unterstützt gelten.
- Ein Offline-Timeout MUSS `unavailable`, nicht `not_supported`, ergeben.
- Prometheus-Metriken MÜSSEN aus Cachezuständen erzeugt werden und dürfen keine Geräte-I/O auslösen.
- DNS-SD/mDNS SOLL Agent und Drucker mit stabiler Identität und REST-Pfaden ankündigen.

### 7.6 Medienverwaltung

Ein geladenes Medium MUSS mindestens enthalten:

- Name;
- Breite und Höhe;
- Farbe und Vorschaufarbe;
- Material/Drucktechnologie;
- Trackingart wie Gap, Black Mark oder Continuous;
- Anfangsmenge, verbrauchte/verbleibende Menge und Warnschwelle;
- eine Revisionskennung für optimistische Konkurrenzkontrolle.

Anforderungen:

- Metadatenänderungen MÜSSEN den Verbrauch erhalten.
- Das Laden einer neuen Rolle MUSS den alten Zustand archivieren und neue Zähler starten.
- Entladen und manuelle Bestandsanpassungen MÜSSEN unterstützt werden.
- Druck, Medienmutation und Wartungsverbrauch MÜSSEN serialisiert werden.
- Ein Medien-Ledger MUSS Änderungen nachvollziehbar machen.
- Farbe DARF niemals als Zebra-Geräteeinstellung gesendet werden.
- Bei Gap-/Mark-Material MUSS die physische Druckerkalibrierung als separate Bedienhandlung behandelt werden.

### 7.7 Gerätekonfiguration

Der Dienst MUSS folgende Zebra-Werte lesen und typisiert ändern können:

- absolute Druckdunkelheit (`~SD`);
- Geschwindigkeit (`^PR`);
- Links-/Top-Position (`^LS`, `^LT`);
- Druckbreite (`^PW`);
- Länge bei Endlosmaterial (`^LL`);
- Ausgabemodus (`^MM`);
- Direct Thermal/Thermal Transfer (`^MT`);
- Medientracking (`^MN`).

Das Geräteprofil MUSS DPI, Grenzen und installierte Optionen wie Thermal Transfer, Peel-off und Cutter deklarieren. Nicht sicher erkannte Fähigkeiten MÜSSEN konservativ deaktiviert bleiben.

Der Speichervorgang MUSS atomar im Druckerworker ablaufen:

1. frisches `^HH` lesen;
2. Clientrevision prüfen;
3. nur geänderte typisierte Einstellungen anwenden;
4. erneut lesen und vergleichen;
5. `^JUS` nur nach Bestätigung aller angeforderten aktiven Werte senden;
6. nochmals lesen und Ergebnis separat protokollieren.

Der Client MUSS bestätigen, dass `^JUS` alle aktuell persistenten Parameter speichert. Ergebniszustände MÜSSEN mindestens `not_saved`, `apply_outcome_unknown`, `save_outcome_unknown` und `save_sent_active_verified` unterscheiden. Eine erfolgreiche Übertragung darf nicht als verifizierte Stromausfallpersistenz dargestellt werden.

### 7.8 Eingebaute WebUI

- Die WebUI MUSS optional und standardmäßig deaktiviert sein.
- Sie MUSS vollständig in das Binärprogramm eingebettet sein und ohne Node.js oder PrintHub funktionieren.
- Sie MUSS same-origin arbeiten, keine externen Assets laden und eine restriktive CSP besitzen.
- Das Admin-Token DARF weder ins HTML eingebettet noch im Browser gespeichert werden.
- Die UI SOLL Druckerstatus, Gerätekonfiguration und Medienverwaltung anbieten.

### 7.9 API v2

Der gemeinsame Print-Service-Vertrag MUSS mindestens bereitstellen:

| Methode | Pfad | Funktion |
| --- | --- | --- |
| `GET` | `/healthz` | Healthcheck |
| `GET` | `/v2/service` | stabile Service-Identität und Vertrag |
| `GET` | `/v2/printers` | Druckerkatalog |
| `GET` | `/v2/printers/{id}` | Druckerdetails |
| `POST` | `/v2/printers/{id}/jobs` | atomaren Job annehmen |
| `POST` | `/v2/printers/{id}/queue/pause` | Queue pausieren |
| `POST` | `/v2/printers/{id}/queue/resume` | Queue fortsetzen |
| `GET` | `/v2/jobs` | Jobs paginiert auflisten |
| `GET` | `/v2/jobs/{id}` | Jobstatus laden |
| `POST` | `/v2/jobs/{id}/cancel` | Job abbrechen |
| `GET` | `/v2/jobs/by-idempotency/{key}` | vorhandenen Job auflösen |
| `GET` | `/v2/admin/printers` | administrative Druckerdaten |
| `GET` | `/v2/admin/usb-devices` | USB-Geräte entdecken |
| `POST` | `/v2/admin/printers/{id}` | Drucker speichern |
| `PUT` | `/v2/admin/printers/{id}/media` | Medium laden |
| `POST` | `/v2/admin/printers/{id}/maintenance/{action}` | Wartungsaktion |
| `POST` | `/v2/extensions/zebra/printers/{id}` | Zebra-spezifische Druckeranlage |
| `POST` | `/v2/extensions/zebra/printers/{id}/maintenance/{action}` | Zebra-Wartung |

Listen MÜSSEN Cursor und Limit bis maximal 200 unterstützen. Administrative v2-Funktionen MÜSSEN authentifiziert sein.

### 7.10 Legacy-v1-Kompatibilität

Das vorhandene System bietet zusätzlich v1-Endpunkte für Agent, Treiber, Drucker, Jobs, Ereignisse, Payload, Medien und Konfiguration. Ein kompatibler Neuaufbau SOLL sie entweder erhalten oder eine explizite Migrationsversion bereitstellen. Besonders relevant sind:

- `GET /v1/printers/{id}/configuration` ohne Geräte-I/O;
- `POST /v1/printers/{id}/configuration/read` für Live-Lesen;
- `POST /v1/printers/{id}/configuration` für revisionsgesichertes Anwenden/Speichern;
- `GET/PATCH/PUT /v1/printers/{id}/media` für Lesen, Metadatenänderung und neue Rolle;
- `POST /v1/printers/{id}/media/unload` und `/media/adjustments`.

### 7.11 Deployment

- Ein einzelnes statisches Rust-Binärprogramm SOLL als Runtime dienen.
- Systemd-Service, udev-Regel und Installationsskript MÜSSEN für Debian/Raspberry Pi angeboten werden.
- ARMv7 und AArch64 MÜSSEN als native Bundles baubar sein; AMD64/ARM64 Container SOLLEN veröffentlicht werden.
- Der Dienst SOLL unter eigenem Benutzer ohne Root laufen und nur Zugriff auf das konkrete Druckergerät erhalten.
- `--check-config` und ein CLI-Healthcheck MÜSSEN für Deploymentprüfung verfügbar sein.

## 8. Repository `ZPL-II-Printer-Emulator`

### 8.1 Zweck

Der Emulator ist ein Entwicklungswerkzeug, das sich wie ein einfacher Netzwerk-ZPL-Drucker verhält, empfangene Jobs über Labelary in PNG rendert und die letzten Jobs in einer Weboberfläche darstellt.

### 8.2 Anforderungen

- Der Emulator MUSS einen konfigurierbaren TCP-Listener bereitstellen, standardmäßig `127.0.0.1:9100`.
- Er MUSS bis zum Verbindungsende lesen und den vollständigen nichtleeren Byte-Stream als einen Druckjob behandeln.
- Ungültige UTF-8-Bytes SOLLEN ersetzend dekodiert werden, damit der Entwicklungsjob sichtbar bleibt.
- Rendering MUSS asynchron außerhalb des Request-/TCP-Lesepfads erfolgen.
- Jobzustände MÜSSEN `rendering`, `rendered` und `failed` umfassen.
- Fehler des externen Renderers MÜSSEN am Job sichtbar werden.
- Der In-Memory-Speicher MUSS threadsicher sein und standardmäßig nur die jüngsten 50 Jobs behalten.
- Listen MÜSSEN neueste Jobs zuerst liefern.
- Pro Job MÜSSEN ID, UTC-Zeit, empfangene Bytes, Status, Fehler und Bildverfügbarkeit sichtbar sein.
- Ein Testdruck MUSS alternativ per HTTP mit direktem ZPL ausgelöst werden können.
- Das erzeugte PNG MUSS über einen eigenen Endpunkt abrufbar sein.
- Etikettenbreite/-höhe und DPMM MÜSSEN zur Laufzeit validiert änderbar sein.
- Größen MÜSSEN auf `>0` bis `300 mm`, DPMM auf `6–24` begrenzt sein.
- Web- und TCP-Host/Port, Labelgröße, DPMM, Joblimit und Labelary-URL MÜSSEN per Environment konfigurierbar sein.
- Die WebUI MUSS Jobs, Renderbilder, Status und Einstellungen ohne separate Frontend-Laufzeit darstellen.

### 8.3 HTTP-API

| Methode | Pfad | Funktion |
| --- | --- | --- |
| `GET` | `/` | statische WebUI |
| `GET` | `/health` | Healthcheck |
| `GET` | `/api/jobs` | letzte Jobs laden |
| `GET` | `/api/jobs/{job_id}` | Jobdetails laden |
| `GET` | `/api/jobs/{job_id}/image` | gerendertes PNG laden |
| `POST` | `/api/test-print` | ZPL-Testjob anlegen |
| `GET` | `/api/settings` | aktive Druckeinstellungen lesen |
| `PUT` | `/api/settings` | Labelgröße/DPMM ändern |

### 8.4 Bewusste Einschränkungen

- Der Emulator ist kein vollständiger Print-Service-v2.
- Er besitzt keine dauerhafte Jobpersistenz.
- Er simuliert keinen verlässlichen Hardwarestatus.
- Er ist für Entwicklung gedacht und darf nicht als Nachweis eines physischen Drucks gelten.

## 9. Repository `Thingdex`

### 9.1 Zweck und Systemgrenze

Thingdex ist ein eigenständig deploybares, selbst gehostetes Haushaltsinventar-Backend. Es ist die Quelle der Wahrheit für Orte, benutzerdefinierte Gegenstandstypen, Gegenstände, Beziehungen, Eigenschaftshistorien, Snapshots und optionale Label-Automatisierung.

Thingdex besitzt keine UI, kein Template-Layout, kein ZPL, keine Druckerkonfiguration und keinen Gerätestatus.

### 9.2 Technische Basis

- Die API MUSS versioniert mit FastAPI oder einem gleichwertigen HTTP-Framework umgesetzt sein.
- PostgreSQL 15+ MUSS als persistente Datenbank verwendet werden.
- Schemaänderungen MÜSSEN über Alembic oder gleichwertige versionierte Migrationen erfolgen.
- Ein eingechecktes OpenAPI-Dokument MUSS mit der Laufzeit-API übereinstimmen.
- Liveness und Readiness MÜSSEN getrennt sein; Readiness MUSS bei Datenbankausfall geschlossen fehlschlagen.
- Die produktive Containerlaufzeit MUSS Migrationen kontrolliert vor dem API-Start ausführen können.

### 9.3 Orte

- Orte MÜSSEN eine hierarchische Adjazenzlistenstruktur bilden.
- Genau ein aktiver Root-Ort MUSS existieren.
- Der Root MUSS idempotent bootstrapbar sein.
- Nur der Root darf keinen Elternort besitzen.
- Der Root darf nicht verschoben, umtypisiert oder gelöscht werden.
- Ein Ort darf nicht unter einen eigenen Nachfahren verschoben werden.
- Name, optionale Art und freie JSON-Metadaten MÜSSEN unterstützt werden.
- Direkte Kinder, vollständiger Baum und Root-zu-Ort-Pfad MÜSSEN abfragbar sein.
- Gegenstände eines Ortes MÜSSEN direkt oder rekursiv aufgelistet werden können.
- Löschen MUSS als Soft Delete eines leeren Nicht-Root-Unterbaums erfolgen.
- Enthält der Unterbaum aktive Gegenstände, MUSS Löschen mit Konflikt abgelehnt werden.

### 9.4 Gegenstandstypen und Schema-Dialekt

- Ein Item Type MUSS Name, Feldschema, UI-Hinweise, optionale Label-Template-ID und Soft-Delete-Zeit besitzen.
- Typnamen MÜSSEN auch über Soft Deletes hinweg eindeutig bleiben.
- Der Schema-Dialekt MUSS `string`, `integer`, `number`, `boolean`, `date` und `date-time` unterstützen.
- Pro Feld MÜSSEN `required`, `default`, `enum`, `min`, `max`, Volltreffer-`pattern` und `track_history` unterstützt werden.
- UI-Metadaten wie `unit`, `label`, `help`, `group` und `order` MÜSSEN gespeichert, aber nicht fachlich umgerechnet werden.
- Unbekannte UI-Metadaten SOLLEN erhalten bleiben.
- `allow_additional` MUSS zusätzliche Eigenschaften explizit erlauben oder standardmäßig verbieten.
- Neue und vollständig ersetzte Gegenstände MÜSSEN Defaults anwenden.
- Schemaänderungen MÜSSEN gegen alle aktiven Gegenstände validiert werden.
- Eine Änderung, die bestehende Daten ungültig macht, MUSS HTTP `409` mit betroffenen IDs und Fehlern liefern.
- Ein Typ mit aktiven Gegenständen DARF nicht gelöscht werden.

### 9.5 Gegenstände

- Ein Gegenstand MUSS stabile UUID, Typ, Status, optionale Beschreibung, validierte JSONB-Eigenschaften und Zeitstempel besitzen.
- Ein Gegenstand MUSS entweder einen direkten physischen Ort oder eine aktive In-use-Elternbeziehung besitzen.
- Gegenstände MÜSSEN einzeln und atomar in Batches angelegt werden können.
- Batches MÜSSEN atomare Updates und Ortswechsel unterstützen.
- Status und Beschreibung MÜSSEN separat von Eigenschaften aktualisierbar sein.
- Eigenschaften MÜSSEN per PATCH gemergt oder per PUT vollständig ersetzt werden können.
- Listen MÜSSEN nach Typ, Status und In-use-Zustand filterbar sein.
- Gegenstände ohne effektiven Ort MÜSSEN auffindbar sein.
- Detailantworten MÜSSEN Typdaten, physischen Ort, effektiven Ort und vollständigen Ortspfad enthalten.
- Gegenstände MÜSSEN soft-gelöscht werden.
- Aktive Beziehungen MÜSSEN vor dem Löschen getrennt werden.

### 9.6 Beziehungen und effektiver Ort

Unterstützte Beziehungstypen MÜSSEN mindestens sein:

- `installed_in`;
- `uses`;
- `paired_with`.

Anforderungen:

- Beziehungen MÜSSEN gerichtet mit Eltern-, Kind-ID, Typ, Menge, Slot, Notizen und Zeitstempel gespeichert werden.
- Selbstbeziehungen MÜSSEN verboten sein.
- Die Menge MUSS positiv sein.
- Doppelte aktive Kanten MÜSSEN verhindert werden.
- Ein Kind darf höchstens einen aktiven `installed_in`- oder `uses`-Elternteil besitzen.
- Attach eines In-use-Kindes MUSS dessen direkte `location_id` entfernen.
- Der effektive Ort MUSS über aktive Elternbeziehungen bis zum ersten physischen Ort aufgelöst werden.
- Zyklen MÜSSEN verhindert werden.
- Graphmutationen MÜSSEN in PostgreSQL serialisiert werden, damit konkurrierende Requests keine Invarianten brechen.
- `paired_with` DARF den physischen Ort nicht beeinflussen.
- Aktivstatus DARF nicht direkt gepatcht werden.
- Detach MUSS das Kind an einen expliziten Ort oder den Root setzen.
- Inaktive Beziehungen dürfen anschließend soft-gelöscht werden.

### 9.7 Eigenschaftshistorie und Snapshots

- Felder mit `track_history: true` MÜSSEN bei Wertänderung einen Eventdatensatz erzeugen.
- Historie MUSS Property-Key, Zeitpunkt, JSON-Wert und Quelle enthalten und neueste Einträge zuerst liefern können.
- Aktuelle Eigenschaften bleiben die Lesequelle; Historie ist ein Eventlog.
- Snapshots MÜSSEN große oder unabhängig versionierte Beobachtungen speichern.
- Ein Snapshot MUSS Art, Aufnahmezeit, optionalen Text, optionale JSON-Daten und Metadaten enthalten.
- Snapshots MÜSSEN nach Gegenstand und optional nach Art gelistet und soft-gelöscht werden können.

### 9.8 Suche

- Die Suche MUSS Typ, Ortsunterbaum und In-use-Zustand kombinieren können.
- JSON-Eigenschaften MÜSSEN über Pfade filterbar sein.
- Operatoren MÜSSEN `==`, `!=`, `>`, `>=`, `<`, `<=`, `contains` und `in` umfassen.
- Numerische Vergleiche MÜSSEN JSON-Zahlen, Datumsvergleiche ISO-Strings konsistent behandeln.

### 9.9 Labelprofile und PrintIntent-Outbox

Die Labelintegration MUSS optional und standardmäßig deaktiviert sein.

- Ein Labelprofil MUSS Name, Entitätsart, optionalen Item Type oder Location Kind, Template-ID, Drucker-ID, Auto-Print-Flag, Bindings und Aktivstatus besitzen.
- Profile MÜSSEN für Item Types oder Location Kinds auflösbar sein.
- Erforderliche Templatevariablen MÜSSEN gegen Item-Schema und Bindings validierbar sein.
- `internal_uuid` MUSS als systemseitige Variable geliefert werden können.
- Beim Erstellen eines Gegenstands oder Ortes MUSS der Inventardatensatz zusammen mit einem unveränderlichen PrintIntent atomar committen.
- Der Inventarrequest DARF nicht auf PrintHub warten und darf bei PrintHub-Ausfall nicht zurückgerollt werden.
- Ein PrintIntent MUSS Entität, Version, Template, Drucker, unveränderlichen Variablensnapshot, stabilen Idempotenzschlüssel, Zustand, Versuche und Zeitplanung speichern.
- Ein separater Worker MUSS wartende Intents mit Lease-/Crash-Recovery verarbeiten.
- Temporäre Fehler MÜSSEN begrenzt wiederholt werden.
- Permanente Ablehnungen dürfen nicht in eine Endlosschleife gelangen.
- Nach maximalen Versuchen MUSS ein authentifizierter Operator einen neuen begrenzten Versuchshaushalt starten können.
- Der PrintHub-Aufruf MUSS die PrintIntent-ID als `origin_reference` mitgeben.
- Alte `item_types.label_template_id`- und ortsbezogene Metadaten dürfen als Migrationsfallback erhalten bleiben, sind aber nicht die bevorzugte Automatisierung.

### 9.10 Statusereignisse von PrintHub

- Der Inbox-Endpunkt MUSS standardmäßig deaktiviert sein, solange kein Secret konfiguriert ist.
- Eingehende Bodies MÜSSEN per HMAC-SHA256 authentifiziert werden.
- Event-IDs MÜSSEN idempotent sein.
- Nur monoton steigende Sequenzen dürfen den sichtbaren Jobzustand voranbringen.
- Duplikate und ältere Ereignisse MÜSSEN als erfolgreiche No-ops behandelt werden.
- Der öffentliche PrintIntent-Admin-Response DARF den aufgelösten Variablensnapshot nicht offenlegen.

### 9.11 Öffentliche HTTP-API

| Bereich | Endpunkte / Funktionen |
| --- | --- |
| Health | `GET /health/live`, `/health/ready`, `/health` |
| Orte | Create, Root lesen/bootstrapen, Baum, Details, Update, Delete, Kinder, Pfad, Items |
| Item Types | Create, List, Get, Update, Delete |
| Items | Create, List, Bulk Create/Update/Move, Missing Location, Get, Update, Delete, Move |
| Eigenschaften | PATCH Merge und PUT Replace |
| Beziehungen | Attach, Kinder/Eltern listen, Metadaten ändern, Detach, Delete |
| Historie | Item-Historie lesen |
| Snapshots | Create, List, Delete |
| Suche | compound Search per POST |
| Labels | manuellen Druck für Item oder Location anfordern |
| Labelprofile | List, Create, Get, Update, Delete |
| PrintIntents | authentifiziert List, Get und Retry |
| Integration | HMAC-gesicherte PrintHub-Ereignisse anwenden |

### 9.12 Sicherheits- und Fehlerverhalten

- PrintIntent-Administration MUSS geschlossen fehlschlagen, wenn kein Admin-Token gesetzt ist.
- Datenbank-, PrintHub-, Admin- und Event-Secrets MÜSSEN getrennt injiziert werden.
- Soft-gelöschte Ressourcen MÜSSEN in normalen Reads wie nicht vorhanden behandelt werden.
- Fehlersemantik SOLL `400` für Domain-/Schemafehler, `404` für nicht vorhandene Ressourcen, `409` für Invariantenkonflikte, `422` für Payloadvalidierung und `503` für Readinessabhängigkeiten verwenden.

## 10. Repository `Thingdex-Home-Inventory`

### 10.1 Tatsächlicher Inhalt

Dieses Repository enthält im analysierten Stand keine eigene Laufzeitanwendung. Es liefert:

- eine ausführliche System- und Repositoryübersicht;
- einen historischen/strategischen PrintHub-Rewrite-Plan;
- einen koordinierten Entwicklungs-Compose-Stack;
- Release-Dokumentation;
- eine alte Druckerkonfiguration und LabelGallery-Konfiguration.

### 10.2 Anforderungen an ein Nachfolge-Workspace-Repository

- Es SOLL als Einstiegspunkt erklären, welche Repositories existieren und welche Datenhoheit jedes besitzt.
- Es SOLL End-to-End-Datenflüsse, APIs, lokale Entwicklungsports und Contract-Update-Reihenfolge dokumentieren.
- Es SOLL einen Entwicklungsstack für PostgreSQL, Thingdex API, Thingdex Worker, PrintHub API, SDK-Watcher, UIs und einen Druckeremulator bereitstellen.
- API-Änderungen SOLLEN in der Reihenfolge Backend → OpenAPI → SDK → Consumer validiert werden.
- Lokale `file:`-SDK-Abhängigkeiten SOLLEN reproduzierbar und mit Watch-Modus nutzbar sein.

### 10.3 Historische Inhalte, die nicht als Zielanforderung gelten

Das vorhandene `docker-compose.dev.yml` und Teile des README verweisen noch auf:

- `PrinterFleet` als Pflichtdienst;
- getrennte `LabelArchitect`- und `LabelGallery`-Oberflächen;
- `ThingdexUI` und `thingdex-sdk`, die nicht in diesem Workspace liegen;
- alte Fleet-URLs und Drucker-YAML-Konfiguration.

Der aktuelle Root-Stack hat PrinterFleet entfernt, PrintHub Studio konsolidiert und ZebraTamer direkt als Print-Service angebunden. Ein Neuaufbau MUSS sich am aktuellen Root-Repository und am Print-Service-v2-Vertrag orientieren. Das historische Repository ist als Migrations- und Architekturquelle nützlich, aber nicht als unveränderlicher Laufzeitvertrag.

## 11. Zentrale End-to-End-Workflows

### 11.1 Template entwerfen und speichern

1. Nutzer öffnet den Desktop-Designer.
2. Nutzer legt Labelgröße/DPI fest und baut einen rekursiven Split-/Leaf-Baum.
3. Nutzer platziert Text, 2D-Code, Bild oder Linie und definiert dynamische Variablen.
4. Studio validiert das Dokument fortlaufend.
5. Studio erzeugt über PrintHub eine ZPL-/PNG-Vorschau und zeigt Diagnosen.
6. Nutzer speichert Name, Tags, Variablendefinitionen, Sample-Daten, Ziel und Template.
7. PrintHub validiert ID und Schema und speichert alles persistent.

### 11.2 Manueller Schnell-Druck

1. Nutzer wählt ein gespeichertes Template oder öffnet einen Draft.
2. Studio erzeugt aus Variablendefinitionen das Formular.
3. Nutzer wählt Drucker, Ausgabemodus und Größenquelle.
4. Studio rendert zur Vorprüfung und zeigt Warnungen.
5. Nach nötiger Bestätigung legt Studio den logischen PrintHub-Job an.
6. PrintHub löst Variablen/Makros auf und speichert das exakte Artefakt.
7. PrintHub wählt anhand der Druckerfähigkeiten ZPL oder Raster.
8. PrintHub übergibt idempotent an den zuständigen Print-Service.
9. ZebraTamer persistiert, reiht ein und überträgt serialisiert an das Gerät.
10. Beide Dienste zeigen getrennt logischen und physischen Transportzustand.

### 11.3 Raster-/Dokumentdruck über IPP

1. Betriebssystem sendet einen IPP-Job an eine stabile Queue.
2. Gateway übergibt das unveränderte Dokument mit haltbarem Idempotenzschlüssel an PrintHub.
3. PrintHub prüft Seitenzahl, Label-Limit und Medienabmessungen.
4. Bei Abweichung entsteht ein Hold; Nutzer entscheidet über `fit` oder `fill`.
5. PrintHub rastert lokal in das neutrale einfarbige Seitenformat.
6. Print-Service validiert Gerätegrenzen und sendet das Ergebnis.

### 11.4 Automatischer Thingdex-Druck

1. Administrator ordnet einem Item Type oder Location Kind ein Labelprofil zu.
2. Nutzer legt Inventarobjekt oder Ort an, ohne pro Vorgang einen Druckdialog bedienen zu müssen.
3. Thingdex commitet Entität und PrintIntent atomar.
4. Der API-Request endet unabhängig von PrintHub erfolgreich.
5. Ein Worker übermittelt den unveränderlichen Intent idempotent an PrintHub.
6. PrintHub erzeugt und verarbeitet den logischen Job.
7. PrintHub sendet Zustandsereignisse signiert und sequenziert an Thingdex zurück.
8. Operatoren können terminale Outboxfehler untersuchen und bewusst erneut freigeben.

### 11.5 Umgang mit unklarem Druckausgang

1. Der Print-Service verliert nach oder während der Übertragung die sichere Kenntnis über den Ausgang.
2. Der physische Job wird `outcome_unknown` beziehungsweise `unconfirmed`.
3. Weder ZebraTamer noch PrintHub wiederholen automatisch.
4. UI weist ausdrücklich darauf hin, dass kein physischer Erfolg bestätigt ist.
5. Nutzer prüft Drucker und Material.
6. Nur eine bestätigte Reprint-Aktion erzeugt einen neuen Job mit neuer Identität.

## 12. Datenhoheit und Persistenz

| Daten | Eigentümer | Persistenzanforderung |
| --- | --- | --- |
| Templates, Sample-Daten, Variablendefinitionen | PrintHub | dauerhaft |
| Drafts | PrintHub | bis Ablaufzeit |
| logische Jobs und unveränderliche Artefakte | PrintHub | dauerhaft/recovery-fähig |
| Serviceverbindungen und Tokens | PrintHub | dauerhaft, Tokens separat und geheim |
| öffentlicher Druckerkatalog und Benutzerpräferenzen | PrintHub | dauerhaft, Cache bei Offline-Service |
| IPP-Freigaben und Portzuordnung | PrintHub / IPP Gateway | dauerhaft |
| physische Druckerdefinitionen | jeweiliger Print-Service | dauerhaft |
| physische Warteschlange und Jobpayload | ZebraTamer | dauerhaft und crash-sicher |
| Gerätekonfiguration und letzte Versuche | ZebraTamer | dauerhaft, Beobachtung und Versuch getrennt |
| geladenes Medium und Ledger | ZebraTamer | dauerhaft |
| Inventarobjekte, Orte, Typen, Relationen | Thingdex/PostgreSQL | dauerhaft |
| Inventar-PrintIntents und Event-Inbox | Thingdex/PostgreSQL | dauerhaft und transaktional |
| Emulatorjobs | ZPL-Emulator | absichtlich nur im Speicher |
| Browserzustand | Studio | Template/Theme/Preview lokal; Admin-Token nur Session |

## 13. Nichtfunktionale Neuaufbau-Anforderungen

### Zuverlässigkeit

- Persistente Schreibvorgänge MÜSSEN atomar erfolgen.
- Single-writer-Schutz MUSS verhindern, dass zwei ZebraTamer-Prozesse dasselbe Datenverzeichnis bearbeiten.
- Crash-Recovery MUSS terminale, wartende und unsichere Jobs korrekt unterscheiden.
- Externe Ausfälle dürfen lokale, bereits bestätigte Datenbanktransaktionen nicht rückgängig machen.

### Sicherheit

- Admin- und Servicefunktionen MÜSSEN authentifiziert sein.
- Secrets DÜRFEN nicht in Logs, OpenAPI, Images, UI-Bundles oder öffentlichen Antworten auftauchen.
- Dienste SOLLEN nur im vertrauenswürdigen Netz oder hinter authentifiziertem TLS-Reverse-Proxy erreichbar sein.
- Die legacy ZebraTamer-v1-Druck-API kann beliebiges ZPL senden und ist deshalb keine ausreichende Sicherheitsgrenze; Netzsegmentierung bleibt erforderlich.
- Remote Bild- und Renderdienste MÜSSEN explizit opt-in sein.

### Observability

- Jeder Dienst MUSS einen Health-Endpunkt besitzen.
- Abhängige Readiness MUSS getrennt von Prozess-Liveness beurteilt werden.
- ZebraTamer MUSS Prometheus-Metriken ohne Geräte-I/O bereitstellen.
- Jobfehler, Holds, Warnungen, downstream Zustände und unsichere Ausgänge MÜSSEN für Operatoren sichtbar sein.

### Portabilität

- Das Kernprodukt MUSS auf AMD64 und ARM64 lauffähig sein.
- ZebraTamer SOLL zusätzlich ARMv7 für ältere Raspberry Pis unterstützen.
- Produktionsimages MÜSSEN reproduzierbar, minimal und ohne Buildtooling sein.

### Testbarkeit

- Der ZPL-Emulator MUSS hardwarefreie RAW-TCP-Tests ermöglichen.
- Ein raster-only Konformitätsdienst MUSS Offline-, Slow-, Lost-response- und Unknown-outcome-Fälle injizieren können.
- OpenAPI-Artefakte MÜSSEN gegen die Anwendung geprüft werden.
- Print-Service-Protokollbeispiele MÜSSEN gegen JSON-Schemas validiert werden.
- Idempotenz, Restart-Recovery, Medienverbrauch, Identitätskonflikte, Größen-Holds und Reprint-Sicherheit MÜSSEN automatisierte Regressionstests besitzen.

## 14. Priorisierte Umsetzungsreihenfolge für einen Neuaufbau

### Phase 1 – Verträge und Domänen

- Template-v1-Schema und Renderziel festlegen.
- Print-Service-v2-Schemas einschließlich Job-, Printer-, Raster- und Error-Envelope festlegen.
- Zustandsautomaten für logische und physische Jobs definieren.
- Idempotenz- und Unknown-outcome-Regeln als ausführbare Vertragstests festhalten.
- Datenhoheit je Dienst verbindlich dokumentieren.

### Phase 2 – Geräteebene

- ZebraTamer-Persistenz, Single-writer-Schutz und per-printer Worker bauen.
- Character-Device-, USB-Bulk- und TCP-Transport implementieren.
- ZPL- und neutrales Rasterformat annehmen.
- Medienledger, Queue-Steuerung, Statusprobes und v2-Katalog implementieren.
- Emulator und raster-only Konformitätsdienst bereitstellen.

### Phase 3 – PrintHub-Kern

- Templatevalidierung, Layout und ZPL-Compiler bauen.
- Template-, Draft- und Jobstores implementieren.
- Zielabhängige ZPL-/Raster-Artefakterzeugung implementieren.
- Print-Service-Registry und öffentliche Druckerprojektion implementieren.
- Background-Recovery und Statusabgleich bauen.
- Dokument- und IPP-Pipeline ergänzen.

### Phase 4 – Studio und SDK

- OpenAPI exportieren und TypeScript-SDK generieren.
- Templatebibliothek und Schnell-Druck bauen.
- visuellen Designer mit Validierung, Undo/Redo und Import/Export bauen.
- Drucker-/Service-/Medien-/IPP-Verwaltung ergänzen.
- Jobansicht mit Hold, Retry, Cancel und sicherem Reprint ergänzen.

### Phase 5 – Optionales Thingdex

- Inventardomäne und PostgreSQL-Invarianten bauen.
- Suche, Historie und Snapshots ergänzen.
- Labelprofile und transaktionale PrintIntent-Outbox implementieren.
- HMAC-gesicherte Status-Inbox und Operatorverwaltung ergänzen.

### Phase 6 – Produktisierung

- Compose-Profile, Secret-Bootstrap und sichere Netzwerke bauen.
- Backup, Restore und Altdatenmigration testen.
- Multiarch-Images, native Pi-Bundles, SBOM und Provenance erzeugen.
- Hardwarefreie und reale Hardware-Abnahmematrix vollständig ausführen.

## 15. Offene Entscheidungen vor einem echten Rewrite

Diese Punkte sind im Bestand entweder absichtlich offen oder zwischen historischen und aktuellen Dokumenten uneinheitlich und sollten vor Implementierungsbeginn entschieden werden:

- Soll ZebraTamer v1 vollständig kompatibel bleiben oder nach einer Übergangsfrist entfallen?
- Sollen administrative PrintHub-Endpunkte vollständig in `printhub-sdk` aufgenommen werden?
- Wie lange müssen Templates, Jobs, Artefakte, Drafts und Emulatorjobs aufbewahrt werden?
- Welches Authentifizierungsmodell ersetzt die heutigen statischen Bearer-Tokens bei Internetzugriff oder Mehrbenutzerbetrieb?
- Soll ein eigener lokaler PNG-Renderer Labelary vollständig ersetzen?
- Welche genauen MIME-Typen und Grenzwerte gelten für Dokumente, Seiten, Pixel und Payloads im Zielprodukt?
- Werden ThingdexUI und `thingdex-sdk` ebenfalls neu gebaut, obwohl sie nicht Bestandteil dieses Workspaces sind?
- Soll das historische `Thingdex-Home-Inventory` modernisiert oder durch das aktuelle `Labeldrucker`-Repository vollständig ersetzt werden?
- Welche Druckerfamilie neben Zebra soll als erster raster-only Print-Service implementiert werden?
- Welche SLA, Aufbewahrungs-, Datenschutz- und Backup-Ziele gelten produktiv?

## 16. Definition funktionaler Gleichwertigkeit

Ein Neuaufbau ist funktional gleichwertig, wenn mindestens folgende Abnahme erfüllt ist:

- Ein Nutzer kann ohne Thingdex ein Template visuell erstellen, validieren, speichern, wieder laden, befüllen, previewen und drucken.
- Derselbe Job kann über TCP-, USB-Character-Device- und USB-Bulk-Zebra-Transporte sicher verarbeitet werden.
- ZPL- und raster-only Print-Services können gleichzeitig im selben öffentlichen Druckerkatalog existieren.
- Verlorene Antworten und Neustarts führen nicht zu unbeabsichtigten Doppeldrucken.
- Größenabweichungen und Label-Limits erzeugen Holds und können bewusst freigegeben werden.
- Unsichere physische Ausgänge erfordern einen ausdrücklich bestätigten neuen Reprint.
- IPP-Clients können über stabile Queues Dokumente einreichen.
- Drucker, Services, Medien, Queuezustände und IPP-Freigaben sind über Studio administrierbar.
- Backups stellen Identitäten, Jobs, Artefakte, Medienhistorie und Konfiguration konsistent wieder her.
- Optional kann Thingdex Inventar und PrintIntent atomar speichern, später idempotent drucken und signierte Zustandsereignisse übernehmen.
