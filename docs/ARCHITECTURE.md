# Architecture

The product separates content orchestration from device ownership.

```text
browser / public API / IPP client
                 |
              PrintHub
       templates, rendering, logical jobs,
       public printer IDs and IPP shares
                 |
       print-service protocol v2
          /                    \
   ZebraTamer          raster-only service
 Zebra state + queue    future Niimbot driver
 USB / serial / TCP            Bluetooth
```

PrintHub persists the exact artifact before crossing the service boundary. It
chooses native ZPL when supported and otherwise renders the template to the
neutral one-bit raster envelope. Retries reuse a stable dispatch key. A changed
request under an existing idempotency key is a conflict.

Every print service owns its local printers, hardware configuration, observed
state and physical queue. Its stable service identity plus the local printer ID
forms the public PrintHub printer identity. Consequently, two services can each
have a local printer named `default`.

ZebraTamer contains Zebra-specific queries, configuration, media accounting,
maintenance commands and transports. It accepts both ZPL and neutral raster
jobs. It is equally suitable beside PrintHub on a server for Ethernet printers
and by itself on a small Pi attached over USB.

IPP is an input adapter owned by the PrintHub repository but released as a
separate image because it needs CUPS/Avahi runtime packages. One gateway watches
PrintHub's persistent share registry and manages multiple stable TCP ports.

The default container network is internal. Only PrintHub receives the separate
renderer-egress network for optional Labelary calls. Admin tokens and service
tokens are separate; neither is compiled into Studio.
