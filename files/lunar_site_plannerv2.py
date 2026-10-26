"""Lunar Site Planner v2: south-pole atlas -> click a region -> place gNB and UE -> export BICTR configs.

Run:  python lunar_site_planner.py        (needs: pip install pillow numpy)

Sections (read top to bottom):
  1. Settings        - paths and defaults
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
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

Image.MAX_IMAGE_PIXELS = None

# ----------------------------------------------------------------------------
# 1. SETTINGS
# ----------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ATLAS_DIR = os.path.join(APP_DIR, "atlas_v2", "bundle", "context")      # from the Zenodo archive
POLE_DEM = os.path.join(ATLAS_DIR, "pole_dem_160m.tif")
REGION_DIR = os.path.join(ATLAS_DIR, "regions")                          # <Region>__dem.tif
CANDIDATES_CSV = os.path.join(APP_DIR, "data", "atlas_base", "candidates_freeze.csv")
SITES_CSV = os.path.join(APP_DIR, "sites.csv")                           # id,name,lat_deg,lon_deg
TERRAIN_DIR = os.path.join(APP_DIR, "terrain")                           # your .bdem files
POLE_BDEM = "lunar_south_pole.bdem"      # used when there is no region-specific .bdem
EXPORT_DIR = os.path.join(APP_DIR, "exports")
GNB_DEFAULTS_CSV = os.path.join(APP_DIR, "gnb_defaults.csv")             # region,lon,lat,height_m
MINI_PX = 230                            # size of the atlas minimap in the side panel

BODY_RADIUS_M = 1_737_400.0              # Moon sphere used by the atlas and bictr_body_radius
GNB_HEIGHT_M = 4.0                       # atlas radio_params.json: mast_height_m
UE_HEIGHT_M = 1.5                        # atlas radio_params.json: rx_height_m
DISPLAY_MAX_PX = 1800                    # maps are shown at most this many pixels wide/high
REGION_ALIASES = {"Leibnitz_Beta_Plateau": "Mons_Mouton"}   # same massif (see Bictr notes)

GNB_CONF = "gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf"
UE_CONF = "ue.bictr.conf"
BLOCK_GNB_SIDE = "rfsimu_channel_enB0"   # TX = gNB, RX = UE
BLOCK_UE_SIDE = "rfsimu_channel_ue0"     # TX = UE,  RX = gNB (swapped)
MARKER_COLORS = {"gNB": "#e53935", "UE": "#1e88e5"}


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
    dzdx, dzdy = gx, -gy                                  # rows run south, so flip y
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
        self.display = _shade(arr, mask, self.dx)
        self.display.thumbnail((DISPLAY_MAX_PX, DISPLAY_MAX_PX))

    def frac_to_xy(self, fx, fy):
        """(0..1, 0..1) position across the picture -> projected metres."""
        return self.x0 + fx * self.width * self.dx, self.y0 - fy * self.height * self.dy

    def xy_to_frac(self, x, y):
        return (x - self.x0) / (self.width * self.dx), (self.y0 - y) / (self.height * self.dy)


# ----------------------------------------------------------------------------
# 4. CATALOG  (sites.csv -> regions; .bdem lookup; candidate masts)
# ----------------------------------------------------------------------------
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


class PlannerApp(tk.Tk):
    def __init__(self, regions, missing, candidates):
        super().__init__()
        self.title("Lunar Site Planner")
        self.geometry("1200x820")
        self.regions, self.missing, self.candidates = regions, missing, candidates
        self.rasters = {}               # cache: path -> Raster
        self.mode = "atlas"             # "atlas" or "region"
        self.region = None
        self.raster = None
        self.photo = None
        self.pole = None                # the atlas raster (kept while a region is open)
        self.focus = None               # region highlighted on the atlas (last one opened)
        self.mini_photo = None
        self.gnb_defaults = load_gnb_defaults()
        self.points = {"gNB": None, "UE": None}      # (fx, fy) fractions of the region picture
        self.template_dir = ""
        self._view = (1.0, 0, 0, 1, 1)               # scale, x offset, y offset, picture w, h
        self._hits = []                              # clickable atlas markers
        self._build_widgets()
        self.show_atlas()

    # ---- widgets -------------------------------------------------------------
    def _build_widgets(self):
        panel = ttk.Frame(self, padding=10)
        panel.pack(side="left", fill="y")

        self.mini = tk.Canvas(panel, width=MINI_PX, height=MINI_PX, bg="#202020", highlightthickness=1)
        self.mini.pack(pady=(0, 8))

        ttk.Label(panel, text="1. Choose a region").pack(anchor="w")
        self.choice = tk.StringVar(value=ATLAS_LABEL)
        self.labels = {r.label: stem for stem, r in self.regions.items()}
        box = ttk.Combobox(panel, textvariable=self.choice, state="readonly", width=30,
                           values=[ATLAS_LABEL] + sorted(self.labels))
        box.pack(fill="x")
        box.bind("<<ComboboxSelected>>", lambda e: self.on_choice())
        ttk.Button(panel, text="< Back to atlas", command=self.show_atlas).pack(fill="x", pady=(4, 10))

        ttk.Label(panel, text="2. Place on the map (click or drag)").pack(anchor="w")
        self.active = tk.StringVar(value="gNB")
        for who in ("gNB", "UE"):
            ttk.Radiobutton(panel, text=who, value=who, variable=self.active).pack(anchor="w")

        ttk.Label(panel, text="gNB default for this region").pack(anchor="w", pady=(8, 0))
        self.gnb_lon_var, self.gnb_lat_var = tk.StringVar(), tk.StringVar()
        row = ttk.Frame(panel)
        row.pack(fill="x")
        for text, var in (("lon", self.gnb_lon_var), (" lat", self.gnb_lat_var)):
            ttk.Label(row, text=text).pack(side="left")
            ttk.Entry(row, textvariable=var, width=11).pack(side="left")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        ttk.Button(row, text="Place gNB at lon/lat", command=self.place_gnb_from_entries).pack(side="left")
        row = ttk.Frame(panel)
        row.pack(fill="x")
        ttk.Button(row, text="Save as default", command=self.save_default).pack(side="left")
        ttk.Button(row, text="Clear default", command=self.clear_default).pack(side="left", padx=4)

        ttk.Label(panel, text="3. Antenna heights (m)").pack(anchor="w", pady=(10, 0))
        self.height_vars = {"gNB": tk.StringVar(value=str(GNB_HEIGHT_M)),
                            "UE": tk.StringVar(value=str(UE_HEIGHT_M))}
        for who, var in self.height_vars.items():
            row = ttk.Frame(panel)
            row.pack(fill="x")
            ttk.Label(row, text=who, width=5).pack(side="left")
            ttk.Entry(row, textvariable=var, width=8).pack(side="left")

        self.show_cands = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Show atlas candidate masts", variable=self.show_cands,
                        command=self.redraw,
                        state="normal" if self.candidates else "disabled").pack(anchor="w", pady=(10, 0))

        ttk.Label(panel, text="Readout").pack(anchor="w", pady=(10, 0))
        self.readout = {k: tk.StringVar(value="") for k in ("gNB", "UE", "dist")}
        for k in ("gNB", "UE", "dist"):
            ttk.Label(panel, textvariable=self.readout[k]).pack(anchor="w")

        ttk.Label(panel, text="4. Export").pack(anchor="w", pady=(10, 0))
        ttk.Button(panel, text="Set OAI CONF template folder (optional)",
                   command=self.choose_template_dir).pack(fill="x")
        ttk.Button(panel, text="Export gNB + UE configs...", command=self.export).pack(fill="x", pady=4)
        ttk.Button(panel, text="Clear markers", command=self.clear_points).pack(fill="x")

        self.status = tk.StringVar()
        ttk.Label(panel, textvariable=self.status, wraplength=260, foreground="#555").pack(anchor="w", pady=10)

        self.canvas = tk.Canvas(self, bg="#202020", highlightthickness=0)
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
        self.choice.set(ATLAS_LABEL)
        self.points = {"gNB": None, "UE": None}
        try:
            self.raster = self.pole = self._load(POLE_DEM)
            self.mini_photo = ImageTk.PhotoImage(self.pole.display.resize((MINI_PX, MINI_PX)))
            n = len(self.regions)
            self.status.set(f"Click a marker to open a region ({n} regions with terrain).")
        except (OSError, ValueError) as err:
            self.raster = None
            messagebox.showerror("Atlas", f"Cannot read {POLE_DEM}\n{err}")
        self.update_readout()
        self.redraw()

    def show_region(self, stem):
        region = self.regions[stem]
        try:
            raster = self._load(region.dem_path)
        except (OSError, ValueError) as err:
            messagebox.showerror("Region map", f"Cannot read {region.dem_path}\n{err}")
            return
        self.mode, self.region, self.raster, self.focus = "region", region, raster, region
        self.choice.set(region.label)
        self.points = {"gNB": None, "UE": None}
        note = self._apply_gnb_default(stem, raster)
        bdem = find_bdem(stem)
        warn = "" if os.path.exists(bdem) else "  WARNING: no .bdem found for this region."
        self.status.set(f"{region.label}: place the gNB and UE.{note}{warn}")
        self.update_readout()
        self.redraw()

    def on_choice(self):
        label = self.choice.get()
        self.show_atlas() if label == ATLAS_LABEL else self.show_region(self.labels[label])

    # ---- drawing -------------------------------------------------------------
    def redraw(self):
        self.draw_minimap()
        c = self.canvas
        c.delete("all")
        if self.raster is None:
            c.create_text(20, 20, anchor="nw", fill="white",
                          text=f"Atlas map not found.\nExpected: {POLE_DEM}")
            return
        cw, ch = c.winfo_width(), c.winfo_height()
        iw, ih = self.raster.display.size
        scale = min(cw / iw, ch / ih)
        ox, oy = (cw - iw * scale) / 2, (ch - ih * scale) / 2
        self._view = (scale, ox, oy, iw, ih)
        shown = self.raster.display.resize((max(1, int(iw * scale)), max(1, int(ih * scale))))
        self.photo = ImageTk.PhotoImage(shown)
        c.create_image(ox, oy, anchor="nw", image=self.photo)
        if self.mode == "atlas":
            self._draw_atlas_markers()
        else:
            self._draw_region_overlays()

    def _canvas_xy(self, fx, fy):
        scale, ox, oy, iw, ih = self._view
        return ox + fx * iw * scale, oy + fy * ih * scale

    def _draw_atlas_markers(self):
        self._hits = []
        for stem, reg in self.regions.items():
            fx, fy = self.raster.xy_to_frac(*lonlat_to_xy(*reg.lonlat))
            x, y = self._canvas_xy(fx, fy)
            self.canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#ffb300", outline="white", width=2)
            if reg is not self.focus:                       # the focused region gets a bold label below
                tag = " [gNB]" if stem in self.gnb_defaults else ""
                self.canvas.create_text(x + 10, y - 10, anchor="sw", text=reg.label + tag, fill="#ffe082")
            self._hits.append((x, y, stem))
        for sid, name, lon, lat in self.missing:                    # no terrain tile: grey
            fx, fy = self.raster.xy_to_frac(*lonlat_to_xy(lon, lat))
            x, y = self._canvas_xy(fx, fy)
            self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, outline="#9e9e9e", width=2)
            self.canvas.create_text(x + 8, y - 8, anchor="sw", text=f"{sid} (no tile)", fill="#9e9e9e")
            self._hits.append((x, y, ("missing", name)))
        self._draw_highlight(self.canvas, self.focus, self._canvas_xy,
                             (self.canvas.winfo_width(), self.canvas.winfo_height()), 13)

    def _draw_highlight(self, canvas, region, to_canvas, size, font_size):
        """Footprint box, ring and name of `region` on an atlas-based canvas."""
        if region is None or self.pole is None:
            return
        fx, fy = self.pole.xy_to_frac(*lonlat_to_xy(*region.lonlat))
        cx, cy = to_canvas(fx, fy)
        tile = self.rasters.get(region.dem_path)
        if tile:                                            # true footprint (axis-aligned in the projection)
            ax, ay = to_canvas(*self.pole.xy_to_frac(tile.x0, tile.y0))
            bx, by = to_canvas(*self.pole.xy_to_frac(tile.x0 + tile.width * tile.dx,
                                                     tile.y0 - tile.height * tile.dy))
            canvas.create_rectangle(ax, ay, bx, by, outline="#ff1744", width=2)
        canvas.create_oval(cx - 11, cy - 11, cx + 11, cy + 11, outline="#ff1744", width=2)
        w, h = size
        tx = min(max(cx, w * 0.2), w * 0.8)
        above = cy > 36
        ty, anchor = (cy - 15, "s") if above else (cy + 15, "n")
        font = ("TkDefaultFont", font_size, "bold")
        canvas.create_text(tx + 1, ty + 1, text=region.label, anchor=anchor, fill="black", font=font)
        canvas.create_text(tx, ty, text=region.label, anchor=anchor, fill="#ffeb3b", font=font)

    def draw_minimap(self):
        m = self.mini
        m.delete("all")
        if self.pole is None or self.mini_photo is None:
            return
        m.create_image(0, 0, anchor="nw", image=self.mini_photo)
        to_canvas = lambda fx, fy: (fx * MINI_PX, fy * MINI_PX)
        for reg in self.regions.values():
            x, y = to_canvas(*self.pole.xy_to_frac(*lonlat_to_xy(*reg.lonlat)))
            m.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#ffb300", outline="")
        self._draw_highlight(m, self.focus, to_canvas, (MINI_PX, MINI_PX), 10)

    def _draw_region_overlays(self):
        if self.show_cands.get():
            colors = {"ridge": "#ff9800", "landing_site": "#66bb6a"}
            for x, y, cls in self.candidates:
                fx, fy = self.raster.xy_to_frac(x, y)
                if 0 <= fx <= 1 and 0 <= fy <= 1:
                    cx, cy = self._canvas_xy(fx, fy)
                    self.canvas.create_oval(cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5,
                                            fill=colors.get(cls, "#bbbbbb"), outline="")
        for who, pt in self.points.items():
            if pt:
                cx, cy = self._canvas_xy(*pt)
                col = MARKER_COLORS[who]
                self.canvas.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill=col, outline="white", width=2)
                self.canvas.create_text(cx + 12, cy - 12, text=who, fill=col, font=("TkDefaultFont", 11, "bold"))

    # ---- clicks --------------------------------------------------------------
    def _frac(self, event):
        scale, ox, oy, iw, ih = self._view
        return (event.x - ox) / (iw * scale), (event.y - oy) / (ih * scale)

    def on_press(self, event):
        if self.raster is None:
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
        if self.mode == "region":
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

    def update_readout(self):
        g, u = self.lonlat("gNB"), self.lonlat("UE")
        for who, ll in (("gNB", g), ("UE", u)):
            self.readout[who].set(f"{who}: lon {ll[0]:.5f}, lat {ll[1]:.5f}" if ll else
                                  (f"{who}: not placed" if self.mode == "region" else ""))
        self.readout["dist"].set(f"Separation: {distance_m(g, u):.0f} m" if g and u else "")
        if g:                                              # keep the lon/lat boxes in step with the marker
            self.gnb_lon_var.set(f"{g[0]:.6f}")
            self.gnb_lat_var.set(f"{g[1]:.6f}")

    # ---- default gNB per region ---------------------------------------------
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

    def place_gnb_from_entries(self):
        """Put the gNB at the typed lon/lat. Returns True on success."""
        if self.mode != "region":
            messagebox.showinfo("Open a region", "Open a region first.")
            return False
        try:
            lon, lat = float(self.gnb_lon_var.get()), float(self.gnb_lat_var.get())
        except ValueError:
            messagebox.showwarning("Invalid coordinates", "Longitude and latitude must be numbers.")
            return False
        fx, fy = self.raster.xy_to_frac(*lonlat_to_xy(lon, lat))
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            messagebox.showwarning("Outside the tile", "That position is outside this region's map.")
            return False
        self.points["gNB"] = (fx, fy)
        self.update_readout()
        self.redraw()
        return True

    def save_default(self):
        if not self.place_gnb_from_entries():
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

    def clear_points(self):
        self.points = {"gNB": None, "UE": None}
        self.update_readout()
        self.redraw()

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
    PlannerApp(regions, missing, load_candidates()).mainloop()


if __name__ == "__main__":
    main()
