#!/bin/sh
set -eu

: "${FLEET_API_UPSTREAM:?Set FLEET_API_UPSTREAM to the PrinterFleet API base URL}"

case "$FLEET_API_UPSTREAM" in
  http://*|https://*) ;;
  *) echo "FLEET_API_UPSTREAM must be an http(s) URL" >&2; exit 1 ;;
esac

envsubst '${FLEET_API_UPSTREAM}' \
  < /opt/fleet-console/default.conf.template \
  > /etc/nginx/http.d/default.conf
