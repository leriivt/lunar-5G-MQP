"""Lunar Site Planner v2: south-pole atlas -> click a region -> place gNB and UE -> export BICTR configs.

Run:  python lunar_site_planner.py        (needs: pip install pillow numpy)

Sections (read top to bottom):
  1. Settings        - paths, defaults and the colour THEME
  2. Map projection  - polar stereographic x/y <-> longitude/latitude
  3. Rasters         - reads a GeoTIFF DEM and renders a shaded-relief picture
  4. Catalog         - sites.csv -> clickable regions; .bdem lookup; candidate masts;
                       per-region default gNB locations (gnb_defaults.csv)
  5. Config export   - fills the four BICTR model entries, dated export folders
  6. GUI             - the tkinter window (atlas screen + region screen)
"""
import csv
import math
import os
import re
import sys
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import numpy as np
from PIL import Image, ImageTk

Image.MAX_IMAGE_PIXELS = None

# ----------------------------------------------------------------------------
# 1. SETTINGS
# ----------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)                                      # repo root (one level up from files/)
ATLAS_DIR = os.path.join(APP_DIR, "atlas_v2", "bundle", "context")      # from the Zenodo archive
BUNDLE_DIR = os.path.join(APP_DIR, "atlas_v2", "bundle")
POLE_DEM = os.path.join(ATLAS_DIR, "pole_dem_160m.tif")
REGION_DIR = os.path.join(ATLAS_DIR, "regions")                          # <Region>__dem.tif
CANDIDATES_CSV = os.path.join(APP_DIR, "data", "atlas_base", "candidates_freeze.csv")
SITES_CSV = os.path.join(APP_DIR, "sites.csv")                           # id,name,lat_deg,lon_deg
TERRAIN_DIR = os.path.join(APP_DIR, "terrain")                           # your .bdem files
POLE_BDEM = "lunar_south_pole.bdem"      # used when there is no region-specific .bdem
EXPORT_DIR = os.path.join(APP_DIR, "exports")
# Topographic overlays: transparent *_topo_hq.png files, searched in these folders in order
TOPO_POLE_FOLDERS = [ATLAS_DIR, BUNDLE_DIR]
TOPO_REGION_FOLDERS = [REGION_DIR, os.path.join(BUNDLE_DIR, "regions"), ATLAS_DIR]
TOPO_OPACITY = 0.8                       # starting opacity of the overlay (0 to 1)
OVERLAY_MAX_PX = 3000                    # overlays are shrunk to at most this many pixels per side
# Permanently shadowed regions (PSR): <Region>__psr.tif in REGION_DIR, and POLE_PSR for the atlas
POLE_PSR = os.path.join(ATLAS_DIR, "pole_psr_160m.tif")
PSR_OPACITY = 0.5                        # how solid the shadow tint is (0 to 1)
PSR_THRESHOLD = 0.5                      # for files holding 0..1 values: at or above this = shadowed
PSR_INVERT = False                       # True if the files mark shadowed areas as 0 instead of 1
PSR_MAX_PX = 3000                        # PSR pictures are shrunk to at most this many pixels per side
GNB_DEFAULTS_CSV = os.path.join(APP_DIR, "gnb_defaults.csv")             # region,lon,lat,height_m
MINI_PX = 210                            # size of the atlas minimap in the side panel

# optimal_gNB.py lives at the repo root, alongside its coverage/index CSVs
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
OPTIMAL_GNB_CANDIDATES_CSV = os.path.join(ROOT_DIR, "candidates_coverage.csv")
OPTIMAL_GNB_INDEX_CSV = os.path.join(ROOT_DIR, "site_tiles_index.csv")
OPTIMAL_GNB_FREQ_GHZ = 2.580

BODY_RADIUS_M = 1_737_400.0              # Moon sphere used by the atlas and bictr_body_radius
GNB_HEIGHT_M = 4.0                       # atlas radio_params.json: mast_height_m
UE_HEIGHT_M = 1.5                        # atlas radio_params.json: rx_height_m
DISPLAY_MAX_PX = 1800                    # maps are shown at most this many pixels wide/high
SHOW_SITES_WITHOUT_TILE = False           # True: also draw sites with no region tile as grey, unclickable markers
REGION_ALIASES = {"Leibnitz_Beta_Plateau": "Mons_Mouton"}   # same massif (see Bictr notes)

GNB_CONF = "gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf"
UE_CONF = "ue.bictr.conf"
BLOCK_GNB_SIDE = "rfsimu_channel_enB0"   # TX = gNB, RX = UE
BLOCK_UE_SIDE = "rfsimu_channel_ue0"     # TX = UE,  RX = gNB (swapped)

# ---- LOOK AND FEEL: change colours and font size here (all UI colours live in this block) ----
THEME = {
    "font_size": 8,
    # side panel (light background, near-black text)
    "panel_bg": "#f4f4f4", "text": "#111111", "muted": "#263238", "disabled": "#757575",
    "border": "#7fbddc", "entry_bg": "#ffffff",
    "button_bg": "#dfe6ec", "button_active": "#bfd2e3",
    # map area
    "canvas_bg": "#000000",
    "label_bg": "#351C41",           # dark plate drawn behind every map label
    "label_fg": "#ffffff",           # label text
    "label_focus_fg": "#cf8f06",     # name of the region you are in / last opened
    "missing_fg": "#cfd8dc",         # sites with no terrain tile
    "marker": "#ffb300", "marker_outline": "#1e0348",   # region markers on the atlas
    "footprint": "#00e5ff",          # box showing the open region's extent on the atlas
    "gnb": "#c62828", "ue": "#1565c0",                  # gNB / UE markers and panel headings
    "cand_ridge": "#F9A034", "cand_landing": "#0BF862",  # candidate mast overlay
    "grid": "#000000", "grid_label": "#b2ebf2", #81eb88
    "psr": "#29b6f6",                # tint for permanently shadowed regions
    "link": "#ffeb3b",               # line between the gNB and the UE (map and cross section)
    "terrain_fill": "#808080", "terrain_line": "#d7ccc8",   # cross-section terrain
}


# ----------------------------------------------------------------------------
# 2. MAP PROJECTION  (south polar stereographic, sphere R, true scale at the pole)
# ----------------------------------------------------------------------------
def xy_to_lonlat(x, y):
    """Projected metres -> (lon, lat) degrees, east-positive longitude."""
    rho = math.hypot(x, y)
    return math.degrees(math.atan2(x, y)), -90.0 + math.degrees(2 * math.atan(rho / (2 * BODY_RADIUS_M)))


def lonlat_to_xy(lon, lat):
    rho = 2 * BODY_RADIUS_M * math.tan(math.radians(lat + 90.0) / 2)
    return rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))


def distance_m(a, b):
    """Great-circle distance between two (lon, lat) points, metres."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * BODY_RADIUS_M * math.asin(math.sqrt(h))

#helper functions for drawing map projected grid lines
GRID_STEPS = (0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
              1, 2, 5, 10, 15, 30, 45)


def grid_step(span, target=6):
    """Smallest 'nice' step that gives at most `target` lines across `span` degrees."""
    for s in GRID_STEPS:
        if span / s <= target:
            return s
    return GRID_STEPS[-1]


def frange(a, b, step):
    """Multiples of `step` between a and b (inclusive)."""
    k = math.ceil(a / step - 1e-9)
    while k * step <= b + 1e-9:
        yield round(k * step, 9)
        k += 1


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

# ----------------------------------------------------------------------------
# 3. RASTERS  (GeoTIFF read with Pillow; georeference from the TIFF tags)
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


def scale_bar(m_per_px, target_px=110):
    """(bar length in pixels, label) for a scale bar roughly target_px wide (1, 2 or 5 x 10^n)."""
    raw = m_per_px * target_px
    base = 10 ** math.floor(math.log10(raw))
    length = max(k for k in (1, 2, 5, 10) if k * base <= raw) * base
    return length / m_per_px, (f"{length:g} m" if length < 1000 else f"{length / 1000:g} km")


# ----------------------------------------------------------------------------
# 4. CATALOG  (sites.csv -> regions; .bdem lookup; candidate masts)
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
@dataclass
class Region:
    stem: str                                   # file stem, e.g. "Haworth"
    sites: list = field(default_factory=list)  # [(id, name, lon, lat), ...]

    @property
    def label(self):
        return self.stem.replace("_", " ")

    @property
    def lonlat(self):
        return self.sites[0][2], self.sites[0][3]

    @property
    def dem_path(self):
        return os.path.join(REGION_DIR, f"{self.stem}__dem.tif")

    @property
    def available(self):
        return os.path.exists(self.dem_path)


def region_stem(name):
    """'Haworth (2024)' -> 'Haworth';  'de Gerlache Rim 2' -> 'de_Gerlache_Rim_2'."""
    stem = re.sub(r"[^A-Za-z0-9]+", "_", re.sub(r"\s*\(.*?\)", "", name)).strip("_")
    return REGION_ALIASES.get(stem, stem)


def load_catalog(path=SITES_CSV):
    """Returns (regions with a terrain tile, sites without one)."""
    regions, missing = {}, []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lat = row.get("lat_deg") or row.get("lat")
            lon = row.get("lon_deg") or row.get("lon")
            site = (row["id"].strip(), row["name"].strip(), float(lon), float(lat))
            reg = regions.setdefault(region_stem(site[1]), Region(region_stem(site[1])))
            reg.sites.append(site)
    for stem in list(regions):
        if not regions[stem].available:
            missing += regions.pop(stem).sites
    return regions, missing


def find_bdem(stem):
    """Region-specific .bdem in terrain/ if present, else the pole-wide file, else the
    expected region path (reported as missing by the app)."""
    if os.path.isdir(TERRAIN_DIR):
        for fname in sorted(os.listdir(TERRAIN_DIR)):
            if fname.lower().endswith(".bdem") and stem.lower() in fname.lower():
                return os.path.abspath(os.path.join(TERRAIN_DIR, fname))
        pole = os.path.join(TERRAIN_DIR, POLE_BDEM)
        if os.path.exists(pole):
            return os.path.abspath(pole)
    return os.path.abspath(os.path.join(TERRAIN_DIR, f"{stem}.bdem"))


def load_candidates(path=CANDIDATES_CSV):
    """Atlas candidate mast positions: [(x_m, y_m, class)]. Empty if the file is absent."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [(float(r["x_m"]), float(r["y_m"]), r["cls"]) for r in csv.DictReader(f)]


def load_gnb_defaults(path=GNB_DEFAULTS_CSV):
    """{region stem: (lon, lat, height_m or None)}. Empty if the file is absent."""
    out = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    h = float(r["height_m"]) if (r.get("height_m") or "").strip() else None
                    out[r["region"].strip()] = (float(r["lon"]), float(r["lat"]), h)
                except (KeyError, ValueError):
                    continue                      # skip malformed rows
    return out


def save_gnb_defaults(defaults, path=GNB_DEFAULTS_CSV):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", "lon", "lat", "height_m"])
        for stem in sorted(defaults):
            lon, lat, h = defaults[stem]
            w.writerow([stem, f"{lon:.6f}", f"{lat:.6f}", "" if h is None else f"{h:g}"])


# ----------------------------------------------------------------------------
# 5. CONFIG EXPORT
# ----------------------------------------------------------------------------
def block_values(tx, rx, tx_h, rx_h, dem_path):
    """Ordered BICTR parameter values (as config strings) for one model entry."""
    return {
        "bictr_tx_lon": f"{tx[0]:.6f}", "bictr_tx_lat": f"{tx[1]:.6f}",
        "bictr_tx_height": f"{tx_h:.2f}",
        "bictr_rx_lon": f"{rx[0]:.6f}", "bictr_rx_lat": f"{rx[1]:.6f}",
        "bictr_rx_height": f"{rx_h:.2f}",
        "bictr_body_radius": f"{BODY_RADIUS_M:.0f}",
        "bictr_dem_file": f'"{dem_path}"',
    }


def snippet(block, values):
    lines = "\n".join(f"  {k} = {v};" for k, v in values.items())
    return f"{block} = {{\n{lines}\n}};\n"


def fill_block(text, block, values):
    """Overwrite `key = value;` lines inside `block` of a template; None if it doesn't fit."""
    start = text.find(block)
    if start < 0:
        return None
    nxt = text.find("rfsimu_channel_", start + len(block))
    end = nxt if nxt >= 0 else len(text)
    segment = text[start:end]
    for key, val in values.items():
        segment, n = re.subn(rf"({key}\s*=\s*)[^;\n]*", lambda m: m.group(1) + val, segment)
        if n == 0:
            return None
    return text[:start] + segment + text[end:]


def build_config(template_text, entries):
    """entries: {block_name: values}. Uses the template if it fits, else appends snippets."""
    text = template_text or ""
    for block, values in entries.items():
        filled = fill_block(text, block, values)
        text = filled if filled is not None else text + "\n" + snippet(block, values)
    return text


def run_folder_name(label, now=None):
    now = now or datetime.now()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")
    return f"{slug}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"


def make_run_folder(parent, label):
    """Create a new, uniquely named, date/time-stamped folder inside `parent`."""
    base = os.path.join(parent, run_folder_name(label))
    path, n = base, 1
    while os.path.exists(path):
        n += 1
        path = f"{base}_{n}"
    os.makedirs(path)
    return path


def export_configs(out_dir, template_dir, gnb, ue, gnb_h, ue_h, dem_path):
    """Write the gNB and UE conf files. Both contain both entries, TX/RX swapped."""
    entries = {
        BLOCK_GNB_SIDE: block_values(gnb, ue, gnb_h, ue_h, dem_path),
        BLOCK_UE_SIDE: block_values(ue, gnb, ue_h, gnb_h, dem_path),
    }
    written = []
    for name in (GNB_CONF, UE_CONF):
        template = ""
        if template_dir and os.path.exists(os.path.join(template_dir, name)):
            with open(os.path.join(template_dir, name), encoding="utf-8") as f:
                template = f.read()
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_config(template, entries))
        written.append(path)
    return written


# ----------------------------------------------------------------------------
# 6. GUI
# ----------------------------------------------------------------------------
ATLAS_LABEL = "South pole atlas"
NODES = ("gNB", "UE")


def apply_theme(root):
    """Applies THEME (section 1) to the window and all ttk widgets. Returns (font family, size)."""
    t = THEME
    style = ttk.Style(root)
    style.theme_use("clam")                       # 'clam' honours colours on Windows, macOS and Linux
    base = tkfont.nametofont("TkDefaultFont")
    base.configure(size=t["font_size"])
    family = base.actual("family")
    root.configure(bg=t["panel_bg"])
    root.option_add("*TCombobox*Listbox.background", t["entry_bg"])
    root.option_add("*TCombobox*Listbox.foreground", t["text"])
    style.configure(".", background=t["panel_bg"], foreground=t["text"], font=base)
    style.configure("TLabel", background=t["panel_bg"], foreground=t["text"])
    style.configure("Muted.TLabel", foreground=t["muted"])
    style.configure("TLabelframe", background=t["panel_bg"], bordercolor=t["border"])
    style.configure("TLabelframe.Label", background=t["panel_bg"], foreground=t["text"],
                    font=(family, t["font_size"], "bold"))
    style.configure("gNB.TLabelframe.Label", foreground=t["gnb"])
    style.configure("UE.TLabelframe.Label", foreground=t["ue"])
    style.configure("TButton", background=t["button_bg"], foreground=t["text"], padding=4,
                    bordercolor=t["border"])
    style.map("TButton", background=[("active", t["button_active"])])
    style.configure("TEntry", fieldbackground=t["entry_bg"], foreground=t["text"], bordercolor=t["border"])
    style.configure("TCombobox", fieldbackground=t["entry_bg"], foreground=t["text"],
                    background=t["button_bg"], arrowcolor=t["text"])
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(widget, background=t["panel_bg"], foreground=t["text"])
        style.map(widget, background=[("active", t["panel_bg"])],
                  foreground=[("disabled", t["disabled"])])
    return family, t["font_size"]


class PlannerApp(tk.Tk):
    def __init__(self, regions, missing, candidates):
        super().__init__()
        self.title("Lunar Site Planner")
        self.geometry("1260x880")
        self.font_family, self.font_size = apply_theme(self)
        self.regions, self.missing, self.candidates = regions, missing, candidates
        self.rasters = {}               # cache: path -> Raster
        self.mode = "atlas"             # "atlas" or "region"
        self.view_mode = "atlas"        # "atlas" or "cross"
        self.region = None
        self.raster = None
        self.pole = None                # the atlas raster (kept while a region is open)
        self.focus = None               # region highlighted on the atlas (last one opened)
        self.photo = None
        self.mini_photo = None
        self.gnb_defaults = load_gnb_defaults()
        self._topo_cache = {}           # view key (region stem or None) -> (overlay image or None, path)
        self._psr_cache = {}            # view key -> PsrLayer or None
        self._bg_key = self._bg_img = None   # cached map background (map + overlay)
        self.points = {"gNB": None, "UE": None}      # (fx, fy) fractions of the region picture
        self.template_dir = ""
        self._view = (1.0, 0, 0, 1, 1)               # scale, x offset, y offset, picture w, h
        self._hits = []                              # clickable atlas markers
        self._build_widgets()
        self.show_atlas()

    # ---- widgets -------------------------------------------------------------
    def _build_widgets(self):
        t = THEME
        panel = ttk.Frame(self, padding=10)
        panel.pack(side="left", fill="y")

        self.mini = tk.Canvas(panel, width=MINI_PX, height=MINI_PX, bg=t["canvas_bg"],
                              highlightthickness=1, highlightbackground=t["border"])
        self.mini.pack(pady=(0, 8))

        ttk.Label(panel, text="Region", font=(self.font_family, self.font_size, "bold")).pack(anchor="w")
        self.choice = tk.StringVar(value=ATLAS_LABEL)
        self.labels = {r.label: stem for stem, r in self.regions.items()}
        box = ttk.Combobox(panel, textvariable=self.choice, state="readonly", width=34,
                           values=[ATLAS_LABEL] + sorted(self.labels))
        box.pack(fill="x")
        box.bind("<<ComboboxSelected>>", lambda e: self.on_choice())
        ttk.Button(panel, text="< Back to atlas", command=self.show_atlas).pack(fill="x", pady=(4, 8))

        view_frame = ttk.Frame(panel)
        view_frame.pack(fill="x", pady=(0, 8))
        self.view_choice = tk.StringVar(value="atlas")
        ttk.Radiobutton(view_frame, text="Atlas view", value="atlas", variable=self.view_choice,
                        command=self.set_view).pack(side="left", expand=True)
        ttk.Radiobutton(view_frame, text="Cross section", value="cross", variable=self.view_choice,
                        command=self.set_view).pack(side="left", expand=True)

        # one group per node: pick it, then click the map OR type its coordinates
        self.active = tk.StringVar(value="gNB")
        self.lon_vars = {w: tk.StringVar() for w in NODES}
        self.lat_vars = {w: tk.StringVar() for w in NODES}
        self.height_vars = {"gNB": tk.StringVar(value=str(GNB_HEIGHT_M)),
                            "UE": tk.StringVar(value=str(UE_HEIGHT_M))}
        for who in NODES:
            group = ttk.LabelFrame(panel, text=f" {who} ", style=f"{who}.TLabelframe", padding=6)
            group.pack(fill="x", pady=3)
            top = ttk.Frame(group)
            top.pack(fill="x")
            ttk.Radiobutton(top, text="Place by clicking the map", value=who,
                            variable=self.active).pack(side="left")
            ttk.Label(top, text="  height (m)").pack(side="left")
            ttk.Entry(top, textvariable=self.height_vars[who], width=6).pack(side="left", padx=2)
            row = ttk.Frame(group)
            row.pack(fill="x", pady=(5, 0))
            for text, var in (("lon", self.lon_vars[who]), ("lat", self.lat_vars[who])):
                ttk.Label(row, text=text).pack(side="left")
                entry = ttk.Entry(row, textvariable=var, width=11)
                entry.pack(side="left", padx=(2, 6))
                entry.bind("<FocusIn>", lambda e, w=who: self.active.set(w))
                entry.bind("<Return>", lambda e, w=who: self.place_from_entries(w))
            ttk.Button(row, text="Place", width=6,
                       command=lambda w=who: self.place_from_entries(w)).pack(side="left")
            if who == "gNB":
                ttk.Button(group, text=f"Place optimal gNB ({OPTIMAL_GNB_FREQ_GHZ:g} GHz)",
                           command=self.place_optimal_gnb).pack(fill="x", pady=(5, 0))

        group = ttk.LabelFrame(panel, text=" gNB default for this region ", padding=6)
        group.pack(fill="x", pady=3)
        ttk.Button(group, text="Save gNB as default", command=self.save_default).pack(side="left")
        ttk.Button(group, text="Clear default", command=self.clear_default).pack(side="left", padx=6)

        self.sep_var = tk.StringVar(value="Separation: -")
        ttk.Label(panel, textvariable=self.sep_var, font=(self.font_family, self.font_size, "bold")
                  ).pack(anchor="w", pady=(6, 0))
        self.show_cands = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Show atlas candidate masts", variable=self.show_cands,
                        command=self.redraw,
                        state="normal" if self.candidates else "disabled").pack(anchor="w", pady=4)

        self.show_grid = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Show lon/lat grid", variable=self.show_grid,
                        command=self.redraw).pack(anchor="w")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(0, 4))
        self.show_topo = tk.BooleanVar(value=False)
        self.topo_opacity = tk.DoubleVar(value=TOPO_OPACITY)
        ttk.Checkbutton(row, text="Topographic overlay", variable=self.show_topo,
                        command=self.on_topo_toggle).pack(side="left")
        self.show_psr = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Permanently shadowed regions", variable=self.show_psr,
                        command=self.on_psr_toggle).pack(anchor="w", pady=(0, 4))
        
        ttk.Button(panel, text="Set OAI CONF template folder (optional)",
                   command=self.choose_template_dir).pack(fill="x")
        ttk.Button(panel, text="Export gNB + UE configs...", command=self.export).pack(fill="x", pady=4)
        ttk.Button(panel, text="Clear markers", command=self.clear_points).pack(fill="x")

        self.status = tk.StringVar()
        ttk.Label(panel, textvariable=self.status, wraplength=330, style="Muted.TLabel").pack(
            anchor="w", pady=8)

        self.canvas = tk.Canvas(self, bg=t["canvas_bg"], highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)

    # ---- screens -------------------------------------------------------------
    def _load(self, path):
        if path not in self.rasters:
            self.status.set("Loading map...")
            self.update_idletasks()
            self.rasters[path] = Raster(path)
        return self.rasters[path]

    def show_atlas(self):
        self.mode, self.region = "atlas", None
        self.view_mode = "atlas"
        if hasattr(self, "view_choice"):
            self.view_choice.set("atlas")
        self.choice.set(ATLAS_LABEL)
        self.points = {"gNB": None, "UE": None}
        try:
            self.raster = self.pole = self._load(POLE_DEM)
            self.mini_photo = ImageTk.PhotoImage(self.pole.display.resize((MINI_PX, MINI_PX)))
            self.status.set(f"Click a marker to open a region ({len(self.regions)} regions with terrain).")
        except (OSError, ValueError) as err:
            self.raster = None
            messagebox.showerror("Atlas", f"Cannot read {POLE_DEM}\n{err}")
        self._append_topo_note()
        self.update_readout(clear=True)
        self.redraw()

    def show_region(self, stem):
        region = self.regions[stem]
        try:
            raster = self._load(region.dem_path)
        except (OSError, ValueError) as err:
            messagebox.showerror("Region map", f"Cannot read {region.dem_path}\n{err}")
            return
        self.mode, self.region, self.raster, self.focus = "region", region, raster, region
        self.view_mode = "atlas"
        if hasattr(self, "view_choice"):
            self.view_choice.set("atlas")
        self.choice.set(region.label)
        self.points = {"gNB": None, "UE": None}
        note = self._apply_gnb_default(stem, raster)
        bdem = find_bdem(stem)
        warn = "" if os.path.exists(bdem) else "  WARNING: no .bdem found for this region."
        self.status.set(f"{region.label}: click the map or type coordinates.{note}{warn}")
        self._append_topo_note()
        self.update_readout(clear=True)
        self.redraw()

    def on_choice(self):
        label = self.choice.get()
        self.show_atlas() if label == ATLAS_LABEL else self.show_region(self.labels[label])

    # ---- drawing -------------------------------------------------------------
    def _label(self, canvas, x, y, text, fg, anchor="sw", size=None, bold=False, clamp=None):
        """Text on a dark plate so it stays readable over any map. `clamp` = (w, h) keeps it inside."""
        font = (self.font_family, size or self.font_size, "bold" if bold else "normal")
        item = canvas.create_text(x, y, text=text, fill=fg, anchor=anchor, font=font)
        x1, y1, x2, y2 = canvas.bbox(item)
        if clamp:
            dx = max(4 - x1, 0) or min(clamp[0] - 4 - x2, 0)
            dy = max(4 - y1, 0) or min(clamp[1] - 4 - y2, 0)
            canvas.move(item, dx, dy)
            x1, y1, x2, y2 = canvas.bbox(item)
        plate = canvas.create_rectangle(x1 - 3, y1 - 2, x2 + 3, y2 + 2, fill=THEME["label_bg"], outline="")
        canvas.tag_lower(plate, item)

    def redraw(self):
        self.draw_minimap()
        c = self.canvas
        c.delete("all")
        if self.raster is None:
            self._label(c, 20, 20, f"Atlas map not found. Expected: {POLE_DEM}", THEME["label_fg"], "nw")
            return
        cw, ch = c.winfo_width(), c.winfo_height()
        iw, ih = self.raster.display.size
        scale = min(cw / iw, ch / ih)
        ox, oy = (cw - iw * scale) / 2, (ch - ih * scale) / 2
        self._view = (scale, ox, oy, iw, ih)
        size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        if self.mode == "region" and self.view_mode == "cross":
            self.cross_section_view()
            return
        self.photo = ImageTk.PhotoImage(self._background(size))
        c.create_image(ox, oy, anchor="nw", image=self.photo)
        if self.show_grid.get():
            self._draw_grid()
        if self.mode == "atlas":
            self._draw_atlas_markers()
        else:
            self._draw_region_overlays()
        self._draw_legend(*self._map_legend())

    # ---- topographic overlay -------------------------------------------------
    def _current_overlay(self):
        """The overlay picture for the map on screen (None if there is none)."""
        key = self.region.stem if self.mode == "region" and self.region else None
        if key not in self._topo_cache:
            path = find_topo_overlay(key)
            try:
                img = load_overlay(path) if path else None
            except (OSError, ValueError):
                img = None
            self._topo_cache[key] = (img, path)
        return self._topo_cache[key][0]

    def _topo_note(self):
        """Why the overlay is missing or may not line up; empty if all is well."""
        if self.raster is None:
            return ""
        img = self._current_overlay()
        if img is None:
            return "No topographic overlay (*_topo_hq.png) found for this view."
        if abs((img.width / img.height) / (self.raster.width / self.raster.height) - 1) > 0.01:
            return "The overlay has a different shape from the map, so it is stretched and may not line up."
        return ""

    def _append_topo_note(self):
        notes = [self._topo_note() if self.show_topo.get() else "", self._psr_note() if self.show_psr.get() else ""]
        notes = [n for n in notes if n]
        if notes:
            self.status.set(self.status.get() + "  " + "  ".join(notes))

    def _current_psr(self):
        """The shadowed-region layer for the map on screen (None if there is no file)."""
        key = self.region.stem if self.mode == "region" and self.region else None
        if key not in self._psr_cache:
            path = POLE_PSR if key is None else os.path.join(REGION_DIR, f"{key}__psr.tif")
            self.status.set("Loading shadowed regions...")
            self.update_idletasks()
            try:
                layer = PsrLayer(path) if os.path.exists(path) else None
            except (OSError, ValueError):
                layer = None
            self._psr_cache[key] = layer
        return self._psr_cache[key]

    def _psr_note(self):
        if self.raster is None:
            return ""
        return "" if self._current_psr() else "No permanently shadowed region file (*_psr.tif) found for this view."

    def on_psr_toggle(self):
        if self.show_psr.get():
            self.status.set(self._psr_note() or "Permanently shadowed regions shown.")
        self.redraw()

    def on_topo_toggle(self):
        if self.show_topo.get():
            self.status.set(self._topo_note() or "Topographic overlay on.")
        self.redraw()

    def _background(self, size):
        """The map picture at `size`, with the overlay composited on top when it is switched on."""
        overlay = self._current_overlay() if self.show_topo.get() else None
        psr = self._current_psr() if self.show_psr.get() else None

        opacity = round(self.topo_opacity.get(), 2)
        key = (id(self.raster), size, id(overlay), id(psr), opacity)
        if key != self._bg_key:
            base = self.raster.display.resize(size)
            if psr is not None:                                  # shadow tint sits under the topo lines
                base = Image.alpha_composite(base.convert("RGBA"), psr.render(self.raster, size))
            if overlay is not None:
                base = base.convert("RGBA")
                top = resize_rgba(overlay, size)
                top.putalpha(top.getchannel("A").point(lambda a: int(a * opacity)))
                base = Image.alpha_composite(base, top)
            self._bg_img, self._bg_key = base, key
        return self._bg_img

    # ---- legend ---------------------------------------------------------------
    def _map_legend(self):
        """(items, scale bar) describing what is on the map right now."""
        t = THEME
        if self.mode == "atlas":
            items = [("dot", t["marker"], "Region with terrain tile")]
            if self.missing:
                items.append(("ring", t["missing_fg"], "Site without terrain tile"))
            if self.focus:
                items.append(("box", t["footprint"], "Last opened region"))
        else:
            items = [("dot", t["gnb"], "gNB"), ("dot", t["ue"], "UE"),
                     ("dash", t["link"], "Line between gNB and UE")]
            if self.show_cands.get():
                items += [("dot", t["cand_ridge"], "Candidate mast (ridge)"),
                          ("dot", t["cand_landing"], "Candidate mast (landing site)")]
        if self.show_psr.get() and self._current_psr():
            items.append(("fill", t["psr"], "Permanently shadowed region"))
        if self.show_topo.get() and self._current_overlay() is not None:
            items.append(("line", "#bdbdbd", "Topographic overlay"))
        if self.show_grid.get():
            items.append(("line", t["grid"], "Lon/lat grid"))
        zoom, ox, oy, iw, ih = self._view
        return items, scale_bar(self.raster.width * self.raster.dx / (iw * zoom))

    def _draw_legend(self, items, scale=None):
        """Legend plate in the bottom-right corner. items: [(kind, colour, text)], kind one of
        dot / ring / line / dash / box / fill, or None for a plain text line. scale: (bar pixels, label)."""
        c, t = self.canvas, THEME
        font = (self.font_family, self.font_size)
        row = int(self.font_size * 2.2) + 2
        y = 0
        for kind, colour, text in items:
            cy = y + row / 2
            if kind == "dot":
                c.create_oval(4, cy - 5, 14, cy + 5, fill=colour, outline=t["marker_outline"], width=2, tags="legend")
            elif kind == "ring":
                c.create_oval(4, cy - 5, 14, cy + 5, outline=colour, width=2, tags="legend")
            elif kind in ("line", "dash"):
                c.create_line(0, cy, 24, cy, fill="#cfd8dc", width=4, tags="legend")   # light backing keeps dark lines visible
                c.create_line(0, cy, 24, cy, fill=colour, width=2, dash=(5, 3) if kind == "dash" else None, tags="legend")
            elif kind == "box":
                c.create_rectangle(2, cy - 5, 16, cy + 5, outline=colour, width=2, tags="legend")
            elif kind == "fill":
                c.create_rectangle(2, cy - 5, 16, cy + 5, fill=colour, outline="", tags="legend")
            c.create_text(30 if kind else 2, cy, text=text, anchor="w", fill=t["label_fg"], font=font, tags="legend")
            y += row
        if scale:
            length, label = scale
            y += 6
            c.create_line(0, y + 4, length, y + 4, fill=t["label_fg"], width=2, tags="legend")
            for x in (0, length):
                c.create_line(x, y, x, y + 8, fill=t["label_fg"], width=2, tags="legend")
            c.create_text(length / 2, y + 11, text=label, anchor="n", fill=t["label_fg"], font=font, tags="legend")
        box = c.bbox("legend")
        if not box:
            return
        c.move("legend", c.winfo_width() - 16 - box[2], c.winfo_height() - 16 - box[3])
        x1, y1, x2, y2 = c.bbox("legend")
        plate = c.create_rectangle(x1 - 8, y1 - 8, x2 + 8, y2 + 8, fill=t["label_bg"], outline=t["border"])
        c.tag_lower(plate, "legend")

    def _canvas_xy(self, fx, fy):
        scale, ox, oy, iw, ih = self._view
        return ox + fx * iw * scale, oy + fy * ih * scale

    def _draw_atlas_markers(self):
        t, c = THEME, self.canvas
        size = (c.winfo_width(), c.winfo_height())
        self._hits = []
        for stem, reg in self.regions.items():
            x, y = self._canvas_xy(*self.raster.xy_to_frac(*lonlat_to_xy(*reg.lonlat)))
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=t["marker"], outline=t["marker_outline"], width=2)
            if reg is not self.focus:                       # the focused region gets a bold label instead
                tag = " [gNB]" if stem in self.gnb_defaults else ""
                self._label(c, x + 9, y - 9, reg.label + tag, t["label_fg"], "sw", clamp=size)
            self._hits.append((x, y, stem))
        for sid, name, lon, lat in self.missing:            # no terrain tile: hollow, grey
            x, y = self._canvas_xy(*self.raster.xy_to_frac(*lonlat_to_xy(lon, lat)))
            c.create_oval(x - 4, y - 4, x + 4, y + 4, outline=t["missing_fg"], width=2)
            self._label(c, x + 8, y - 8, f"{sid} (no tile)", t["missing_fg"], "sw", clamp=size)
            self._hits.append((x, y, ("missing", name)))
        self._draw_highlight(c, self.focus, self._canvas_xy, size, self.font_size + 2, 16)

    def _draw_highlight(self, canvas, region, to_canvas, size, font_size, min_box):
        """Footprint box and bold name of `region` on an atlas-based canvas (no ring)."""
        if region is None or self.pole is None:
            return
        fx, fy = self.pole.xy_to_frac(*lonlat_to_xy(*region.lonlat))
        cx, cy = to_canvas(fx, fy)
        half_w = half_h = min_box / 2
        tile = self.rasters.get(region.dem_path)
        if tile:                                            # true footprint (axis-aligned in the projection)
            ax, ay = to_canvas(*self.pole.xy_to_frac(tile.x0, tile.y0))
            bx, by = to_canvas(*self.pole.xy_to_frac(tile.x0 + tile.width * tile.dx,
                                                     tile.y0 - tile.height * tile.dy))
            half_w, half_h = max(abs(bx - ax) / 2, half_w), max(abs(by - ay) / 2, half_h)
        canvas.create_rectangle(cx - half_w, cy - half_h, cx + half_w, cy + half_h,
                                outline=THEME["footprint"], width=2)
        above = cy - half_h > 30
        ty, anchor = (cy - half_h - 4, "s") if above else (cy + half_h + 4, "n")
        self._label(canvas, cx, ty, region.label, THEME["label_focus_fg"], anchor,
                    size=font_size, bold=True, clamp=size)

    def draw_minimap(self):
        m = self.mini
        m.delete("all")
        if self.pole is None or self.mini_photo is None:
            return
        m.create_image(0, 0, anchor="nw", image=self.mini_photo)
        to_canvas = lambda fx, fy: (fx * MINI_PX, fy * MINI_PX)
        for reg in self.regions.values():
            x, y = to_canvas(*self.pole.xy_to_frac(*lonlat_to_xy(*reg.lonlat)))
            m.create_oval(x - 2, y - 2, x + 2, y + 2, fill=THEME["marker"], outline="")
        self._draw_highlight(m, self.focus, to_canvas, (MINI_PX, MINI_PX), max(self.font_size - 1, 8), 12)

    def _draw_region_overlays(self):
        t, c = THEME, self.canvas
        if self.show_cands.get():
            colors = {"ridge": t["cand_ridge"], "landing_site": t["cand_landing"]}
            for x, y, cls in self.candidates:
                fx, fy = self.raster.xy_to_frac(x, y)
                if 0 <= fx <= 1 and 0 <= fy <= 1:
                    cx, cy = self._canvas_xy(fx, fy)
                    c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=colors.get(cls, "#ffffff"), outline="#000000")
        size = (c.winfo_width(), c.winfo_height())
        if all(self.points.values()):                        # line between gNB and UE, follows the markers
            (x1, y1), (x2, y2) = self._canvas_xy(*self.points["gNB"]), self._canvas_xy(*self.points["UE"])
            c.create_line(x1, y1, x2, y2, fill=t["link"], width=2, dash=(6, 4))
        for who, pt in self.points.items():
            if pt:
                cx, cy = self._canvas_xy(*pt)
                c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill=t["gnb" if who == "gNB" else "ue"],
                              outline=t["marker_outline"], width=2)
                self._label(c, cx + 11, cy - 11, who, t["label_fg"], "sw", bold=True, clamp=size)

    def _draw_grid(self):
        r, c, t = self.raster, self.canvas, THEME
        lon0, lon1, lat0, lat1, pole = raster_lonlat_extent(r)
        pad = (lat1 - lat0) * 0.05                       # sampled extent slightly underestimates
        lat0, lat1 = max(-90.0, lat0 - pad), min(-0.1, lat1 + pad)
        if not pole:
            pad = (lon1 - lon0) * 0.05
            lon0, lon1 = lon0 - pad, lon1 + pad
        lat_step = grid_step(lat1 - lat0)
        lon_step = 30 if pole else grid_step(lon1 - lon0)
        size = (c.winfo_width(), c.winfo_height())

        def trace(points, text, anchor):
            """Project the points, draw each on-screen run as a dashed line, label its start."""
            run, runs = [], []
            for lon, lat in points:
                fx, fy = r.xy_to_frac(*lonlat_to_xy(lon, lat))
                if -0.02 <= fx <= 1.02 and -0.02 <= fy <= 1.02:
                    run.append(self._canvas_xy(fx, fy))
                elif run:
                    runs.append(run)
                    run = []
            if run:
                runs.append(run)
            for pts in runs:
                if len(pts) >= 2:
                    #c.create_line(*[v for p in pts for v in p], fill=t["grid"], dash=(3, 4)) #dashed line
                    c.create_line(*[v for p in pts for v in p], fill=t["grid"], width=2) #solid line
            if runs and runs[0]:
                self._label(c, *runs[0][0], text, t["grid_label"], anchor,
                            size=max(self.font_size - 1, 7), clamp=size)

        def fmt(v, step):
            d = max(0, math.ceil(-math.log10(step) - 1e-9))
            return f"{v:.{d}f}\u00b0"

        n = 120
        for lat in frange(lat0, lat1, lat_step):          # parallels
            if lat <= -90.0:
                continue
            pts = [(lon0 + (lon1 - lon0) * i / n, lat) for i in range(n + 1)]
            trace(pts, fmt(lat, lat_step), "sw")
        lon_end = lon1 - 1e-9 if pole else lon1            # avoid drawing -180 and +180 twice
        for lon in frange(lon0, lon_end, lon_step):       # meridians
            pts = [(lon, lat0 + (lat1 - lat0) * i / 60) for i in range(61)]
            shown = ((lon + 180) % 360) - 180
            trace(pts, fmt(shown, lon_step), "nw")    

    # ---- clicks --------------------------------------------------------------
    def _frac(self, event):
        scale, ox, oy, iw, ih = self._view
        return (event.x - ox) / (iw * scale), (event.y - oy) / (ih * scale)

    def on_press(self, event):
        if self.raster is None or self.view_mode == "cross":
            return
        if self.mode == "atlas":
            hits = [(math.hypot(event.x - x, event.y - y), t) for x, y, t in self._hits]
            if hits and min(hits, key=lambda h: h[0])[0] <= 14:
                target = min(hits, key=lambda h: h[0])[1]
                if isinstance(target, tuple):
                    messagebox.showinfo("No terrain tile", f"{target[1]} has no region tile in this atlas release.")
                else:
                    self.show_region(target)
        else:
            self.place(event)

    def on_drag(self, event):
        if self.mode == "region" and self.view_mode != "cross":
            self.place(event)

    def place(self, event):
        fx, fy = self._frac(event)
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            self.status.set("Click inside the map: points must lie within the terrain tile.")
            return
        self.points[self.active.get()] = (fx, fy)
        self.update_readout()
        self.redraw()

    def lonlat(self, who):
        pt = self.points[who]
        return xy_to_lonlat(*self.raster.frac_to_xy(*pt)) if pt and self.mode == "region" else None

    def update_readout(self, clear=False):
        """Keep the lon/lat boxes in step with the markers; refresh the separation."""
        ll = {w: self.lonlat(w) for w in NODES}
        for who, v in ll.items():
            if v:
                self.lon_vars[who].set(f"{v[0]:.6f}")
                self.lat_vars[who].set(f"{v[1]:.6f}")
            elif clear:
                self.lon_vars[who].set("")
                self.lat_vars[who].set("")
        g, u = ll["gNB"], ll["UE"]
        self.sep_var.set(f"Separation: {distance_m(g, u):.0f} m" if g and u else "Separation: -")

    def clear_points(self):
        self.points = {"gNB": None, "UE": None}
        self.update_readout(clear=True)
        self.redraw()

    # ---- typed coordinates and default gNB -----------------------------------
    def place_from_entries(self, who):
        """Put `who` at the typed lon/lat. Returns True on success."""
        if self.mode != "region":
            messagebox.showinfo("Open a region", "Open a region first.")
            return False
        try:
            lon, lat = float(self.lon_vars[who].get()), float(self.lat_vars[who].get())
        except ValueError:
            messagebox.showwarning("Invalid coordinates", f"{who}: longitude and latitude must be numbers.")
            return False
        fx, fy = self.raster.xy_to_frac(*lonlat_to_xy(lon, lat))
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            messagebox.showwarning("Outside the tile", f"{who}: that position is outside this region's map.")
            return False
        self.points[who] = (fx, fy)
        self.active.set(who)
        self.update_readout()
        self.redraw()
        return True

    def _apply_gnb_default(self, stem, raster):
        """Place the saved default gNB for a region. Returns a note for the status line."""
        d = self.gnb_defaults.get(stem)
        if not d:
            return ""
        fx, fy = raster.xy_to_frac(*lonlat_to_xy(d[0], d[1]))
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            return "  Saved default gNB is outside this tile (ignored)."
        self.points["gNB"] = (fx, fy)
        if d[2] is not None:
            self.height_vars["gNB"].set(f"{d[2]:g}")
        return "  Default gNB placed."

    def save_default(self):
        if not self.place_from_entries("gNB"):
            return
        try:
            height = float(self.height_vars["gNB"].get())
        except ValueError:
            messagebox.showwarning("Invalid height", "gNB height must be a number.")
            return
        lon, lat = self.lonlat("gNB")
        self.gnb_defaults[self.region.stem] = (lon, lat, height)
        save_gnb_defaults(self.gnb_defaults)
        self.status.set(f"Saved default gNB for {self.region.label} ({lon:.5f}, {lat:.5f}, {height:g} m).")

    def clear_default(self):
        if self.mode == "region" and self.gnb_defaults.pop(self.region.stem, None):
            save_gnb_defaults(self.gnb_defaults)
            self.status.set(f"Cleared the default gNB for {self.region.label}.")
        else:
            self.status.set("No saved default for this region.")

    def place_optimal_gnb(self):
        """Run optimal_gNB.find_best_mast() for the open region and place the result as the gNB."""
        if self.mode != "region":
            messagebox.showinfo("Open a region", "Open a region first.")
            return
        try:
            from optimal_gNB import find_best_mast
        except ImportError as err:
            messagebox.showerror("Missing dependency",
                                  f"Could not load optimal_gNB.py: {err}\n(pip install pandas)")
            return
        region_id = int(self.region.sites[0][0])
        try:
            best = find_best_mast(
                region_id=region_id,
                freq_GHz=OPTIMAL_GNB_FREQ_GHZ,
                candidates_csv=OPTIMAL_GNB_CANDIDATES_CSV,
                index_csv=OPTIMAL_GNB_INDEX_CSV,
            )
        except (OSError, ValueError) as err:
            messagebox.showerror("Optimal gNB", str(err))
            return
        if best is None:
            messagebox.showwarning(
                "Optimal gNB",
                f"No candidate mast found for {self.region.label} "
                f"(region id {region_id}) in site_tiles_index.csv.")
            return
        lon, lat = float(best["lon_e"]), float(best["lat"])
        fx, fy = self.raster.xy_to_frac(*lonlat_to_xy(lon, lat))
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            messagebox.showwarning("Outside the tile",
                                    "The optimal mast for this region lies outside its terrain tile.")
            return
        self.points["gNB"] = (fx, fy)
        self.height_vars["gNB"].set(f"{float(best['mast_height_m']):g}")
        self.active.set("gNB")
        self.update_readout()
        self.redraw()
        coverage_col = f"area_km2_{OPTIMAL_GNB_FREQ_GHZ:.3f}GHz"
        self.status.set(
            f"Optimal gNB for {self.region.label}: mast {best['cand_id']} "
            f"({lon:.5f}, {lat:.5f}), {float(best[coverage_col]):.1f} km² "
            f"coverage @ {OPTIMAL_GNB_FREQ_GHZ:g} GHz.")


    def set_view(self):
        """Switch between the terrain atlas and the gNB-to-UE cross section."""
        choice = self.view_choice.get()
        if choice == "cross":
            if self.mode != "region":
                messagebox.showinfo("Open a region", "Open a region before showing a cross section.")
                self.view_choice.set("atlas")
                return
            if not all(self.points.values()):
                messagebox.showwarning("Markers required", "Place both the gNB and the UE before showing a cross section.")
                self.view_choice.set("atlas")
                return
            self.view_mode = "cross"
        else:
            self.view_mode = "atlas"
        self.redraw()

    def cross_section_view(self):
        """Draw the DEM terrain and the antenna heights along the line between the gNB and the UE."""
        c, t = self.canvas, THEME
        c.delete("all")

        def message(text):
            self._label(c, 20, 20, text, t["label_fg"], "nw")

        if self.mode != "region":
            return message("Open a region to view a cross section.")
        if not all(self.points.values()):
            return message("Place both the gNB and the UE to view a cross section.")
        try:
            gnb_h, ue_h = float(self.height_vars["gNB"].get()), float(self.height_vars["UE"].get())
        except ValueError:
            return message("Antenna heights must be numbers.")
        if not (np.isfinite(gnb_h) and np.isfinite(ue_h)):
            return message("Antenna heights must be finite numbers.")
        gnb_ll, ue_ll = self.lonlat("gNB"), self.lonlat("UE")
        if gnb_ll == ue_ll:
            return message("gNB and UE cannot be at the same position.")

        dist, terrain = elevation_profile(self.raster, self.points["gNB"], self.points["UE"])
        valid = np.isfinite(terrain)
        if not (valid[0] and valid[-1]):
            return message("The DEM has no elevation data at the gNB or the UE position.")
        z_gnb, z_ue = float(terrain[0]), float(terrain[-1])

        cw, ch = c.winfo_width(), c.winfo_height()
        left, right, top, bottom = 75, max(85, cw - 260), 35, max(70, ch - 55)   # right column holds the legend
        if right <= left or bottom <= top:
            return
        xmax = max(float(dist[-1]), 1.0)
        values = np.concatenate((terrain[valid].astype(float), [z_gnb + gnb_h, z_ue + ue_h]))
        zmin, zmax = float(values.min()), float(values.max())
        zspan = max(zmax - zmin, 1.0)
        zmin, zmax = zmin - zspan * 0.12, zmax + zspan * 0.12
        def px(d): return left + d / xmax * (right - left)
        def py(z): return bottom - (z - zmin) / (zmax - zmin) * (bottom - top)

        c.create_text((left + right) // 2, 16, text=f"Cross section: {self.region.label}",
                      fill=t["label_fg"], font=(self.font_family, self.font_size + 2, "bold"))
        c.create_line(left, bottom, right, bottom, fill="#9e9e9e")
        c.create_line(left, top, left, bottom, fill="#9e9e9e")

        idx = np.flatnonzero(valid)                                  # draw each run of valid data on its own
        for run in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
            if len(run) < 2:
                continue
            pts = [v for i in run for v in (px(float(dist[i])), py(float(terrain[i])))]
            c.create_polygon([pts[0], bottom] + pts + [pts[-2], bottom], fill=t["terrain_fill"], outline="")
            c.create_line(*pts, fill=t["terrain_line"], width=2)

        tops = {}
        for who, d, z_ground, height, color in (("gNB", 0.0, z_gnb, gnb_h, t["gnb"]),
                                                 ("UE", xmax, z_ue, ue_h, t["ue"])):
            tops[who] = (px(d), py(z_ground + height))
        c.create_line(*tops["gNB"], *tops["UE"], fill=t["link"], width=2, dash=(6, 4))   # gNB-UE line
        for who, d, z_ground, height, color in (("gNB", 0.0, z_gnb, gnb_h, t["gnb"]),
                                                 ("UE", xmax, z_ue, ue_h, t["ue"])):
            x, y_top = tops[who]
            c.create_line(x, py(z_ground), x, y_top, fill=color, width=3)
            c.create_oval(x - 5, y_top - 5, x + 5, y_top + 5, fill=color, outline="#ffffff")
            at_start = who == "gNB"
            self._label(c, x + (8 if at_start else -8), y_top - 8, f"{who} {height:g} m",
                        t["label_fg"], "sw" if at_start else "se")

        for frac in range(5):
            d = xmax * frac / 4
            c.create_text(px(d), bottom + 18, text=f"{d / 1000:.2f} km", fill=t["label_fg"])
        c.create_text((left + right) // 2, ch - 12, text="Distance", fill=t["label_fg"])
        c.create_text(18, (top + bottom) // 2, text="Elevation (m)", fill=t["label_fg"], angle=90)
        for frac in range(5):
            z = zmin + (zmax - zmin) * frac / 4
            c.create_text(left - 8, py(z), text=f"{z:.0f}", anchor="e", fill=t["label_fg"])

        m_per_px_h = xmax / (right - left)
        exaggeration = m_per_px_h / ((zmax - zmin) / (bottom - top))
        self._draw_legend(
            [("fill", t["terrain_fill"], "Terrain (DEM)"),
             ("dot", t["gnb"], f"gNB antenna, {gnb_h:g} m"),
             ("dot", t["ue"], f"UE antenna, {ue_h:g} m"),
             ("dash", t["link"], "Line between gNB and UE"),
             (None, None, f"Vertical exaggeration x{exaggeration:.1f}")],
            scale_bar(m_per_px_h))
        self.status.set(f"Cross section: {distance_m(gnb_ll, ue_ll):.0f} m separation; "
                        f"terrain from {os.path.basename(self.region.dem_path)}")

    # ---- export --------------------------------------------------------------
    def choose_template_dir(self):
        folder = filedialog.askdirectory(title="OAI targets/PROJECTS/GENERIC-NR-5GC/CONF folder")
        if folder:
            self.template_dir = folder
            self.status.set(f"Templates: {folder}")

    def export(self):
        if self.mode != "region" or not all(self.points.values()):
            messagebox.showwarning("Not ready", "Open a region and place both the gNB and the UE.")
            return
        try:
            heights = {w: float(v.get()) for w, v in self.height_vars.items()}
        except ValueError:
            messagebox.showwarning("Invalid height", "Antenna heights must be numbers.")
            return
        g, u = self.lonlat("gNB"), self.lonlat("UE")
        if g == u:
            messagebox.showwarning("Same point", "gNB and UE are at the same position.")
            return
        bdem = find_bdem(self.region.stem)
        if not os.path.exists(bdem) and not messagebox.askyesno(
                "Missing .bdem",
                f"{bdem} was not found.\nThe simulator would fall back to flat terrain. Export anyway?"):
            return
        os.makedirs(EXPORT_DIR, exist_ok=True)
        out_dir = filedialog.askdirectory(title="Choose output folder (a dated subfolder is created)",
                                          initialdir=EXPORT_DIR)
        if not out_dir:
            return
        run_dir = make_run_folder(out_dir, self.region.label)
        export_configs(run_dir, self.template_dir, g, u, heights["gNB"], heights["UE"], bdem)
        self.status.set(f"Exported to:\n{run_dir}")


def main():
    try:
        regions, missing = load_catalog()
    except (OSError, KeyError, ValueError) as err:
        messagebox.showerror("Site list", f"Could not read {SITES_CSV}:\n{err}")
        return
    PlannerApp(regions, missing if SHOW_SITES_WITHOUT_TILE else [], load_candidates()).mainloop()


if __name__ == "__main__":
    main()