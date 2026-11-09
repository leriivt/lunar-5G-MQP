"""Rasters for the Lunar Site Planner: GeoTIFF DEMs, shaded relief, overlays, shadow layer,
terrain profiles and line-of-sight coverage.

No Qt. Needs Pillow and numpy, plus constants from settings.py and the pure maths in geo_math.py.

Contents:
  - GeoTIFF reading    _geotags, Raster
  - Rendering helpers  _shade, resize_rgba, load_overlay, find_topo_overlay
  - Shadow layer       PsrLayer
  - Sampling           raster_lonlat_extent, elevation_profile
  - Visibility         los_coverage
"""
import math
import os
import re

import numpy as np
from PIL import Image

# package layout: use `from .geo_math import ...` and `from .settings import ...`
from geo_math import curvature_drop, distance_m, xy_to_lonlat
from settings import (COVERAGE_MAX_PX, DISPLAY_MAX_PX, OVERLAY_MAX_PX, PSR_INVERT, PSR_MAX_PX,
                      PSR_OPACITY, PSR_THRESHOLD, THEME, TOPO_POLE_FOLDERS, TOPO_REGION_FOLDERS)

Image.MAX_IMAGE_PIXELS = None       # the atlas rasters are far larger than Pillow's default limit


# ----------------------------------------------------------------------------
# GeoTIFF reading  (georeference from the TIFF tags)
# ----------------------------------------------------------------------------
def _geotags(img):
    """(x0, y0, dx, dy): top-left corner in projected metres and pixel size."""
    tags = img.tag_v2
    scale, tie = tags.get(33550), tags.get(33922)       # ModelPixelScale, ModelTiepoint
    if not scale or not tie:
        raise ValueError("the TIFF has no GeoTIFF georeference tags")
    x0, y0 = tie[3] - tie[0] * scale[0], tie[4] + tie[1] * scale[1]
    keys = tags.get(34735) or ()                         # GeoKeyDirectory
    for i in range(4, len(keys) - 3, 4):
        if keys[i] == 1025 and keys[i + 3] == 2:         # PixelIsPoint: shift half a pixel
            x0, y0 = x0 - scale[0] / 2, y0 + scale[1] / 2
    return x0, y0, abs(scale[0]), abs(scale[1])


def _shade(arr, mask, cell, azimuth=315.0, altitude=35.0):
    """Hillshade picture (8-bit greyscale) from an elevation array."""
    z = np.where(mask, arr[~mask].mean() if (~mask).any() else 0.0, arr)
    gy, gx = np.gradient(z, cell)
    dzdx, dzdy = -gx, gy                                  # rows run south, so flip y
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(dzdy, -dzdx)
    az, alt = np.radians((360.0 - azimuth + 90.0) % 360.0), np.radians(altitude)
    s = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    lo, hi = np.percentile(s[~mask], [1, 99]) if (~mask).any() else (0.0, 1.0)
    out = np.clip((s - lo) / (hi - lo + 1e-9), 0, 1) * 220 + 25
    out[mask] = 0
    return Image.fromarray(out.astype(np.uint8))


class Raster:
    """A georeferenced DEM: a display picture plus pixel <-> projected-metre conversion."""

    def __init__(self, path):
        with Image.open(path) as img:
            self.x0, self.y0, self.dx, self.dy = _geotags(img)
            nodata = img.tag_v2.get(42113)               # GDAL_NODATA (text)
            arr = np.array(img, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[..., 0]
        self.height, self.width = arr.shape
        mask = ~np.isfinite(arr) | (arr < -2e4)
        try:
            mask |= arr == float(str(nodata).strip("\x00"))
        except (TypeError, ValueError):
            pass
        self.elev = np.where(mask, np.nan, arr).astype(np.float32)   # metres; NaN = no data
        self.display = _shade(arr, mask, self.dx)
        self.display.thumbnail((DISPLAY_MAX_PX, DISPLAY_MAX_PX))

    def frac_to_xy(self, fx, fy):
        """(0..1, 0..1) position across the picture -> projected metres."""
        return self.x0 + fx * self.width * self.dx, self.y0 - fy * self.height * self.dy

    def xy_to_frac(self, x, y):
        return (x - self.x0) / (self.width * self.dx), (self.y0 - y) / (self.height * self.dy)


# ----------------------------------------------------------------------------
# Rendering helpers: overlays
# ----------------------------------------------------------------------------
def resize_rgba(img, size):
    """Resize an RGBA picture without dark fringes around transparent pixels."""
    return img.convert("RGBa").resize(size, Image.LANCZOS).convert("RGBA")


def load_overlay(path):
    """Load a transparent overlay PNG as RGBA, shrunk if very large."""
    img = Image.open(path).convert("RGBa")
    img.thumbnail((OVERLAY_MAX_PX, OVERLAY_MAX_PX), Image.LANCZOS)
    return img.convert("RGBA")


def find_topo_overlay(stem=None):
    """Path of the *_topo_hq.png overlay for a region (by file stem), or for the pole
    atlas when stem is None. Matches e.g. Haworth__topo_hq.png or Haworth__dem_topo_hq.png
    (a region name never matches a longer one, so Mons_Mouton != Mons_Mouton_Plateau)."""
    pattern = re.compile(rf"{re.escape(stem)}_*(dem_*)?topo_hq\.png", re.I) if stem else None
    for folder in (TOPO_REGION_FOLDERS if stem else TOPO_POLE_FOLDERS):
        if not os.path.isdir(folder):
            continue
        names = sorted(f for f in os.listdir(folder) if f.lower().endswith("topo_hq.png"))
        if stem:
            hits = [f for f in names if pattern.fullmatch(f)]
        else:
            hits = [f for f in names if re.search(r"pole|atlas|south", f, re.I)] or (names if len(names) == 1 else [])
        if hits:
            return os.path.join(folder, hits[0])
    return None


# ----------------------------------------------------------------------------
# Permanently shadowed regions
# ----------------------------------------------------------------------------
class PsrLayer:
    """Permanently shadowed regions from a GeoTIFF, as a tinted RGBA picture that keeps its own
    georeference, so it lines up with the map even if its extent differs a little."""

    def __init__(self, path):
        with Image.open(path) as img:
            x0, y0, dx, dy = _geotags(img)
            nodata = img.tag_v2.get(42113)
            arr = np.array(img, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[..., 0]
        h, w = arr.shape
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x0 + w * dx, y0 - h * dy
        valid = np.isfinite(arr)
        try:
            valid &= arr != float(str(nodata).strip("\x00"))
        except (TypeError, ValueError):
            pass
        top = arr[valid].max() if valid.any() else 0.0
        mask = (arr >= PSR_THRESHOLD) if top <= 1.0 else (arr > 0)     # 0..1 values or 0/255 style masks
        if PSR_INVERT:
            mask = ~mask
        mask &= valid
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[mask] = [int(THEME["psr"][i:i + 2], 16) for i in (1, 3, 5)] + [255]
        self.image = Image.fromarray(rgba, "RGBA")
        self.image.thumbnail((PSR_MAX_PX, PSR_MAX_PX), Image.LANCZOS)
        self.shadowed_fraction = float(mask.mean())

    def render(self, raster, size):
        """RGBA picture of `size` matching `raster`'s extent, with the shadow tint in place."""
        W, H = raster.width * raster.dx, raster.height * raster.dy
        fx0, fx1 = (self.x0 - raster.x0) / W, (self.x1 - raster.x0) / W
        fy0, fy1 = (raster.y0 - self.y0) / H, (raster.y0 - self.y1) / H
        w, h = max(1, round((fx1 - fx0) * size[0])), max(1, round((fy1 - fy0) * size[1]))
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        if w * h > 50_000_000:                                   # extent far larger than the map: skip
            return layer
        piece = resize_rgba(self.image, (w, h))
        piece.putalpha(piece.getchannel("A").point(lambda a: int(a * PSR_OPACITY)))
        layer.paste(piece, (round(fx0 * size[0]), round(fy0 * size[1])))
        return layer


# ----------------------------------------------------------------------------
# Sampling
# ----------------------------------------------------------------------------
def raster_lonlat_extent(raster, n=24):
    """(lon_min, lon_max, lat_min, lat_max, pole_inside) covered by a raster."""
    lons, lats = [], []
    for i in range(n + 1):
        for j in range(n + 1):
            lon, lat = xy_to_lonlat(*raster.frac_to_xy(i / n, j / n))
            lons.append(lon)
            lats.append(lat)
    fx, fy = raster.xy_to_frac(0.0, 0.0)
    if 0 <= fx <= 1 and 0 <= fy <= 1:                    # the pole is in the picture
        return -180.0, 180.0, -90.0, max(lats), True
    ref = lons[len(lons) // 2]                           # unwrap so tiles crossing +-180 work
    lons = [((l - ref + 180) % 360) - 180 + ref for l in lons]
    return min(lons), max(lons), min(lats), max(lats), False


def elevation_profile(raster, p0, p1, samples=None):
    """Ground distance (m) and DEM elevation (m, NaN where there is no data) along the straight
    line between two map positions given as (fx, fy) fractions of the picture."""
    if samples is None:                                   # about one sample per DEM pixel
        n = int(np.hypot((p1[0] - p0[0]) * raster.width, (p1[1] - p0[1]) * raster.height)) + 1
        samples = min(max(n, 60), 800)
    t = np.linspace(0.0, 1.0, samples)
    fx, fy = p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t
    lonlat = [xy_to_lonlat(*raster.frac_to_xy(a, b)) for a, b in zip(fx, fy)]
    dist = np.concatenate(([0.0], np.cumsum([distance_m(a, b) for a, b in zip(lonlat[:-1], lonlat[1:])])))
    cx = np.clip(fx * raster.width - 0.5, 0, raster.width - 1)     # pixel centres sit at i + 0.5
    cy = np.clip(fy * raster.height - 0.5, 0, raster.height - 1)
    x0 = np.minimum(np.floor(cx).astype(int), raster.width - 2)
    y0 = np.minimum(np.floor(cy).astype(int), raster.height - 2)
    tx, ty, e = cx - x0, cy - y0, raster.elev
    z = ((1 - tx) * (1 - ty) * e[y0, x0] + tx * (1 - ty) * e[y0, x0 + 1]
         + (1 - tx) * ty * e[y0 + 1, x0] + tx * ty * e[y0 + 1, x0 + 1])
    return dist, z


# ----------------------------------------------------------------------------
# Visibility
# ----------------------------------------------------------------------------
def los_coverage(raster, gnb, gnb_h, ue_h, max_px=COVERAGE_MAX_PX):
    """Where a UE standing ue_h above the ground would have line of sight to a gNB at map position
    `gnb` ((fx, fy) fractions) with its antenna gnb_h above the ground. Returns a bool array
    (True = LOS) on a grid of at most max_px cells per side covering the whole raster, or None if
    the DEM has no data at the gNB. Rays run from the gNB to every edge cell; along a ray a point is
    in view when the line to the UE clears every terrain sample before it (Moon curvature included)."""
    k = max(1, math.ceil(max(raster.width, raster.height) / max_px))
    W, H = max(2, math.ceil(raster.width / k)), max(2, math.ceil(raster.height / k))
    rows = np.minimum(((np.arange(H) + 0.5) * raster.height / H).astype(int), raster.height - 1)
    cols = np.minimum(((np.arange(W) + 0.5) * raster.width / W).astype(int), raster.width - 1)
    grid = raster.elev[np.ix_(rows, cols)]
    sx, sy = raster.width * raster.dx / W, raster.height * raster.dy / H        # cell size, metres
    z0 = float(elevation_profile(raster, gnb, gnb, samples=2)[1][0])
    if not np.isfinite(z0):
        return None
    top = z0 + gnb_h
    gx, gy = gnb[0] * W, gnb[1] * H                                           # gNB in grid cells
    xs, ys = np.arange(W) + 0.5, np.arange(H) + 0.5                           # edge cell centres
    tx = np.concatenate((xs, xs, np.full(H, 0.5), np.full(H, W - 0.5)))
    ty = np.concatenate((np.full(W, 0.5), np.full(W, H - 0.5), ys, ys))
    rx, ry = tx - gx, ty - gy
    t = np.linspace(0.0, 1.0, int(math.ceil(np.hypot(rx, ry).max())) + 2)     # under a cell per step
    px, py = gx + rx[:, None] * t, gy + ry[:, None] * t
    d = np.hypot(rx * sx, ry * sy)[:, None] * t                               # ground distance, metres
    cx, cy = np.clip(px - 0.5, 0, W - 1), np.clip(py - 0.5, 0, H - 1)         # bilinear terrain height
    x0, y0 = np.minimum(cx.astype(int), W - 2), np.minimum(cy.astype(int), H - 2)
    fx, fy = cx - x0, cy - y0
    z = ((1 - fx) * (1 - fy) * grid[y0, x0] + fx * (1 - fy) * grid[y0, x0 + 1]
         + (1 - fx) * fy * grid[y0 + 1, x0] + fx * fy * grid[y0 + 1, x0 + 1])
    with np.errstate(divide="ignore", invalid="ignore"):
        drop = curvature_drop(d)                                              # curvature of the Moon
        terrain = (z - drop - top) / d                                        # slope up to each ground point
        target = (z + ue_h - drop - top) / d                                  # slope up to a UE antenna there
    terrain[:, 0] = -np.inf
    terrain[~np.isfinite(terrain)] = -np.inf                                 # no-data samples never block
    horizon = np.maximum.accumulate(terrain, axis=1)
    horizon = np.concatenate((np.full((len(rx), 1), -np.inf), horizon[:, :-1]), axis=1)
    valid = np.isfinite(z)
    seen = target >= horizon
    seen[:, 0] = True
    cell = (np.clip(py.astype(int), 0, H - 1) * W + np.clip(px.astype(int), 0, W - 1))[valid]
    total = np.bincount(cell, minlength=W * H)
    clear = np.bincount(cell, weights=seen[valid], minlength=W * H)
    return ((clear * 2 >= total) & (total > 0)).reshape(H, W)                # most rays through the cell agree