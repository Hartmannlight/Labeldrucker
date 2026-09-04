#!/usr/bin/env python3
from __future__ import annotations

import selectors
import socket
import sys
import threading


BUFFER_SIZE = 64 * 1024


def relay(client: socket.socket, target_host: str, target_port: int) -> None:
    try:
        upstream = socket.create_connection((target_host, target_port), timeout=10)
    except OSError:
        client.close()
        return
    with client, upstream:
        client.setblocking(False)
        upstream.setblocking(False)
        selector = selectors.DefaultSelector()
        selector.register(client, selectors.EVENT_READ, upstream)
        selector.register(upstream, selectors.EVENT_READ, client)
        try:
            while True:
                for key, _ in selector.select(timeout=60):
                    source = key.fileobj
                    destination = key.data
                    try:
                        data = source.recv(BUFFER_SIZE)
                    except OSError:
                        return
                    if not data:
                        return
                    try:
                        destination.sendall(data)
                    except OSError:
                        return
        finally:
            selector.close()


def serve(bind_host: str, bind_port: int, target_host: str, target_port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((bind_host, bind_port))
        listener.listen(64)
        while True:
            client, _ = listener.accept()
            threading.Thread(
                target=relay,
                args=(client, target_host, target_port),
                daemon=True,
            ).start()


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("usage: tcp_proxy.py BIND_HOST BIND_PORT TARGET_HOST TARGET_PORT")
    serve(sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
