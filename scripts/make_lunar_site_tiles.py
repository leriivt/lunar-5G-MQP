#!/usr/bin/env python3
"""
Cut one BICTR .bdem tile per Artemis candidate site out of the LOLA south-polar
stereographic DEM (LDEM_80S_20M_FLOAT.IMG, 20 m/px, 80S-90S).

bictr_channel.c expects a regular lon/lat grid (row 0 = min_lat, col 0 = min_lon,
heights in metres relative to the 1737.4 km sphere), so each tile is resampled
(bilinear) from polar stereographic onto a local lon/lat grid around the site.

Usage (from the BICTR_Data folder):
  PYTHONPATH=scripts/.pylib python3 scripts/make_lunar_site_tiles.py \
      [--half-size-km 10] [--step-m 20] [--only 03,18]
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import struct
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LUNAR = os.path.join(ROOT, "Lunar_DEM")
SRC_IMG = os.path.join(LUNAR, "source", "LDEM_80S_20M_FLOAT.IMG")
SRC_LBL = os.path.join(LUNAR, "source", "LDEM_80S_20M_FLOAT.LBL")
SITES_CSV = os.path.join(LUNAR, "artemis_candidate_sites.csv")
OUT_DIR = os.path.join(LUNAR, "sites")

MOON_R = 1737400.0
LINK_DIST_M = 500.0


def lbl_value(text: str, key: str) -> float:
    m = re.search(rf"^\s*{key}\s*=\s*([-0-9.]+)", text, re.M)
    if not m:
        raise KeyError(key)
    return float(m.group(1))


def load_source():
    with open(SRC_LBL, encoding="ascii", errors="replace") as f:
        lbl = f.read()
    n = int(lbl_value(lbl, "LINES"))
    if int(lbl_value(lbl, "LINE_SAMPLES")) != n:
        raise ValueError("expected a square polar grid")
    scale = lbl_value(lbl, "MAP_SCALE")
    l0 = lbl_value(lbl, "LINE_PROJECTION_OFFSET")
    s0 = lbl_value(lbl, "SAMPLE_PROJECTION_OFFSET")
    radius = lbl_value(lbl, "A_AXIS_RADIUS") * 1000.0
    if os.path.getsize(SRC_IMG) != n * n * 4:
        raise ValueError(f"{SRC_IMG} size does not match label ({n}x{n} float32)")
    z = np.memmap(SRC_IMG, dtype="<f4", mode="r", shape=(n, n))
    return z, scale, l0, s0, radius


def latlon_to_pix(lat, lon, scale, l0, s0, radius):
    """South polar stereographic (spherical, true scale at pole) -> 0-based line/sample."""
    rho = 2.0 * radius * np.tan(np.pi / 4.0 + np.radians(lat) / 2.0)
    x = rho * np.sin(np.radians(lon))
    y = rho * np.cos(np.radians(lon))
    return l0 - y / scale, s0 + x / scale


def bilinear(z, line, samp):
    n = z.shape[0]
    l_lo = max(int(np.floor(line.min())) - 1, 0)
    l_hi = min(int(np.ceil(line.max())) + 2, n)
    s_lo = max(int(np.floor(samp.min())) - 1, 0)
    s_hi = min(int(np.ceil(samp.max())) + 2, n)
    win = np.asarray(z[l_lo:l_hi, s_lo:s_hi], dtype=np.float64)
    li = line - l_lo
    si = samp - s_lo
    i0 = np.clip(np.floor(li).astype(int), 0, win.shape[0] - 2)
    j0 = np.clip(np.floor(si).astype(int), 0, win.shape[1] - 2)
    fy = li - i0
    fx = si - j0
    return (win[i0, j0] * (1 - fx) * (1 - fy) + win[i0, j0 + 1] * fx * (1 - fy)
            + win[i0 + 1, j0] * (1 - fx) * fy + win[i0 + 1, j0 + 1] * fx * fy)


def geo_destination(lat_deg, lon_deg, bearing_deg, dist_m, radius=MOON_R):
    """Same great-circle step as geo_destination() in bictr_channel.c."""
    d = dist_m / radius
    b = math.radians(bearing_deg)
    la1, lo1 = math.radians(lat_deg), math.radians(lon_deg)
    la2 = math.asin(math.sin(la1) * math.cos(d) + math.cos(la1) * math.sin(d) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(la1),
                           math.cos(d) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def write_bdem(path, h, min_lon, max_lon, min_lat, max_lat):
    n_lat, n_lon = h.shape
    with open(path, "wb") as f:
        f.write(struct.pack("<4sii4d", b"BDEM", n_lon, n_lat, min_lon, max_lon, min_lat, max_lat))
        f.write(np.ascontiguousarray(h, dtype="<f4").tobytes())


def write_hillshade_png(path, h, dx_m, dy_m):
    """Grayscale hillshade, north (max_lat) at the top."""
    gy, gx = np.gradient(h, dy_m, dx_m)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315.0), np.radians(30.0)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    img = np.clip(shade * 255.0, 0, 255).astype(np.uint8)[::-1]
    rows = b"".join(b"\x00" + r.tobytes() for r in img)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", img.shape[1], img.shape[0], 8, 0, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(rows, 6)))
        f.write(chunk(b"IEND", b""))


def slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--half-size-km", type=float, default=10.0,
                    help="half width of each tile around the site centre (default 10 -> 20x20 km)")
    ap.add_argument("--step-m", type=float, default=20.0, help="target grid spacing (default 20 m = source)")
    ap.add_argument("--only", default="", help="comma-separated site ids to process")
    args = ap.parse_args()

    z, scale, l0, s0, radius = load_source()
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    m_per_deg = radius * math.pi / 180.0
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(SITES_CSV, newline="") as f:
        sites = list(csv.DictReader(f))

    index_rows = []
    for s in sites:
        if only and s["id"] not in only:
            continue
        lat_c, lon_c = float(s["lat_deg"]), float(s["lon_deg"])
        half = args.half_size_km * 1000.0

        dlat_half = half / m_per_deg
        min_lat, max_lat = lat_c - dlat_half, lat_c + dlat_half
        if min_lat <= -90.0:
            raise ValueError(f"site {s['id']}: tile would include the pole; reduce --half-size-km")
        dlon_half = half / (m_per_deg * math.cos(math.radians(lat_c)))
        min_lon, max_lon = lon_c - dlon_half, lon_c + dlon_half
        if min_lon < -180.0 or max_lon > 180.0:
            raise ValueError(f"site {s['id']}: tile crosses the +/-180 seam")

        # lon spacing sized at the equatorward edge so no pixel is wider than step_m
        n_lat = int(math.ceil(2 * half / args.step_m)) + 1
        n_lon = int(math.ceil(2 * dlon_half * m_per_deg * math.cos(math.radians(max_lat)) / args.step_m)) + 1
        lats = np.linspace(min_lat, max_lat, n_lat)
        lons = np.linspace(min_lon, max_lon, n_lon)
        LON, LAT = np.meshgrid(lons, lats)
        line, samp = latlon_to_pix(LAT, LON, scale, l0, s0, radius)
        h = (bilinear(z, line, samp) * 1000.0).astype(np.float32)

        base = f"{s['id']}_{slug(s['name'])}"
        bdem = os.path.join(OUT_DIR, base + ".bdem")
        write_bdem(bdem, h, min_lon, max_lon, min_lat, max_lat)
        dy = 2 * half / (n_lat - 1)
        dx = (max_lon - min_lon) / (n_lon - 1) * m_per_deg * math.cos(math.radians(lat_c))
        write_hillshade_png(os.path.join(OUT_DIR, base + "_hillshade.png"), h.astype(np.float64), dx, dy)

        ue_lat, ue_lon = geo_destination(lat_c, lon_c, 0.0, LINK_DIST_M, radius)
        gc = h[n_lat // 2, n_lon // 2]
        index_rows.append({
            "id": s["id"], "name": s["name"], "list": s["list"],
            "bdem_file": os.path.relpath(bdem, LUNAR),
            "center_lat": f"{lat_c:.6f}", "center_lon": f"{lon_c:.6f}",
            "min_lat": f"{min_lat:.6f}", "max_lat": f"{max_lat:.6f}",
            "min_lon": f"{min_lon:.6f}", "max_lon": f"{max_lon:.6f}",
            "n_lon": n_lon, "n_lat": n_lat,
            "h_min_m": f"{float(h.min()):.1f}", "h_max_m": f"{float(h.max()):.1f}",
            "h_center_m": f"{float(gc):.1f}",
            "gnb_lat": f"{lat_c:.6f}", "gnb_lon": f"{lon_c:.6f}",
            "ue_lat": f"{ue_lat:.6f}", "ue_lon": f"{ue_lon:.6f}",
        })
        print(f"{base}: {n_lon}x{n_lat}  lat [{min_lat:.4f},{max_lat:.4f}]  lon [{min_lon:.3f},{max_lon:.3f}]"
              f"  h [{h.min():.0f},{h.max():.0f}] m  centre {gc:.0f} m", file=sys.stderr)

    if not only:
        with open(os.path.join(LUNAR, "site_tiles_index.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(index_rows[0].keys()))
            w.writeheader()
            w.writerows(index_rows)
        write_snippets(os.path.join(LUNAR, "bictr_site_snippets.conf"), index_rows)
    return 0


def write_snippets(path, rows):
    """Per-site BICTR keys for the gNB/UE channelmod entries (gNB at site centre, UE 500 m north)."""
    with open(path, "w") as f:
        f.write("# BICTR terrain keys per Artemis candidate site.\n"
                "# Paste into BOTH model entries of BOTH configs (gnb...bictr.conf and ue.bictr.conf).\n"
                "# rfsimu_channel_enB0: TX = gNB, RX = UE.  rfsimu_channel_ue0: TX = UE, RX = gNB.\n"
                f"# gNB sits at the region centre, UE {LINK_DIST_M:.0f} m due north (great circle).\n\n")
        for r in rows:
            dem = os.path.join(LUNAR, r["bdem_file"])
            f.write(f"# ---- {r['id']} {r['name']}  (ground at centre {r['h_center_m']} m) ----\n"
                    f"# rfsimu_channel_enB0:\n"
                    f"bictr_dem_file = \"{dem}\";\n"
                    f"bictr_tx_lon = {r['gnb_lon']};  bictr_tx_lat = {r['gnb_lat']};\n"
                    f"bictr_rx_lon = {r['ue_lon']};  bictr_rx_lat = {r['ue_lat']};\n"
                    f"# rfsimu_channel_ue0:\n"
                    f"bictr_dem_file = \"{dem}\";\n"
                    f"bictr_tx_lon = {r['ue_lon']};  bictr_tx_lat = {r['ue_lat']};\n"
                    f"bictr_rx_lon = {r['gnb_lon']};  bictr_rx_lat = {r['gnb_lat']};\n\n")


if __name__ == "__main__":
    raise SystemExit(main())
