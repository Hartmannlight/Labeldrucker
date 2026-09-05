from __future__ import annotations

import logging
import threading

from .service import DeliveryService
from .discovery import AgentDiscoveryService


class DeliveryWorker:
    """Small single-node worker; database claims prevent duplicate sends."""

    def __init__(self, service: DeliveryService, *, interval_seconds: float = 1.0) -> None:
        self.service = service
        self.interval_seconds = max(0.1, interval_seconds)
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="printer-fleet-deliveries",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=max(2.0, self.interval_seconds * 2))

    def _run(self) -> None:
        logger = logging.getLogger(__name__)
        while not self._stopped.wait(self.interval_seconds):
            try:
                self.service.process_due()
            except Exception:
                logger.exception("Unexpected PrinterFleet worker failure")


class AgentDiscoveryWorker:
    def __init__(self, service: AgentDiscoveryService, *, interval_seconds: float = 30) -> None:
        self.service = service
        self.interval_seconds = max(1.0, interval_seconds)
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="printer-fleet-agent-discovery",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        logger = logging.getLogger(__name__)
        while not self._stopped.is_set():
            try:
                self.service.discover()
            except Exception:
                logger.exception("PrintAgent discovery failed")
            if self._stopped.wait(self.interval_seconds):
                break
