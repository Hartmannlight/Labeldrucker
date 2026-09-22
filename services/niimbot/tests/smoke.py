"""Run inside the built image, isolated from network and hardware."""
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

os.environ.update(NIIMBOT_TOKEN=secrets.token_hex(32), NIIMBOT_ADDRESS="/dev/no-niimbot-in-smoke-test",
                  NIIMBOT_TRANSPORT="serial", NIIMBOT_WIDTH_MM="1", NIIMBOT_HEIGHT_MM="1")
server = subprocess.Popen([sys.executable, "-m", "uvicorn", "niimbot_service.app:create_app", "--factory",
                           "--host", "127.0.0.1", "--port", "8080"], stdout=subprocess.DEVNULL)


def request(path, data=None, auth=True):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Bearer " + os.environ["NIIMBOT_TOKEN"]
    with urlopen(Request("http://127.0.0.1:8080" + path, data=None if data is None else json.dumps(data).encode(), headers=headers), timeout=3) as response:
        return json.load(response)


try:
    for attempt in range(30):
        try:
            assert request("/healthz")["status"] == "ok"
            break
        except URLError:
            if server.poll() is not None or attempt == 29:
                raise
            time.sleep(.1)
    try:
        request("/v2/service", auth=False)
        raise AssertionError("Missing auth was accepted")
    except HTTPError as exc:
        assert exc.code == 401
    assert request("/v2/printers/b1")["profile"]["resolution_dpi"] == 203
    raster = json.dumps(dict(version=1, copies=1, dpi=203, width_px=8, height_px=8,
                             black_bits_base64=base64.b64encode(bytes(8)).decode())).encode()
    body = dict(idempotency_key="smoke", artifacts=[dict(mime_type="application/vnd.printhub.raster-page+json",
                sha256=hashlib.sha256(raster).hexdigest(), data_base64=base64.b64encode(raster).decode())])
    accepted = request("/v2/printers/b1/jobs", body)
    for attempt in range(30):
        job = request("/v2/jobs/" + accepted["id"])
        if job["state"] == "failed":
            break
        time.sleep(.1)
    assert job["state"] == "failed", job
    assert job["bytes_transferred"] == 0
    assert request("/v2/printers/b1/jobs", body)["id"] == job["id"]
    print("NIIMBOT container smoke passed: non-root, read-only, auth, durable queue, offline failure, idempotency")
finally:
    server.terminate()
    server.wait(timeout=10)
