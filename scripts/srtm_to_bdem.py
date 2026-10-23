#!/usr/bin/env python3
"""
Convert an SRTM 1 arc-second .hgt / .hgt.gz tile (e.g. N35W112) to BICTR .bdem.

The DRATS 2022 sites near SP Crater, AZ all fall in tile N35W112
(lat 35..36, lon -112..-111). When using the result with bictr_channel.c set
bictr_body_radius = 6371000.0 (Earth) instead of the lunar default.

Usage (from the BICTR_Data folder):
  PYTHONPATH=scripts/.pylib python3 scripts/srtm_to_bdem.py \
      DRATS/terrain/N35W112.hgt.gz -o DRATS/terrain/srtm1_N35W112_sp_crater.bdem \
      [--crop 35.50 35.75 -111.75 -111.50]
"""

from __future__ import annotations

import argparse
import gzip
import math
import os
import re
import struct
import sys

import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("hgt")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--crop", nargs=4, type=float, metavar=("MIN_LAT", "MAX_LAT", "MIN_LON", "MAX_LON"))
    args = ap.parse_args()

    m = re.match(r"([NS])(\d{2})([EW])(\d{3})", os.path.basename(args.hgt).upper())
    if not m:
        print("tile name must look like N35W112.hgt[.gz]", file=sys.stderr)
        return 2
    lat0 = int(m.group(2)) * (1 if m.group(1) == "N" else -1)
    lon0 = int(m.group(4)) * (1 if m.group(3) == "E" else -1)

    opener = gzip.open if args.hgt.endswith(".gz") else open
    with opener(args.hgt, "rb") as f:
        raw = f.read()
    n = int(round(math.sqrt(len(raw) // 2)))
    if n * n * 2 != len(raw):
        print(f"unexpected .hgt size {len(raw)}", file=sys.stderr)
        return 1

    z = np.frombuffer(raw, dtype=">i2").reshape(n, n).astype(np.float32)
    z = np.flipud(z)  # .hgt row 0 is the northern edge; BDEM row 0 is min_lat

    void = z == -32768
    if void.any():
        # fill SRTM voids with the nearest valid value along each row
        idx = np.where(~void, np.arange(n)[None, :], 0)
        np.maximum.accumulate(idx, axis=1, out=idx)
        z = z[np.arange(n)[:, None], idx]
        print(f"filled {int(void.sum())} void samples", file=sys.stderr)

    lats = lat0 + np.arange(n) / (n - 1)
    lons = lon0 + np.arange(n) / (n - 1)
    if args.crop:
        la0, la1, lo0, lo1 = args.crop
        r = np.where((lats >= la0) & (lats <= la1))[0]
        c = np.where((lons >= lo0) & (lons <= lo1))[0]
        z = z[r[0]:r[-1] + 1, c[0]:c[-1] + 1]
        lats, lons = lats[r[0]:r[-1] + 1], lons[c[0]:c[-1] + 1]

    n_lat, n_lon = z.shape
    with open(args.output, "wb") as f:
        f.write(struct.pack("<4sii4d", b"BDEM", n_lon, n_lat,
                            float(lons[0]), float(lons[-1]), float(lats[0]), float(lats[-1])))
        f.write(np.ascontiguousarray(z, dtype="<f4").tobytes())
    print(f"Wrote {args.output}  {n_lon}x{n_lat}  lon [{lons[0]:.5f},{lons[-1]:.5f}]  "
          f"lat [{lats[0]:.5f},{lats[-1]:.5f}]  h [{z.min():.0f},{z.max():.0f}] m", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
