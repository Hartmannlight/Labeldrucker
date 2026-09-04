from __future__ import annotations

import ctypes
import ctypes.util
import os
from pathlib import Path
from typing import Any


class CupsPageHeader2(ctypes.Structure):
    _fields_ = [
        ("MediaClass", ctypes.c_char * 64),
        ("MediaColor", ctypes.c_char * 64),
        ("MediaType", ctypes.c_char * 64),
        ("OutputType", ctypes.c_char * 64),
        ("AdvanceDistance", ctypes.c_uint),
        ("AdvanceMedia", ctypes.c_uint),
        ("Collate", ctypes.c_uint),
        ("CutMedia", ctypes.c_uint),
        ("Duplex", ctypes.c_uint),
        ("HWResolution", ctypes.c_uint * 2),
        ("ImagingBoundingBox", ctypes.c_uint * 4),
        ("InsertSheet", ctypes.c_uint),
        ("Jog", ctypes.c_uint),
        ("LeadingEdge", ctypes.c_uint),
        ("Margins", ctypes.c_uint * 2),
        ("ManualFeed", ctypes.c_uint),
        ("MediaPosition", ctypes.c_uint),
        ("MediaWeight", ctypes.c_uint),
        ("MirrorPrint", ctypes.c_uint),
        ("NegativePrint", ctypes.c_uint),
        ("NumCopies", ctypes.c_uint),
        ("Orientation", ctypes.c_uint),
        ("OutputFaceUp", ctypes.c_uint),
        ("PageSize", ctypes.c_uint * 2),
        ("Separations", ctypes.c_uint),
        ("TraySwitch", ctypes.c_uint),
        ("Tumble", ctypes.c_uint),
        ("cupsWidth", ctypes.c_uint),
        ("cupsHeight", ctypes.c_uint),
        ("cupsMediaType", ctypes.c_uint),
        ("cupsBitsPerColor", ctypes.c_uint),
        ("cupsBitsPerPixel", ctypes.c_uint),
        ("cupsBytesPerLine", ctypes.c_uint),
        ("cupsColorOrder", ctypes.c_uint),
        ("cupsColorSpace", ctypes.c_uint),
        ("cupsCompression", ctypes.c_uint),
        ("cupsRowCount", ctypes.c_uint),
        ("cupsRowFeed", ctypes.c_uint),
        ("cupsRowStep", ctypes.c_uint),
        ("cupsNumColors", ctypes.c_uint),
        ("cupsBorderlessScalingFactor", ctypes.c_float),
        ("cupsPageSize", ctypes.c_float * 2),
        ("cupsImagingBBox", ctypes.c_float * 4),
        ("cupsInteger", ctypes.c_uint * 16),
        ("cupsReal", ctypes.c_float * 16),
        ("cupsString", (ctypes.c_char * 64) * 16),
        ("cupsMarkerType", ctypes.c_char * 64),
        ("cupsRenderingIntent", ctypes.c_char * 64),
        ("cupsPageSizeName", ctypes.c_char * 64),
    ]


def _libcups() -> Any:
    library = ctypes.util.find_library("cups") or "libcups.so.2"
    cups = ctypes.CDLL(library)
    cups.cupsRasterOpen.argtypes = [ctypes.c_int, ctypes.c_int]
    cups.cupsRasterOpen.restype = ctypes.c_void_p
    cups.cupsRasterReadHeader2.argtypes = [ctypes.c_void_p, ctypes.POINTER(CupsPageHeader2)]
    cups.cupsRasterReadHeader2.restype = ctypes.c_uint
    cups.cupsRasterReadPixels.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    cups.cupsRasterReadPixels.restype = ctypes.c_uint
    cups.cupsRasterClose.argtypes = [ctypes.c_void_p]
    cups.cupsRasterClose.restype = None
    return cups


def read_pwg_raster(path: Path) -> list[dict[str, Any]]:
    maximum_pages = max(1, int(os.getenv("PRINTHUB_IPP_MAX_PAGES", "100")))
    maximum_pixels = max(1, int(os.getenv("PRINTHUB_IPP_MAX_PIXELS_PER_PAGE", "100000000")))
    cups = _libcups()
    pages: list[dict[str, Any]] = []
    with path.open("rb") as source:
        raster = cups.cupsRasterOpen(source.fileno(), 0)
        if not raster:
            raise RuntimeError("Unable to open PWG Raster document")
        try:
            while True:
                header = CupsPageHeader2()
                if not cups.cupsRasterReadHeader2(raster, ctypes.byref(header)):
                    break
                width = int(header.cupsWidth)
                height = int(header.cupsHeight)
                bytes_per_line = int(header.cupsBytesPerLine)
                if width <= 0 or height <= 0 or width * height > maximum_pixels:
                    raise RuntimeError("PWG Raster page dimensions exceed the configured limit")
                if (
                    header.cupsBitsPerColor != 8
                    or header.cupsBitsPerPixel != 8
                    or header.cupsNumColors != 1
                    or bytes_per_line < width
                ):
                    raise RuntimeError(
                        "Unsupported PWG Raster type; PrintHub accepts sgray_8 pages"
                    )
                if len(pages) >= maximum_pages:
                    raise RuntimeError(f"Document exceeds the configured {maximum_pages}-page limit")
                row_buffer = (ctypes.c_ubyte * bytes_per_line)()
                pixels = bytearray(width * height)
                for row in range(height):
                    count = cups.cupsRasterReadPixels(raster, row_buffer, bytes_per_line)
                    if count != bytes_per_line:
                        raise RuntimeError("PWG Raster page ended before all rows were read")
                    start = row * width
                    pixels[start : start + width] = bytes(row_buffer[:width])
                xdpi = int(header.HWResolution[0])
                ydpi = int(header.HWResolution[1])
                if xdpi <= 0 or ydpi <= 0:
                    raise RuntimeError("PWG Raster page has no valid resolution")
                width_mm = (
                    float(header.cupsPageSize[0]) * 25.4 / 72.0
                    if header.cupsPageSize[0] > 0
                    else width * 25.4 / xdpi
                )
                height_mm = (
                    float(header.cupsPageSize[1]) * 25.4 / 72.0
                    if header.cupsPageSize[1] > 0
                    else height * 25.4 / ydpi
                )
                pgm = f"P5\n{width} {height}\n255\n".encode("ascii") + pixels
                pages.append(
                    {
                        "mime_type": "image/x-portable-graymap",
                        "data": pgm,
                        "width_mm": width_mm,
                        "height_mm": height_mm,
                    }
                )
        finally:
            cups.cupsRasterClose(raster)
    if not pages:
        raise RuntimeError("PWG Raster document contains no pages")
    return pages
