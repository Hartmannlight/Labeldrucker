# PrinterFleet

PrinterFleet is the physical-delivery boundary of the printing platform. It
owns printer endpoints, device capabilities, delivery records, drivers and
transports. It deliberately does not own templates, inventory data or document
layout.

The first vertical slice supports ZPL artifacts over `raw_tcp`, the legacy
`raw9100` spelling and `serial_over_tcp`. A successful socket write is recorded
as `transport_accepted`, never as a confirmed physical print.

This directory incubates an independently deployable service. It is intended
to become its own repository once its v1 contract is stable.
