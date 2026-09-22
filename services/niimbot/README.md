# PrintHub NIIMBOT service

Standalone, authenticated Print Service Protocol v2 adapter for the **B1**.
USB serial and BLE transports, 203 dpi, 384-dot head; B1 Pro is rejected.
No ZPL dependency. One durable SQLite FIFO and one hardware worker per instance.

See [setup, operation and protocol references](../../docs/NIIMBOT.md).

```bash
python -m pip install './services/niimbot[test]'
python -m pytest services/niimbot/tests -q
```

Set `NIIMBOT_TOKEN` (24+ characters), `NIIMBOT_ADDRESS`,
`NIIMBOT_TRANSPORT=serial` or `ble`, `NIIMBOT_WIDTH_MM`, `NIIMBOT_HEIGHT_MM` and
`NIIMBOT_DATA_DIR` before starting:

```bash
python -m uvicorn niimbot_service.app:create_app --factory --host 127.0.0.1 --port 8083 --workers 1
```

Do not use multiple workers, live reload or multiple instances for one printer.
No physical job is automatically replayed after a disconnect or crash.
Held media-conflict jobs must be cancelled and submitted anew after checking
the loaded media. Vendor configuration and queue pause/resume are unsupported
and not advertised. `/healthz` measures service/worker health, not printer readiness.
