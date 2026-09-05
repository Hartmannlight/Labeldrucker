# Prepared print artifact contract

Status: version 1, pre-stable

This contract is the boundary between document preparation in PrintHub and
device encoding in PrinterFleet. PrintHub decides page size, scaling, color
flattening, grayscale conversion and dithering. It does not select a transport
or create a vendor wire payload.

## Raster page

MIME type: `application/vnd.printhub.raster-page+json`

The UTF-8 JSON document contains exactly one prepared label page:

```json
{
  "version": 1,
  "width_px": 400,
  "height_px": 400,
  "dpi": 203,
  "copies": 1,
  "black_bits_base64": "..."
}
```

`black_bits_base64` contains row-major one-bit pixels. Each row occupies
`ceil(width_px / 8)` bytes, most-significant bit first; a set bit means ink.
Rows are byte-aligned and padding bits in the final byte are ignored. The
decoded byte length must equal `ceil(width_px / 8) * height_px`.

PrinterFleet validates the complete envelope before a driver is allowed to
create a device payload. Its Zebra driver converts the bits to ZPL `^GF` and
adds Fleet-owned device settings. A future Niimbot driver can consume the same
bits and apply Niimbot compression and framing. Neither change affects IPP,
Thingdex or the PrintHub job API.

## Native artifacts

`application/zpl` remains supported for templates whose canonical renderer is
currently ZPL-native. PrinterFleet still owns device settings and transport.
Arbitrary native payload submission is not a public PrintHub administration
API; it is an authenticated service-to-service delivery contract.

## Integrity and delivery

Every artifact is immutable and submitted with a SHA-256 checksum and stable
idempotency key. PrinterFleet stores it before device I/O. Acceptance therefore
means durable queueing, not physical printing. A driver creates `DevicePayload`
only inside the Fleet worker after the delivery is claimed for one printer.

