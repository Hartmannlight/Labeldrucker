"""Run a bounded health and privilege smoke test for product candidate images."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import sys
import threading
import time
import urllib.request


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


class EmptyPrintHub(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/ipp-shares":
            body = b'{"items":[]}'
        else:
            body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def wait_http(url: str) -> None:
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


def wait_container_http(container: str, url: str) -> None:
    deadline = time.monotonic() + 90
    probe = (
        "import urllib.request; "
        f"response = urllib.request.urlopen({url!r}, timeout=2); "
        "assert response.status == 200"
    )
    while True:
        result = subprocess.run(
            ["docker", "exec", container, "python", "-c", probe],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"container health endpoint did not become ready: {url}")
        time.sleep(1)


def main() -> None:
    component, image = sys.argv[1:3]
    ports = {
        "zebratamer": (8080, "/healthz"),
        "printhub": (8000, "/health"),
        "printhub-studio": (80, "/"),
        "printhub-ipp": (8799, "/healthz"),
    }
    if component not in ports:
        raise RuntimeError(f"unexpected component: {component}")
    port, path = ports[component]
    args = ["docker", "run", "-d", "--cap-drop=ALL", "--security-opt=no-new-privileges:true"]
    mock: ThreadingHTTPServer | None = None
    if component == "zebratamer":
        args += ["-e", "RUST_LOG=warn"]
    elif component == "printhub-ipp":
        mock = ThreadingHTTPServer(("0.0.0.0", 18080), EmptyPrintHub)
        threading.Thread(target=mock.serve_forever, daemon=True).start()
        args += [
            "--cap-add=CHOWN",
            "--cap-add=DAC_OVERRIDE",
            "--cap-add=FOWNER",
            "--cap-add=SETGID",
            "--cap-add=SETUID",
            "--add-host=host.docker.internal:host-gateway",
            "-e",
            "PRINTHUB_API_URL=http://host.docker.internal:18080",
        ]
    if component != "printhub-ipp":
        args += ["-p", f"127.0.0.1::{port}"]
    args.append(image)
    container = run(*args)
    try:
        if component == "printhub-ipp":
            wait_container_http(container, f"http://127.0.0.1:{port}{path}")
        else:
            binding = run("docker", "port", container, f"{port}/tcp").splitlines()[0]
            host, host_port = binding.rsplit(":", 1)
            wait_http(f"http://{host}:{host_port}{path}")
        uid_status = run("docker", "exec", container, "cat", "/proc/1/status")
        uid = next(
            line.split()[1] for line in uid_status.splitlines() if line.startswith("Uid:")
        )
        if uid == "0":
            raise RuntimeError("candidate process still runs as root after startup")
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False)
        if mock:
            mock.shutdown()


if __name__ == "__main__":
    main()
