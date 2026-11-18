"""Convert the atlas region DEMs (GeoTIFF, south polar stereographic) into bictr .bdem files.

bictr (OAI's BICTR_LUNAR channel) only reads its own BDEM format: a regular longitude/latitude
grid of float heights, so the polar-stereographic TIFFs have to be resampled onto one.

    python3 make_region_bdems.py              # every <Region>__dem.tif in the region folder
    python3 make_region_bdems.py Haworth      # just these regions
    python3 make_region_bdems.py --force      # rebuild files that already exist

Each <Region>__dem.tif gets a <Region>__dem.bdem next to it. catalog.find_bdem() looks there.

BDEM layout (little-endian, read by bictr_dem_load in bictr_channel.c):
    b"BDEM"                                   4 bytes
    int32 n_lon, int32 n_lat                  grid size
    float64 min_lon, max_lon, min_lat, max_lat
    float32 heights[n_lat][n_lon]             row 0 = min_lat, column 0 = min_lon, metres
Grid points sit exactly on the bounds: pixel size = (max - min) / (n - 1).

The grid keeps the TIFF's ~20 m spacing: 1 deg of latitude is ~30 km everywhere, but 1 deg of
longitude shrinks towards the pole, so the longitude step is chosen at the region's middle
latitude (cells are a little finer on the poleward side, a little coarser on the other).
Grid points outside the TIFF (the corners of a lon/lat box drawn around a stereographic tile)
take the nearest edge height, so bictr never sees NaN.
"""
import glob
import math
import os
import struct
import sys

import numpy as np
from PIL import Image

from raster import Raster, _geotags, raster_lonlat_extent
from settings import BODY_RADIUS_M, REGION_DIR

TARGET_SPACING_M = 20.0          # same as the atlas region DEMs
ROWS_PER_CHUNK = 256             # resample this many latitude rows at a time (keeps RAM low)


def bdem_path_for(tif_path):
    """<Region>__dem.tif -> <Region>__dem.bdem in the same folder."""
    return os.path.splitext(tif_path)[0] + ".bdem"


def load_tif(path):
    """(heights float32 [rows, cols] with NaN for no-data, x0, y0, dx, dy) of a GeoTIFF DEM."""
    with Image.open(path) as img:
        x0, y0, dx, dy = _geotags(img)
        nodata = img.tag_v2.get(42113)
        arr = np.array(img, dtype=np.float32)
    if arr.ndim == 3:
        arr = arr[..., 0]
    bad = ~np.isfinite(arr) | (arr < -2e4)
    try:
        bad |= arr == float(str(nodata).strip("\x00"))
    except (TypeError, ValueError):
        pass
    return np.where(bad, np.nan, arr), x0, y0, dx, dy


def fill_nan_nearest(z):
    """Replace NaNs with the nearest valid height (none in the current atlas, but be safe)."""
    bad = np.isnan(z)
    if not bad.any():
        return z
    from scipy.ndimage import distance_transform_edt
    idx = distance_transform_edt(bad, return_distances=False, return_indices=True)
    return z[tuple(idx)]


def lonlat_to_xy(lon_deg, lat_deg):
    """Vectorised geo_math.lonlat_to_xy (south polar stereographic, sphere BODY_RADIUS_M)."""
    rho = 2 * BODY_RADIUS_M * np.tan(np.radians(lat_deg + 90.0) / 2)
    lon = np.radians(lon_deg)
    return rho * np.sin(lon), rho * np.cos(lon)


def sample_bilinear(z, x0, y0, dx, dy, x, y):
    """Heights at projected (x, y), bilinear between pixel centres, clamped to the TIFF edges."""
    rows, cols = z.shape
    fc = np.clip((x - x0) / dx - 0.5, 0, cols - 1)        # pixel centres sit at x0 + (i + 0.5) dx
    fr = np.clip((y0 - y) / dy - 0.5, 0, rows - 1)        # rows run south (y decreasing)
    c0 = np.minimum(np.floor(fc).astype(np.int64), cols - 2)
    r0 = np.minimum(np.floor(fr).astype(np.int64), rows - 2)
    tc, tr = fc - c0, fr - r0
    z00, z01 = z[r0, c0], z[r0, c0 + 1]
    z10, z11 = z[r0 + 1, c0], z[r0 + 1, c0 + 1]
    return ((z00 * (1 - tc) + z01 * tc) * (1 - tr) + (z10 * (1 - tc) + z11 * tc) * tr).astype(np.float32)


def grid_for(tif_path):
    """(min_lon, max_lon, min_lat, max_lat, n_lon, n_lat, pole_inside) for a region TIFF."""
    lon0, lon1, lat0, lat1, pole = raster_lonlat_extent(Raster(tif_path), n=64)
    m_per_deg_lat = BODY_RADIUS_M * math.pi / 180
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians((lat0 + lat1) / 2))
    n_lat = int(math.ceil((lat1 - lat0) * m_per_deg_lat / TARGET_SPACING_M)) + 1
    n_lon = int(math.ceil((lon1 - lon0) * m_per_deg_lon / TARGET_SPACING_M)) + 1
    return lon0, lon1, lat0, lat1, n_lon, n_lat, pole


def write_bdem(out_path, z_rows, lon0, lon1, lat0, lat1, n_lon, n_lat):
    """Write the header, then the height rows (an iterable of float32 arrays, south to north)."""
    tmp = out_path + ".part"
    with open(tmp, "wb") as f:
        f.write(b"BDEM")
        f.write(struct.pack("<ii", n_lon, n_lat))
        f.write(struct.pack("<4d", lon0, lon1, lat0, lat1))
        written = 0
        for block in z_rows:
            f.write(np.ascontiguousarray(block, dtype="<f4").tobytes())
            written += block.shape[0]
    if written != n_lat:
        os.remove(tmp)
        raise RuntimeError(f"wrote {written} rows, expected {n_lat}")
    os.replace(tmp, out_path)      # only a complete file ever has the final name


def convert(tif_path, force=False):
    out = bdem_path_for(tif_path)
    if os.path.exists(out) and not force:
        print(f"  skip (exists): {os.path.basename(out)}")
        return out
    z, x0, y0, dx, dy = load_tif(tif_path)
    z = fill_nan_nearest(z)
    lon0, lon1, lat0, lat1, n_lon, n_lat, pole = grid_for(tif_path)
    lons = np.linspace(lon0, lon1, n_lon)
    lats = np.linspace(lat0, lat1, n_lat)

    def rows():
        for start in range(0, n_lat, ROWS_PER_CHUNK):
            lat_block = lats[start:start + ROWS_PER_CHUNK]
            lon_g, lat_g = np.meshgrid(lons, lat_block)
            yield sample_bilinear(z, x0, y0, dx, dy, *lonlat_to_xy(lon_g, lat_g))

    write_bdem(out, rows(), lon0, lon1, lat0, lat1, n_lon, n_lat)
    size_mb = os.path.getsize(out) / 1e6
    note = "  (contains the pole: lon/lat grid, see note below)" if pole else ""
    print(f"  {os.path.basename(out)}: {n_lon} x {n_lat}, lon [{lon0:.3f}, {lon1:.3f}] "
          f"lat [{lat0:.3f}, {lat1:.3f}], {size_mb:.0f} MB{note}")
    return out


def main(argv):
    force = "--force" in argv
    names = [a for a in argv if not a.startswith("--")]
    tifs = sorted(glob.glob(os.path.join(REGION_DIR, "*__dem.tif")))
    if names:
        tifs = [t for t in tifs if os.path.basename(t)[:-len("__dem.tif")] in names]
    if not tifs:
        sys.exit(f"no matching *__dem.tif in {REGION_DIR}")
    for tif in tifs:
        print(os.path.basename(tif))
        convert(tif, force=force)


if __name__ == "__main__":
    main(sys.argv[1:])
