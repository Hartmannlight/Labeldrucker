# PrinterFleet Console

PrinterFleet Console is the independently deployable operator interface for
the physical-printer control plane. It talks only to the PrinterFleet API and
does not render templates, prepare documents or access Thingdex.

The browser supplies an operator bearer credential on each API request. The
credential is retained only in JavaScript memory, is cleared on reload and is
never embedded in the image or written to browser storage. Deploy the console
behind TLS and normal enterprise access controls. PrinterFleet remains the
authorization authority for roles and sites.

The first console slice supports:

- direct RAW TCP/JetDirect and serial-over-TCP printer registration;
- site-scoped printer inventory and revision-checked display-name changes;
- live status, persistent pause/resume and allowlisted Zebra maintenance;
- durable delivery history;
- global PrintAgent discovery and audit views when the credential permits it.

Run the container on the same private network as PrinterFleet:

```sh
docker build -t printer-fleet-console fleet-console
docker run --rm -p 127.0.0.1:8089:8080 \
  -e FLEET_API_UPSTREAM=http://printer-fleet:8000 \
  printer-fleet-console
```

No PrinterFleet credential belongs in the container environment. Operator
credentials are entered interactively and forwarded through the same-origin
`/api` proxy.
