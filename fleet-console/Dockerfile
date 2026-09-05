FROM nginx:stable-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6

RUN apk upgrade --no-cache \
    && apk add --no-cache gettext \
    && mkdir -p /etc/nginx/http.d /opt/fleet-console /usr/share/nginx/html \
    && chown -R nginx:nginx /etc/nginx/http.d /opt/fleet-console /usr/share/nginx/html

COPY --chown=nginx:nginx index.html app.js api.js styles.css /usr/share/nginx/html/
COPY nginx.runtime.conf /etc/nginx/nginx.conf
COPY default.conf.template /opt/fleet-console/default.conf.template
COPY docker-entrypoint.d/99-fleet-console-config.sh /docker-entrypoint.d/99-fleet-console-config.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/99-fleet-console-config.sh \
    && chmod +x /docker-entrypoint.d/99-fleet-console-config.sh

ENV FLEET_API_UPSTREAM=http://printer-fleet:8000
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/ >/dev/null || exit 1
