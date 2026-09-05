from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from collections.abc import Sequence

from .composition import repository_from_environment
from .service import DeliveryService


def _repository_check() -> None:
    repository = repository_from_environment()
    repository.initialize()
    repository.metrics_snapshot()


def run() -> int:
    logging.basicConfig(
        level=os.getenv("PRINTER_FLEET_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)
    repository = repository_from_environment()
    repository.initialize()
    recovered = repository.recover_interrupted_deliveries()
    if recovered:
        logger.warning("Recovered %d interrupted deliveries as unconfirmed", recovered)

    service = DeliveryService(
        repository,
        max_parallel_printers=int(
            os.getenv("PRINTER_FLEET_MAX_PARALLEL_PRINTERS", "4")
        ),
    )
    interval_seconds = max(
        0.1, float(os.getenv("PRINTER_FLEET_WORKER_INTERVAL_SECONDS", "1"))
    )
    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("PrinterFleet delivery worker started")
    while not stopped.is_set():
        try:
            service.process_due()
        except Exception:
            logger.exception("Unexpected PrinterFleet worker failure")
        stopped.wait(interval_seconds)
    logger.info("PrinterFleet delivery worker stopped")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PrinterFleet delivery worker")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify database initialization and exit",
    )
    arguments = parser.parse_args(argv)
    if arguments.check:
        _repository_check()
        return 0
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
