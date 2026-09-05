"""Run a bounded smoke test against an exact root-owned candidate image."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


class PrinterHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps(
            {
                "id": "release-smoke",
                "name": "Release smoke",
                "vendor": "PrintHub",
                "model": "Virtual label",
                "media": {"loaded": {"width_mm": 50, "height_mm": 50}},
                "alignment": {"dpi": 203},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def wait_http(url: str) -> None:
    deadline = time.monotonic() + 60
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


def main() -> None:
    component = sys.argv[1]
    image = sys.argv[2]
    args = ["docker", "run", "-d", "--cap-drop=ALL", "--security-opt=no-new-privileges:true"]
    mock: ThreadingHTTPServer | None = None
    if component == "printer-fleet":
        args += [
            "-e", "PRINTER_FLEET_MDNS_ENABLED=0",
            "-e", "PRINTER_FLEET_API_TOKEN=smoke-secret",
            "-p", "127.0.0.1::8000",
        ]
        container_port = "8000/tcp"
    elif component == "printhub-ipp":
        mock = ThreadingHTTPServer(("0.0.0.0", 18080), PrinterHandler)
        threading.Thread(target=mock.serve_forever, daemon=True).start()
        args += [
            "--add-host", "host.docker.internal:host-gateway",
            "-e", "PRINTHUB_API_URL=http://host.docker.internal:18080",
            "-e", "PRINTHUB_IPP_PRINTER_ID=release-smoke",
            "-e", "PRINTHUB_IPP_MDNS_ENABLED=0",
            "-p", "127.0.0.1::8631",
        ]
        container_port = "8631/tcp"
    else:
        raise RuntimeError("Unexpected component")
    container = run(*args, image)
    try:
        binding = run("docker", "port", container, container_port).splitlines()[0]
        host, port_text = binding.rsplit(":", 1)
        if component == "printer-fleet":
            wait_http(f"http://{host}:{port_text}/health")
            request = urllib.request.Request(
                f"http://{host}:{port_text}/metrics",
                headers={"Authorization": "Bearer smoke-secret"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                assert b"printer_fleet_printers" in response.read()
        else:
            deadline = time.monotonic() + 60
            while True:
                try:
                    with socket.create_connection((host, int(port_text)), timeout=2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
        uid = run("docker", "exec", container, "python", "-c", "import os; print(os.getuid())")
        if uid == "0":
            raise RuntimeError("Candidate process still runs as root after startup")
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False)
        if mock:
            mock.shutdown()


if __name__ == "__main__":
    main()
