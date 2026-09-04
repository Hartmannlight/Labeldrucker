#!/usr/bin/env python3
"""Send Get-Printer-Attributes from a separate container without CUPS bindings."""
from __future__ import annotations

import http.client
import struct
import sys


def attribute(tag: int, name: str, value: str) -> bytes:
    encoded_name = name.encode("ascii")
    encoded_value = value.encode("ascii")
    return bytes([tag]) + struct.pack(">H", len(encoded_name)) + encoded_name + struct.pack(">H", len(encoded_value)) + encoded_value


def request_body(printer_uri: str) -> bytes:
    return b"".join(
        [
            b"\x02\x00",  # IPP 2.0
            b"\x00\x0b",  # Get-Printer-Attributes
            b"\x00\x00\x00\x01",
            b"\x01",  # operation-attributes-tag
            attribute(0x47, "attributes-charset", "utf-8"),
            attribute(0x48, "attributes-natural-language", "en"),
            attribute(0x45, "printer-uri", printer_uri),
            attribute(0x44, "requested-attributes", "all"),
            attribute(0x44, "", "media-col-database"),
            b"\x03",  # end-of-attributes-tag
        ]
    )


def main(connect_host: str, port: int, advertised_host: str) -> None:
    printer_uri = f"ipp://{advertised_host}:{port}/ipp/print"
    connection = http.client.HTTPConnection(connect_host, port, timeout=10)
    connection.request(
        "POST",
        "/ipp/print",
        body=request_body(printer_uri),
        headers={
            "Content-Type": "application/ipp",
            "Host": f"{advertised_host}:{port}",
        },
    )
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    if response.status != 200:
        raise RuntimeError(f"HTTP status is {response.status}")
    if len(payload) < 8 or payload[:2] != b"\x02\x00":
        raise RuntimeError("Response is not IPP 2.0")
    ipp_status = int.from_bytes(payload[2:4], "big")
    if ipp_status > 0x00FF:
        raise RuntimeError(f"IPP request failed with status 0x{ipp_status:04x}")
    if b"document-format-supported" not in payload or b"media-col-database" not in payload:
        raise RuntimeError("IPP response is missing required printer capabilities")
    print(f"PASS: {connect_host}:{port} returned valid IPP capabilities for {advertised_host}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: network_probe.py CONNECT_HOST PORT ADVERTISED_HOST")
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
