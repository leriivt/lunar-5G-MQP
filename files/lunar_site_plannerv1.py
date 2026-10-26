"""Lunar Site Planner: pick a site, click to place gNB and UE, export OAI BICTR configs.

Run:  python lunar_site_planner.py        (requires: pip install pillow)

Layout of this file (read top to bottom):
  1. Settings       - constants you may want to change
  2. Site catalog   - loads sites/sites.csv (or sites.json)  (F1, F2, F3)
  3. Geometry       - pixel <-> lon/lat, distance (F5, F6)
  4. Config export  - fills the four BICTR model entries (F7, F8)
  5. GUI            - the tkinter window (F4, F9, F10)
"""
import csv
import json
import math
import os
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

# ----------------------------------------------------------------------------
# 1. SETTINGS
# ----------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SITES_DIR = os.path.join(APP_DIR, "terrain")           # holds sites.json, PNGs, .bdem files
BODY_RADIUS_M = 1_737_400.0                          # Moon, matches bictr_body_radius default
TILE_HALF_WIDTH_M = 10_000.0                        # tile = +/-10 km around the site centre
DEFAULT_HEIGHT_M = 2.0                               # matches bictr_*_height example
GNB_CONF = "gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf"
UE_CONF = "ue.bictr.conf"
BLOCK_GNB_SIDE = "rfsimu_channel_enB0"               # TX = gNB, RX = UE
BLOCK_UE_SIDE = "rfsimu_channel_ue0"                 # TX = UE,  RX = gNB (swapped)
MARKER_COLORS = {"gNB": "#e53935", "UE": "#1e88e5"}


# ----------------------------------------------------------------------------
# 2. SITE CATALOG
# ----------------------------------------------------------------------------
@dataclass
class Site:
    """One terrain tile: a PNG, its .bdem, and the lon/lat box the PNG covers (north-up)."""
    name: str
    png: str
    bdem: str
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float
    center_lon: float = None     # optional; used only as a sanity check on the bounds
    center_lat: float = None

    def center_inside_bounds(self):
        if self.center_lon is None or self.center_lat is None:
            return True
        return (self.lon_min <= self.center_lon <= self.lon_max
                and self.lat_min <= self.center_lat <= self.lat_max)

    @property
    def png_path(self):
        return os.path.join(SITES_DIR, self.png)

    @property
    def bdem_path(self):
        return os.path.abspath(os.path.join(SITES_DIR, self.bdem))


# Accepted CSV header names (case, spaces and dashes are ignored). Add your own here
# if your file uses different headers.
CSV_ALIASES = {
    "id":         ["id", "site_id", "site_number", "number", "no", "site_no"],
    "name":       ["name", "site", "site_name", "region", "region_name"],
    "png":        ["png", "png_file", "image", "image_file"],
    "bdem":       ["bdem", "bdem_file", "dem", "dem_file"],
    "lon_min":    ["lon_min", "min_lon", "west", "west_lon", "lon_west", "left_lon", "lon_left"],
    "lon_max":    ["lon_max", "max_lon", "east", "east_lon", "lon_east", "right_lon", "lon_right"],
    "lat_min":    ["lat_min", "min_lat", "south", "south_lat", "lat_south", "bottom_lat", "lat_bottom"],
    "lat_max":    ["lat_max", "max_lat", "north", "north_lat", "lat_north", "top_lat", "lat_top"],
    "center_lon": ["center_lon", "centre_lon", "lon_center", "lon_centre", "lon", "longitude",
                   "lon_deg", "longitude_deg", "center_longitude"],
    "center_lat": ["center_lat", "centre_lat", "lat_center", "lat_centre", "lat", "latitude",
                   "lat_deg", "latitude_deg", "center_latitude"],
}
EDGE_FIELDS = ["lon_min", "lon_max", "lat_min", "lat_max"]


def _norm(header):
    return re.sub(r"[\s\-]+", "_", header.strip().lower())


def _num(text):
    """Parse a number, tolerating unicode minus signs and a trailing degree sign."""
    return float(text.strip().replace("\u2212", "-").replace("\u00b0", ""))


def tile_bounds_from_centre(lon, lat, half_width_m=TILE_HALF_WIDTH_M):
    """(lon_min, lon_max, lat_min, lat_max) of the +/-half_width_m box around a centre.
    Latitude: a fixed arc. Longitude: the same distance measured at the centre's latitude,
    so tiles near the pole span wide longitudes (Connecting Ridge comes out at ~70 deg)."""
    lat_half = math.degrees(half_width_m / BODY_RADIUS_M)
    lon_half = math.degrees(half_width_m / (BODY_RADIUS_M * math.cos(math.radians(lat))))
    return lon - lon_half, lon + lon_half, lat - lat_half, lat + lat_half


def find_site_file(ident, ext):
    """Find the file for a site in sites/. For id '01' and ext 'png' this accepts
    01.png, 1.png, site01.png, site_01_anything.png (case-insensitive). If nothing
    matches, returns '<id>.<ext>' so the missing file is reported by the app."""
    default = f"{ident}.{ext}"
    if not os.path.isdir(SITES_DIR):
        return default
    if ident.isdigit():
        pattern = rf"(site[_\- ]?)?0*{int(ident)}(?!\d).*\.{ext}"
    else:
        pattern = re.escape(default)
    for fname in sorted(os.listdir(SITES_DIR)):
        if re.fullmatch(pattern, fname, re.IGNORECASE):
            return fname
    return default


def load_sites_csv(path):
    """Read the site table from a CSV; each row is one site.
    Needs EITHER the four edge columns (lon_min, lon_max, lat_min, lat_max)
    OR a centre (lat_deg/lon_deg), from which a +/-10 km tile box is computed.
    Optional: id, name, png, bdem. Other columns (e.g. list, coord_source) are ignored.
    If png/bdem columns are absent, files are found in sites/ by id (see find_site_file)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = {_norm(h): h for h in (reader.fieldnames or [])}
        col = {}
        for field, aliases in CSV_ALIASES.items():
            for a in aliases:
                if a in headers:
                    col[field] = headers[a]
                    break
        have_edges = all(k in col for k in EDGE_FIELDS)
        if not have_edges and not ("center_lon" in col and "center_lat" in col):
            raise ValueError("CSV needs either edge columns (lon_min, lon_max, lat_min, lat_max) "
                             "or centre columns (lat_deg, lon_deg).\n"
                             f"Headers found: {', '.join(reader.fieldnames or [])}\n"
                             "Rename the headers or add aliases to CSV_ALIASES.")
        sites = []
        for n, row in enumerate(reader, start=2):          # row 1 is the header
            get = lambda k: (row[col[k]] or "").strip() if k in col else ""
            ident, label = get("id"), get("name")
            stem = ident or label
            if not stem:
                raise ValueError(f"Row {n}: needs an id or a name.")
            try:
                centre = {k: (_num(get(k)) if get(k) else None) for k in ("center_lon", "center_lat")}
                edges = [_num(get(k)) for k in EDGE_FIELDS] if have_edges else None
            except ValueError:
                raise ValueError(f"Row {n} ({stem}): a longitude/latitude value is not a number.")
            if edges is None:
                if None in centre.values():
                    raise ValueError(f"Row {n} ({stem}): missing centre latitude/longitude.")
                edges = tile_bounds_from_centre(centre["center_lon"], centre["center_lat"])
            bounds = dict(zip(EDGE_FIELDS, edges))
            if bounds["lon_min"] < -180 or bounds["lon_max"] > 180 \
                    or bounds["lat_min"] < -90 or bounds["lat_max"] > 90:
                raise ValueError(f"Row {n} ({stem}): the tile crosses the +/-180 deg seam or the "
                                 "pole, which bictr_channel.c cannot handle.")
            sites.append(Site(name=f"{ident} {label}".strip(),
                              png=get("png") or find_site_file(stem, "png"),
                              bdem=get("bdem") or find_site_file(stem, "bdem"),
                              **bounds, **centre))
    return sites


def load_sites(path=None):
    """Load the catalog: sites/sites.csv if present, otherwise sites/sites.json.
    To add a site, add a PNG, a .bdem and one row; no code changes."""
    csv_path = path or os.path.join(SITES_DIR, "sites.csv")
    if os.path.exists(csv_path):
        return load_sites_csv(csv_path)
    with open(os.path.join(SITES_DIR, "sites.json"), encoding="utf-8") as f:
        return [Site(**e) for e in json.load(f)["sites"]]


# ----------------------------------------------------------------------------
# 3. GEOMETRY
# ----------------------------------------------------------------------------
def pixel_to_lonlat(px, py, img_w, img_h, site):
    """Image pixel -> (lon, lat) in degrees. Image is a north-up lon/lat box."""
    lon = site.lon_min + (px / img_w) * (site.lon_max - site.lon_min)
    lat = site.lat_max - (py / img_h) * (site.lat_max - site.lat_min)
    return lon, lat


def distance_m(a, b):
    """Great-circle (haversine) distance between two (lon, lat) points, in metres."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * BODY_RADIUS_M * math.asin(math.sqrt(h))


# ----------------------------------------------------------------------------
# 4. CONFIG EXPORT
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
    """Overwrite `key = value;` lines inside `block` of a template. Returns None if the
    block or any key is missing, so the caller can fall back to a plain snippet."""
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


def run_folder_name(site_name, now=None):
    """Folder name like '01_Faustini_Rim_A_2026-10-23_14-30-05' (no characters that are
    illegal on Windows)."""
    now = now or datetime.now()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", site_name).strip("_")
    return f"{slug}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"


def make_run_folder(parent, site_name):
    """Create a new, uniquely named, date/time-stamped folder inside `parent`."""
    base = os.path.join(parent, run_folder_name(site_name))
    path, n = base, 1
    while os.path.exists(path):          # two exports in the same second
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
# 5. GUI
# ----------------------------------------------------------------------------
class PlannerApp(tk.Tk):
    def __init__(self, sites):
        super().__init__()
        self.title("Lunar Site Planner")
        self.geometry("1100x700")
        self.sites = {s.name: s for s in sites}
        self.site = None
        self.image = None            # PIL image of the current site
        self.photo = None            # Tk image (kept so it isn't garbage collected)
        self.points = {"gNB": None, "UE": None}   # image-pixel coordinates
        self.template_dir = ""
        self._view = (1.0, 0, 0)     # scale, x offset, y offset of the drawn image
        self._build_widgets()
        if sites:
            self.site_var.set(sites[0].name)
            self.on_site_selected()

    # ---- widget construction -------------------------------------------------
    def _build_widgets(self):
        panel = ttk.Frame(self, padding=10)
        panel.pack(side="left", fill="y")

        ttk.Label(panel, text="1. Site").pack(anchor="w")
        self.site_var = tk.StringVar()
        box = ttk.Combobox(panel, textvariable=self.site_var, state="readonly",
                           values=list(self.sites), width=32)
        box.pack(fill="x", pady=(0, 10))
        box.bind("<<ComboboxSelected>>", lambda e: self.on_site_selected())

        ttk.Label(panel, text="2. Place on image (click or drag)").pack(anchor="w")
        self.active = tk.StringVar(value="gNB")
        for who in ("gNB", "UE"):
            ttk.Radiobutton(panel, text=who, value=who, variable=self.active).pack(anchor="w")

        ttk.Label(panel, text="3. Antenna heights (m)").pack(anchor="w", pady=(10, 0))
        self.height_vars = {w: tk.StringVar(value=str(DEFAULT_HEIGHT_M)) for w in ("gNB", "UE")}
        for who, var in self.height_vars.items():
            row = ttk.Frame(panel)
            row.pack(fill="x")
            ttk.Label(row, text=who, width=5).pack(side="left")
            ttk.Entry(row, textvariable=var, width=8).pack(side="left")

        ttk.Label(panel, text="Readout").pack(anchor="w", pady=(10, 0))
        self.readout = {k: tk.StringVar(value="not placed") for k in ("gNB", "UE", "dist")}
        ttk.Label(panel, textvariable=self.readout["gNB"]).pack(anchor="w")
        ttk.Label(panel, textvariable=self.readout["UE"]).pack(anchor="w")
        ttk.Label(panel, textvariable=self.readout["dist"]).pack(anchor="w")

        ttk.Label(panel, text="4. Export").pack(anchor="w", pady=(10, 0))
        ttk.Button(panel, text="Set OAI CONF template folder (optional)",
                   command=self.choose_template_dir).pack(fill="x")
        ttk.Button(panel, text="Export gNB + UE configs...",
                   command=self.export).pack(fill="x", pady=4)
        ttk.Button(panel, text="Clear markers", command=self.clear_points).pack(fill="x")

        self.status = tk.StringVar(value="Choose a site to begin.")
        ttk.Label(panel, textvariable=self.status, wraplength=250, foreground="#555").pack(
            anchor="w", pady=10)

        self.canvas = tk.Canvas(self, bg="#202020", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_click)

    # ---- site selection (F1-F3) ----------------------------------------------
    def on_site_selected(self):
        self.site = self.sites[self.site_var.get()]
        try:
            self.image = Image.open(self.site.png_path)
        except OSError as err:
            self.image = None
            messagebox.showerror("Image error", f"Cannot open {self.site.png_path}\n{err}")
        self.clear_points()
        warn = "" if os.path.exists(self.site.bdem_path) else "  WARNING: .bdem file not found."
        if not self.site.center_inside_bounds():
            warn += "  WARNING: site centre is outside its lon/lat bounds; check the CSV."
        self.status.set(f"Loaded {self.site.name}.{warn}")

    # ---- drawing -------------------------------------------------------------
    def redraw(self):
        self.canvas.delete("all")
        if self.image is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        iw, ih = self.image.size
        scale = min(cw / iw, ch / ih)
        ox, oy = (cw - iw * scale) / 2, (ch - ih * scale) / 2
        self._view = (scale, ox, oy)
        resized = self.image.resize((max(1, int(iw * scale)), max(1, int(ih * scale))))
        self.photo = ImageTk.PhotoImage(resized)
        self.canvas.create_image(ox, oy, anchor="nw", image=self.photo)
        for who, pt in self.points.items():
            if pt:
                x, y = ox + pt[0] * scale, oy + pt[1] * scale
                c = MARKER_COLORS[who]
                self.canvas.create_oval(x - 7, y - 7, x + 7, y + 7, fill=c, outline="white", width=2)
                self.canvas.create_text(x + 12, y - 12, text=who, fill=c, font=("TkDefaultFont", 11, "bold"))

    # ---- placement (F4-F6, F9) -----------------------------------------------
    def on_click(self, event):
        if self.image is None:
            return
        scale, ox, oy = self._view
        px, py = (event.x - ox) / scale, (event.y - oy) / scale
        iw, ih = self.image.size
        if not (0 <= px <= iw and 0 <= py <= ih):     # F6: stay inside the DEM bounds
            self.status.set("Click inside the image: points must lie within the terrain tile.")
            return
        self.points[self.active.get()] = (px, py)
        self.update_readout()
        self.redraw()

    def lonlat(self, who):
        pt = self.points[who]
        if pt is None:
            return None
        return pixel_to_lonlat(pt[0], pt[1], *self.image.size, self.site)

    def update_readout(self):
        for who in ("gNB", "UE"):
            ll = self.lonlat(who)
            self.readout[who].set(f"{who}: lon {ll[0]:.5f}, lat {ll[1]:.5f}" if ll else f"{who}: not placed")
        g, u = self.lonlat("gNB"), self.lonlat("UE")
        self.readout["dist"].set(f"Separation: {distance_m(g, u):.0f} m" if g and u else "Separation: -")

    def clear_points(self):
        self.points = {"gNB": None, "UE": None}
        self.update_readout()
        self.redraw()

    # ---- export (F7, F8, F10) ------------------------------------------------
    def choose_template_dir(self):
        folder = filedialog.askdirectory(title="OAI targets/PROJECTS/GENERIC-NR-5GC/CONF folder")
        if folder:
            self.template_dir = folder
            self.status.set(f"Templates: {folder}")

    def export(self):
        if self.site is None or not all(self.points.values()):
            messagebox.showwarning("Not ready", "Select a site and place both the gNB and the UE.")
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
        if not os.path.exists(self.site.bdem_path):
            if not messagebox.askyesno(
                    "Missing .bdem",
                    f"{self.site.bdem_path} was not found.\nThe simulator would fall back to flat "
                    "terrain. Export anyway?"):
                return
        out_dir = filedialog.askdirectory(title="Choose output folder (a dated subfolder is created)")
        if not out_dir:
            return
        run_dir = make_run_folder(out_dir, self.site.name)
        files = export_configs(run_dir, self.template_dir, g, u,
                               heights["gNB"], heights["UE"], self.site.bdem_path)
        self.status.set(f"Exported to:\n{run_dir}")


def main():
    try:
        sites = load_sites()
    except (OSError, KeyError, ValueError, TypeError, csv.Error) as err:
        messagebox.showerror("Site catalog", f"Could not read the site list (sites/sites.csv):\n{err}")
        return
    PlannerApp(sites).mainloop()


if __name__ == "__main__":
    main()
