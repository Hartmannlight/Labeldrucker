FROM python:3.11-slim-trixie@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LC_ALL=C \
    PRINTHUB_API_URL=http://printhub:8000 \
    PRINTHUB_IPP_PORT=8631 \
    PRINTHUB_IPP_PRINTER_ID=virtual-zebra \
    PRINTHUB_IPP_MISMATCH_POLICY=hold

RUN DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends avahi-daemon ca-certificates cups-ipp-utils dbus-daemon \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10002 --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app /run/printhub-ipp /var/spool/printhub-ipp \
    && chown -R appuser:appuser /app /run/printhub-ipp /var/spool/printhub-ipp

COPY --chown=appuser:appuser --chmod=0555 entrypoint.py submit_job.py tcp_proxy.py /app/

EXPOSE 8631
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import os,socket; socket.create_connection(('127.0.0.1', int(os.getenv('PRINTHUB_IPP_PORT','8631'))), 2).close()"]
ENTRYPOINT ["python", "/app/entrypoint.py"]
