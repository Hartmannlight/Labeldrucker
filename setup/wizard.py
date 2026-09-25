"""Interactive, one-time PrintHub installer. Uses only the Python standard library."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable


ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
PROJECT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")
ENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=")
USB_CONFIG = """listen = "0.0.0.0:8080"
data_dir = "/var/lib/zpl-agent"
storage_mode = "full"
webui_enabled = false
read_token_file = "/run/printhub-secrets/zebratamer-token"
print_token_file = "/run/printhub-secrets/zebratamer-token"
admin_token_file = "/run/printhub-secrets/zebratamer-token"
mdns_enabled = false
"""


class Prompts:
    def __init__(self, ask: Callable[[str], str] = input,
                 secret: Callable[[str], str] = getpass.getpass,
                 say: Callable[[str], None] = print) -> None:
        self.ask = ask
        self.secret = secret
        self.say = say

    def text(self, label: str, default: str = "", *, required: bool = False,
             check: Callable[[str], bool] | None = None) -> str:
        while True:
            suffix = f" [{default}]" if default else ""
            value = self.ask(f"{label}{suffix}: ").strip() or default
            if required and not value:
                self.say("Bitte einen Wert eingeben.")
            elif "\n" in value or "\r" in value or (check and not check(value)):
                self.say("Ungültiger Wert; bitte erneut eingeben.")
            else:
                return value

    def yes(self, label: str, default: bool = False) -> bool:
        suffix = "J/n" if default else "j/N"
        while True:
            answer = self.ask(f"{label} [{suffix}]: ").strip().casefold()
            if not answer:
                return default
            if answer in {"j", "ja", "y", "yes"}:
                return True
            if answer in {"n", "nein", "no"}:
                return False
            self.say("Bitte j oder n eingeben.")

    def number(self, label: str, default: int, low: int, high: int) -> int:
        while True:
            raw = self.text(label, str(default))
            try:
                value = int(raw)
            except ValueError:
                value = -1
            if low <= value <= high:
                return value
            self.say(f"Bitte eine ganze Zahl von {low} bis {high} eingeben.")

    def size(self, label: str, default: float) -> float:
        while True:
            raw = self.text(label, str(default)).replace(",", ".")
            try:
                value = float(raw)
            except ValueError:
                value = 0
            if 0 < value <= 1000:
                return value
            self.say("Bitte eine Größe zwischen 0 und 1000 mm eingeben.")


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ENV_LINE.match(line)
        if not match:
            continue
        value = line[match.end():].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[match.group(1)] = value
    return values


def env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@~+,-]*", value):
        return value
    return "'" + value.replace("'", "\\'") + "'"


def merge_env(source: str, updates: dict[str, str]) -> str:
    found: set[str] = set()
    output: list[str] = []
    for line in source.splitlines():
        match = ENV_LINE.match(line)
        key = match.group(1) if match else None
        if key in updates:
            if key not in found:
                output.append(f"{key}={env_value(updates[key])}")
                found.add(key)
        else:
            output.append(line)
    if output and output[-1]:
        output.append("")
    output.append("# Values written by the PrintHub setup wizard.")
    output.extend(f"{key}={env_value(value)}" for key, value in updates.items() if key not in found)
    return "\n".join(output).rstrip() + "\n"


def write_atomic(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def valid_host(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value))


def printer_answers(io: Prompts, index: int, existing_ids: set[str], existing_queues: set[str]) -> dict:
    io.say(f"\nDrucker {index}: 1 = Ethernet/RAW 9100, 2 = Linux-USB-Gerät")
    transport_choice = io.number("Verbindung", 1, 1, 2)
    while True:
        printer_id = io.text("Drucker-ID", f"zebra-{index}", required=True,
                             check=lambda value: bool(ID_PATTERN.fullmatch(value)))
        if printer_id not in existing_ids:
            break
        io.say("Diese Drucker-ID wurde bereits verwendet.")
    name = io.text("Anzeigename", printer_id, required=True)
    if transport_choice == 1:
        service = "default"
        transport = "tcp"
        host = io.text("IP-Adresse oder DNS-Name des Druckers", required=True, check=valid_host)
        port = io.number("RAW-Port", 9100, 1, 65535)
        connection = {"tcp_host": host, "tcp_port": port, "device": ""}
    else:
        service = "usb-local"
        transport = "char_device"
        device = io.text("Stabiler Linux-Gerätepfad, z. B. /dev/usb/lp0", required=True,
                         check=lambda value: value.startswith("/dev/") and " " not in value)
        connection = {"tcp_host": None, "tcp_port": 9100, "device": device}
    dpi = io.number("Tatsächliche Druckerauflösung (DPI)", 203, 100, 1200)
    width = io.size("Eingelegte Etikettenbreite (mm)", 50)
    height = io.size("Eingelegte Etikettenhöhe (mm)", 25)
    media_name = io.text("Name der Etikettenrolle", f"{width:g} × {height:g} mm", required=True)
    io.say("Bei unbekanntem Rollenbestand 0 eingeben; Studio zeigt dann 0 verbleibende Etiketten.")
    quantity = io.number("Geschätzte Etiketten auf der eingelegten Rolle", 0, 0, 10_000_000)
    io.say("Medienerkennung: 1 = Lücke, 2 = schwarze Marke, 3 = Endlos")
    tracking = {1: "gap", 2: "black_mark", 3: "continuous"}[
        io.number("Medienerkennung", 1, 1, 3)]
    thermal_transfer = io.yes("Thermotransfer mit Farbband?", False)
    ipp = None
    if io.yes("Diesen Drucker über IPP für Betriebssysteme freigeben?", False):
        while True:
            queue_id = io.text("IPP-Freigabe-ID", printer_id, required=True,
                               check=lambda value: bool(ID_PATTERN.fullmatch(value)))
            if queue_id not in existing_queues:
                break
            io.say("Diese IPP-Freigabe-ID wurde bereits verwendet.")
        ipp = {"queue_id": queue_id, "display_name": name}
    return {
        "id": printer_id, "display_name": name, "service": service,
        "transport": transport, **connection, "dpi": dpi,
        "media": {"display_name": media_name, "width_mm": width,
                  "height_mm": height, "labels_available_at_load": quantity,
                  "tracking": tracking,
                  "print_technology": "thermal_transfer" if thermal_transfer else "direct_thermal"},
        "ipp": ipp,
    }


def run(root: Path, io: Prompts) -> bool:
    root = root.resolve()
    example = root / ".env.example"
    if not example.is_file():
        raise RuntimeError(f".env.example fehlt unter {root}")
    env_path = root / ".env"
    existing = read_env(env_path)
    previous_manifest_path = root / "config" / "printhub-install.json"
    previous_manifest = json.loads(previous_manifest_path.read_text(encoding="utf-8")) if previous_manifest_path.exists() else {}
    if not isinstance(previous_manifest, dict) or not isinstance(previous_manifest.get("printers", []), list):
        raise ValueError("Das vorhandene Installationsmanifest ist ungültig")
    io.say("PrintHub Setup – einmalig ausführen, danach docker compose up -d.")
    if env_path.exists():
        io.say("Vorhandene .env gefunden. Nicht abgefragte Einträge bleiben erhalten.")
    project = io.text("Installationsname", existing.get("COMPOSE_PROJECT_NAME", "printhub"),
                      required=True, check=lambda value: bool(PROJECT_PATTERN.fullmatch(value)))
    lan_default = existing.get("PRINTHUB_STUDIO_BIND", "127.0.0.1") not in {"127.0.0.1", "localhost"}
    lan = io.yes("Studio im lokalen Netzwerk erreichbar machen?", lan_default)
    previous_bind = existing.get("PRINTHUB_STUDIO_BIND", "")
    suggested_bind = previous_bind if previous_bind not in {"", "localhost", "127.0.0.1"} else "0.0.0.0"
    studio_bind = io.text("Studio-Bind-Adresse", suggested_bind,
                          required=True, check=valid_host) if lan else "127.0.0.1"
    studio_port = io.number("Studio-Port", int(existing.get("PRINTHUB_STUDIO_PORT", "8088")), 1, 65535)
    timezone = io.text("Zeitzone", existing.get("TZ", "Europe/Berlin"), required=True,
                       check=lambda value: bool(re.fullmatch(r"[A-Za-z0-9_+./-]+", value)))

    printers = previous_manifest.get("printers", [])
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in printers):
        raise ValueError("Das vorhandene Installationsmanifest enthält ungültige Drucker")
    if printers and io.yes("Gespeicherte Druckerangaben neu erfassen?", False):
        printers = []
    io.say("Drucker können alternativ später im Studio hinzugefügt werden.")
    while io.yes("Jetzt einen Drucker hinzufügen?", not printers):
        printer = printer_answers(
            io, len(printers) + 1, {item["id"] for item in printers},
            {item["ipp"]["queue_id"] for item in printers if item.get("ipp")},
        )
        if printer["service"] == "usb-local" and any(item["service"] == "usb-local" for item in printers):
            io.say("Das USB-Overlay unterstützt hier nur ein direkt zugeordnetes Gerät.")
            continue
        printers.append(printer)
        if len(printers) >= 20:
            break

    ipp_requested = any(item.get("ipp") for item in printers)
    ipp_lan = io.yes("IPP für andere Geräte im LAN erreichbar machen?", lan) if ipp_requested else False
    ipp_hostname = existing.get("PRINTHUB_IPP_HOSTNAME", "localhost")
    if ipp_requested:
        ipp_hostname = io.text("Für IPP-Clients erreichbarer Hostname oder IP", ipp_hostname if ipp_hostname != "localhost" or not ipp_lan else "", required=True, check=valid_host)
        if ipp_lan and ipp_hostname in {"localhost", "127.0.0.1"}:
            raise RuntimeError("Für IPP im LAN muss ein vom Client erreichbarer Host angegeben werden")

    io.say("Labelary erhält nur die Daten der jeweils aktivierten Funktion.")
    stored = io.yes("Gespeicherte Vorlagenbilder aus Beispieldaten erzeugen?", existing.get("ZPLGRID_ENABLE_LABELARY_TEMPLATES", "0") == "1")
    live = io.yes("Live-Vorschau mit eingegebenen Daten aktivieren?", existing.get("ZPLGRID_ENABLE_LABELARY_API", "0") == "1")
    draft = io.yes("API-Druckentwurfsvorschau aktivieren?", existing.get("ZPLGRID_ENABLE_LABELARY_PREVIEW", "0") == "1")

    ai_enabled = io.yes("OpenRouter für KI-Vorlagen verwenden?", bool(existing.get("PRINTHUB_AI_API_KEY")))
    ai_key = ""
    model = existing.get("PRINTHUB_AI_MODEL", "")
    if model == "~openai/gpt-sol-latest":
        model = ""
    if ai_enabled:
        ai_key = io.secret("OpenRouter API-Key (leer = vorhandenen Key behalten): ").strip() or existing.get("PRINTHUB_AI_API_KEY", "")
        if not ai_key or any(character in ai_key for character in "\r\n"):
            raise RuntimeError("Ein gültiger OpenRouter API-Key ist erforderlich")
        io.say("Modell-ID aus OpenRouter eingeben; das Modell muss JSON-Schema-Ausgaben unterstützen.")
        model = io.text("OpenRouter-Modell-ID", model, required=True,
                        check=lambda value: bool(re.fullmatch(r"[A-Za-z0-9_~./:-]+", value)))

    usb_printers = [item for item in printers if item["service"] == "usb-local"]
    updates = {
        "COMPOSE_PROJECT_NAME": project,
        "PRINTHUB_STUDIO_BIND": studio_bind,
        "PRINTHUB_STUDIO_PORT": str(studio_port),
        "PRINTHUB_IPP_BIND": "0.0.0.0" if ipp_lan else "127.0.0.1",
        "PRINTHUB_IPP_HOSTNAME": ipp_hostname if ipp_requested else "localhost",
        "ZPLGRID_ENABLE_LABELARY_TEMPLATES": "1" if stored else "0",
        "ZPLGRID_ENABLE_LABELARY_API": "1" if live else "0",
        "ZPLGRID_ENABLE_LABELARY_PREVIEW": "1" if draft else "0",
        "PRINTHUB_AI_API_KEY": ai_key,
        "PRINTHUB_AI_MODEL": model,
        "TZ": timezone,
        "ZEBRATAMER_USB_DEVICE": usb_printers[0]["device"] if usb_printers else "",
    }
    manifest = {"version": 1, "printers": printers}
    io.say("\nZusammenfassung:")
    io.say(f"  Studio: {studio_bind}:{studio_port}; Zeitzone: {timezone}")
    io.say(f"  Drucker: {', '.join(item['display_name'] for item in printers) or 'später im Studio'}")
    io.say(f"  IPP-Freigaben: {sum(bool(item.get('ipp')) for item in printers)}; Host: {ipp_hostname if ipp_requested else '—'}")
    io.say(f"  Labelary: Vorlagenbilder={stored}, Live={live}, API-Entwürfe={draft}")
    io.say(f"  OpenRouter: {'aktiviert, Modell ' + model if ai_enabled else 'deaktiviert'} (Key wird nicht angezeigt)")
    if not io.yes("Konfiguration schreiben?", True):
        io.say("Abgebrochen; keine Dateien geändert.")
        return False

    source = env_path.read_text(encoding="utf-8") if env_path.exists() else example.read_text(encoding="utf-8")
    write_atomic(env_path, merge_env(source, updates))
    write_atomic(previous_manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    if usb_printers:
        usb_config = root / "config" / "zebratamer.usb.toml"
        if not usb_config.exists():
            write_atomic(usb_config, USB_CONFIG, 0o644)
    io.say("\n.env und config/printhub-install.json geschrieben.")
    if usb_printers:
        io.say("Start: docker compose -f compose.yaml -f compose.usb.yaml --profile usb up -d")
        io.say("USB-Gerätepfad und Zugriffsrechte auf dem Linux-Host müssen erreichbar sein.")
    else:
        io.say("Start: docker compose up -d")
    io.say("Der kurzlebige Dienst config-apply übernimmt neue Drucker, Medien und IPP-Freigaben nach dem Start.")
    if ipp_requested:
        io.say("IPP: Die endgültigen ipp://HOST:PORT/ipp/print-Adressen nach dem Start im Studio prüfen.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Interaktiver PrintHub-Installationsassistent")
    parser.add_argument("--root", type=Path, default=Path("/workspace"))
    args = parser.parse_args()
    try:
        run(args.root, Prompts())
    except (EOFError, KeyboardInterrupt):
        print("\nAbgebrochen; keine weiteren Eingaben.")
        raise SystemExit(1) from None
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Setup fehlgeschlagen: {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
