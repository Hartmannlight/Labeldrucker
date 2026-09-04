#!/usr/bin/env python3
"""Generate a deterministic sgray_8 PWG Raster page for integration tests."""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pwg_raster import CupsPageHeader2, _libcups, read_pwg_raster


def main(output: Path) -> None:
    cups = _libcups()
    cups.cupsRasterWriteHeader2.argtypes = [ctypes.c_void_p, ctypes.POINTER(CupsPageHeader2)]
    cups.cupsRasterWriteHeader2.restype = ctypes.c_uint
    cups.cupsRasterWritePixels.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    cups.cupsRasterWritePixels.restype = ctypes.c_uint

    width = height = 400
    header = CupsPageHeader2()
    header.MediaClass = b"PwgRaster"
    header.MediaType = b"labels"
    header.OutputType = b"Grayscale"
    header.HWResolution[:] = (203, 203)
    header.PageSize[:] = (142, 142)
    header.cupsWidth = width
    header.cupsHeight = height
    header.cupsBitsPerColor = 8
    header.cupsBitsPerPixel = 8
    header.cupsBytesPerLine = width
    header.cupsColorOrder = 0
    header.cupsColorSpace = 18
    header.cupsNumColors = 1
    header.cupsPageSize[:] = (141.732, 141.732)
    header.cupsImagingBBox[:] = (0.0, 0.0, 141.732, 141.732)
    header.cupsPageSizeName = b"custom_50x50mm"

    with output.open("wb") as destination:
        raster = cups.cupsRasterOpen(destination.fileno(), 3)
        if not raster:
            raise RuntimeError("Unable to create PWG Raster stream")
        try:
            if not cups.cupsRasterWriteHeader2(raster, ctypes.byref(header)):
                raise RuntimeError("Unable to write PWG Raster header")
            for y in range(height):
                row = bytes(
                    0 if x in {0, width - 1} or y in {0, height - 1} else 255
                    for x in range(width)
                )
                buffer = (ctypes.c_ubyte * width).from_buffer_copy(row)
                if cups.cupsRasterWritePixels(raster, buffer, width) != width:
                    raise RuntimeError("Unable to write PWG Raster pixels")
        finally:
            cups.cupsRasterClose(raster)

    pages = read_pwg_raster(output)
    if len(pages) != 1 or pages[0]["data"][:2] != b"P5":
        raise RuntimeError("Generated PWG Raster did not round-trip through the gateway reader")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
