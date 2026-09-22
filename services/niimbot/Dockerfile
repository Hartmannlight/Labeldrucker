FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY niimbot_service ./niimbot_service
RUN pip install --no-cache-dir . && \
    useradd --uid 10001 --create-home niimbot && \
    mkdir /data && chown niimbot:niimbot /data
USER 10001:10001
ENV NIIMBOT_DATA_DIR=/data
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["uvicorn", "niimbot_service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
