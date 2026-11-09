"""Lunar Site Planner v2 (PyQt6): south-pole atlas -> click a region -> place gNB and UE -> export BICTR configs.

Run:  python qt_lunar_site_planner.py     (needs: pip install pillow numpy PyQt6)

Same features as lunar_site_planner.py; only the GUI toolkit differs (PyQt6 instead of tkinter).

Sections (read top to bottom):
  1. Settings        - paths, defaults and the colour THEME
  2. Map projection  - polar stereographic x/y <-> longitude/latitude
  3. Rasters         - reads a GeoTIFF DEM and renders a shaded-relief picture
  4. Catalog         - sites.csv -> clickable regions; .bdem lookup; candidate masts;
                       per-region default gNB locations (gnb_defaults.csv)
  5. Config export   - fills the four BICTR model entries, dated export folders
  6. GUI             - the PyQt6 window (atlas screen + region screen)
"""
import csv
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

import numpy as np
from PIL import Image
from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontMetrics, QFontMetricsF, QImage, QPainter, QPalette, QPen,
                         QPolygonF)
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
                             QVBoxLayout, QWidget)

from geo_math import *


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
TEMPLATE_DIR = os.path.join(APP_DIR, "Templates")                       # OAI gNB/UE .conf templates filled on export
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
COVERAGE_MAX_PX = 450                    # UE LOS coverage is worked out on a grid of at most this many cells per side
COVERAGE_OPACITY = 0.35                  # how solid the LOS coverage tint is (0 to 1)
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
    "scale": "#000000",              # map scale bar and its label (drawn straight on the map, no plate)
    "psr": "#29b6f6",                # tint for permanently shadowed regions
    "link": "#ffeb3b",               # gNB-UE line when line of sight cannot be judged
    "los_clear": "#00e676", "los_blocked": "#ff5252",   # gNB-UE line: line of sight clear / blocked
    "coverage": "#00e676",           # tint where a UE would have line of sight to the gNB
    "terrain_fill": "#808080", "terrain_line": "#d7ccc8",   # cross-section terrain
}




from raster import *
from catalog import *
















def scale_bar(m_per_px, target_px=110):
    """(bar length in pixels, label) for a scale bar roughly target_px wide (1, 2 or 5 x 10^n)."""
    raw = m_per_px * target_px
    base = 10 ** math.floor(math.log10(raw))
    length = max(k for k in (1, 2, 5, 10) if k * base <= raw) * base
    return length / m_per_px, (f"{length:g} m" if length < 1000 else f"{length / 1000:g} km")



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
# 6. GUI  (PyQt6; the map and minimap are painted with QPainter on plain widgets)
# ----------------------------------------------------------------------------
ATLAS_LABEL = "South pole atlas"
NODES = ("gNB", "UE")


def pil_to_qimage(img):
    """Pillow picture -> QImage (a copy, so it does not depend on Pillow's buffer)."""
    if img.mode == "L":
        fmt, depth = QImage.Format.Format_Grayscale8, 1
    else:
        img, fmt, depth = img.convert("RGBA"), QImage.Format.Format_RGBA8888, 4
    return QImage(img.tobytes(), img.width, img.height, img.width * depth, fmt).copy()


def _pen(colour, width=1, dash=None):
    """Pen with flat caps; `dash` = (on, off) lengths in pixels, as on a tk canvas."""
    pen = QPen(QColor(colour))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    if dash:
        pen.setDashPattern([d / width for d in dash])
    return pen


def _shape_style(p, fill, outline, width):
    p.setPen(_pen(outline, width) if outline else Qt.PenStyle.NoPen)
    p.setBrush(QColor(fill) if fill else Qt.BrushStyle.NoBrush)


def draw_oval(p, x1, y1, x2, y2, fill=None, outline=None, width=1):
    _shape_style(p, fill, outline, width)
    p.drawEllipse(QRectF(x1, y1, x2 - x1, y2 - y1))


def draw_rect(p, x1, y1, x2, y2, fill=None, outline=None, width=1):
    _shape_style(p, fill, outline, width)
    p.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))


def draw_line(p, points, colour, width=1, dash=None):
    """Polyline through [(x, y), ...]."""
    p.setPen(_pen(colour, width, dash))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))


def draw_polygon(p, points, fill):
    _shape_style(p, fill, None, 1)
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))


def anchored_rect(w, h, x, y, anchor):
    """w x h rectangle placed at (x, y) by a tk-style anchor: n, s, e, w, nw, ..., or center."""
    a = "" if anchor == "center" else anchor
    left = x if "w" in a else x - w if "e" in a else x - w / 2
    top = y if "n" in a else y - h if "s" in a else y - h / 2
    return QRectF(left, top, w, h)


def apply_theme(app):
    """Applies THEME (section 1) to the whole application. Returns (font family, size)."""
    t = THEME
    app.setStyle("Fusion")                        # 'Fusion' honours colours on Windows, macOS and Linux
    palette = QPalette()                          # fixed light palette, whatever the desktop theme is
    for role, key in ((QPalette.ColorRole.Window, "panel_bg"), (QPalette.ColorRole.WindowText, "text"),
                      (QPalette.ColorRole.Base, "entry_bg"), (QPalette.ColorRole.Text, "text"),
                      (QPalette.ColorRole.Button, "button_bg"), (QPalette.ColorRole.ButtonText, "text")):
        palette.setColor(role, QColor(t[key]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t["disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["disabled"]))
    app.setPalette(palette)
    family = app.font().family()
    app.setFont(QFont(family, t["font_size"]))
    app.setStyleSheet(f"""
        QWidget#panel {{ background: {t['panel_bg']}; }}
        QWidget#panel QLabel {{ color: {t['text']}; background: transparent; }}
        QLabel#muted {{ color: {t['muted']}; }}
        QFrame#controls {{ background: {t['panel_bg']}; border: 1px solid {t['border']}; }}
        QFrame#controls QLabel, QFrame#controls QCheckBox {{ color: {t['text']}; background: transparent; }}
        QGroupBox {{ border: 1px solid {t['border']}; margin-top: 1.3em; font-weight: bold; }}
        QGroupBox QWidget {{ font-weight: normal; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {t['text']}; }}
        QGroupBox#gNB::title {{ color: {t['gnb']}; }}
        QGroupBox#UE::title {{ color: {t['ue']}; }}
        QPushButton {{ background: {t['button_bg']}; color: {t['text']}; border: 1px solid {t['border']};
                       padding: 4px; }}
        QPushButton:hover, QPushButton:pressed {{ background: {t['button_active']}; }}
        QLineEdit {{ background: {t['entry_bg']}; color: {t['text']}; border: 1px solid {t['border']};
                     padding: 1px; }}
        QComboBox {{ background: {t['entry_bg']}; color: {t['text']}; border: 1px solid {t['border']};
                     padding: 2px 4px; }}
        QComboBox QAbstractItemView {{ background: {t['entry_bg']}; color: {t['text']}; }}
    """)
    return family, t["font_size"]


class Canvas(QWidget):
    """A drawing surface (like a tk Canvas): `paint(painter)` draws it; mouse events, with tk-style
    integer .x/.y, go to `owner` (on_press, on_drag, on_release, on_pan_*, on_mousewheel_zoom)."""

    def __init__(self, paint, owner=None):
        super().__init__()
        self._paint, self._owner = paint, owner

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME["canvas_bg"]))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint(p)
        p.end()

    @staticmethod
    def _xy(event):
        pos = event.position()
        return SimpleNamespace(x=int(pos.x()), y=int(pos.y()))

    def mousePressEvent(self, event):
        if self._owner is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner.on_press(self._xy(event))
        elif event.button() == Qt.MouseButton.RightButton:
            self._owner.on_pan_press(self._xy(event))

    def mouseMoveEvent(self, event):
        if self._owner is None:
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._owner.on_drag(self._xy(event))
        if event.buttons() & Qt.MouseButton.RightButton:
            self._owner.on_pan_drag(self._xy(event))

    def mouseReleaseEvent(self, event):
        if self._owner is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner.on_release(self._xy(event))
        elif event.button() == Qt.MouseButton.RightButton:
            self._owner.on_pan_release(self._xy(event))

    def wheelEvent(self, event):
        dy = event.angleDelta().y()
        if self._owner is not None and dy:
            self._owner.on_mousewheel_zoom(self._xy(event), 1.1 if dy > 0 else 0.9)

    def resizeEvent(self, event):
        if self._owner is not None:
            self._owner.redraw()


class PlannerApp(QWidget):
    def __init__(self, regions, missing, candidates):
        super().__init__()
        self.setWindowTitle("Lunar Site Planner")
        self.resize(1260, 880)
        self.setMinimumSize(800, 600)
        self.font_family, self.font_size = apply_theme(QApplication.instance())
        self.regions, self.missing, self.candidates = regions, missing, candidates
        self.rasters = {}               # cache: path -> Raster
        self.mode = "atlas"             # "atlas" or "region"
        self._link = None               # gNB-UE terrain profile and line-of-sight result
        self._inset_rect = None         # screen rectangle of the cross-section inset
        self._inset_size = None         # user-selected (width, height) for the inset
        self._inset_position = None     # user-selected top-left position; None uses top-right default
        self._inset_handle = None       # top-left resize handle
        self._inset_drag = None
        self._map_zoom = 1.0            # zoom multiplier from the map's fitted size
        self._map_pan = (0.0, 0.0)
        self._map_pan_drag = None
        self.region = None
        self.raster = None
        self.pole = None                # the atlas raster (kept while a region is open)
        self.focus = None               # region highlighted on the atlas (last one opened)
        self.mini_photo = None          # QImage of the atlas minimap
        self.gnb_defaults = load_gnb_defaults()
        self._topo_cache = {}           # view key (region stem or None) -> (overlay image or None, path)
        self._psr_cache = {}            # view key -> PsrLayer or None
        self._bg_key = self._bg_img = None   # cached map background (map + overlay)
        self._bg_qkey = self._bg_qimage = None   # the same background converted for Qt
        self._cov_key = self._coverage = None    # UE LOS coverage: (QImage, fraction in view) or None
        self._legend = ([], None)       # legend items and scale bar, worked out in redraw()
        self.points = {"gNB": None, "UE": None}      # (fx, fy) fractions of the region picture
        self._view = (1.0, 0, 0, 1, 1)               # scale, x offset, y offset, picture w, h
        self._hits = []                              # clickable atlas markers
        self._build_widgets()
        self.show_atlas()

    # ---- widgets -------------------------------------------------------------
    def _font(self, size=None, bold=False):
        font = QFont(self.font_family, size or self.font_size)
        font.setBold(bold)
        return font

    def _chars(self, n):
        """Width of an entry box `n` characters wide (like tk's width=n)."""
        return QFontMetrics(self._font()).horizontalAdvance("0") * n + 8

    def _button(self, text, command):
        button = QPushButton(text)
        button.clicked.connect(lambda _checked=False: command())
        return button

    def _check(self, text, command, checked=False, enabled=True):
        box = QCheckBox(text)
        box.setChecked(checked)
        box.setEnabled(enabled)
        box.clicked.connect(lambda _checked=False: command())
        return box

    def _bold_label(self, text):
        label = QLabel(text)
        label.setFont(self._font(bold=True))
        return label

    def _build_widgets(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        panel = QWidget(objectName="panel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        panel.setFixedWidth(350)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(4)
        outer.addWidget(panel)

        self.mini = Canvas(self.paint_minimap)
        self.mini.setFixedSize(MINI_PX + 2, MINI_PX + 2)     # 1 px border on each side
        lay.addWidget(self.mini, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(8)

        lay.addWidget(self._bold_label("Region"))
        self.labels = {r.label: stem for stem, r in self.regions.items()}
        self.choice = QComboBox()
        self.choice.addItems([ATLAS_LABEL] + sorted(self.labels))
        self.choice.activated.connect(lambda _index: self.on_choice())
        lay.addWidget(self.choice)
        lay.addWidget(self._button("< Back to atlas", self.show_atlas))
        lay.addSpacing(8)

        # one group per node: pick it, then click the map OR type its coordinates
        self.radios, self.lon_vars, self.lat_vars, self.height_vars = {}, {}, {}, {}
        self._entry_owner = {}                       # lon/lat entry -> node it belongs to
        self._radio_group = QButtonGroup(self)
        for who in NODES:
            group = QGroupBox(f" {who} ", objectName=who)
            g = QVBoxLayout(group)
            g.setContentsMargins(6, 6, 6, 6)
            top = QHBoxLayout()
            radio = QRadioButton("Place by clicking the map")
            self._radio_group.addButton(radio)
            self.radios[who] = radio
            top.addWidget(radio)
            top.addWidget(QLabel("  height (m)"))
            height = QLineEdit(str(GNB_HEIGHT_M if who == "gNB" else UE_HEIGHT_M))
            height.setFixedWidth(self._chars(6))
            height.textChanged.connect(lambda _text: self.redraw())    # LOS line and coverage follow the heights
            self.height_vars[who] = height
            top.addWidget(height)
            top.addStretch()
            g.addLayout(top)
            row = QHBoxLayout()
            for text, store in (("lon", self.lon_vars), ("lat", self.lat_vars)):
                row.addWidget(QLabel(text))
                entry = QLineEdit()
                entry.setFixedWidth(self._chars(11))
                store[who] = entry
                self._entry_owner[entry] = who
                entry.installEventFilter(self)       # focus -> this node becomes the active one
                entry.returnPressed.connect(lambda w=who: self.place_from_entries(w))
                row.addWidget(entry)
            row.addWidget(self._button("Place", lambda w=who: self.place_from_entries(w)))
            row.addStretch()
            g.addLayout(row)
            if who == "gNB":
                g.addWidget(self._button(f"Place optimal gNB ({OPTIMAL_GNB_FREQ_GHZ:g} GHz)",
                                         self.place_optimal_gnb))
            lay.addWidget(group)
        self._set_active("gNB")

        group = QGroupBox(" gNB default for this region ")
        g = QHBoxLayout(group)
        g.setContentsMargins(6, 6, 6, 6)
        g.addWidget(self._button("Save gNB as default", self.save_default))
        g.addWidget(self._button("Clear default", self.clear_default))
        g.addStretch()
        lay.addWidget(group)

        lay.addSpacing(6)
        self.sep_var = self._bold_label("Separation: -")
        lay.addWidget(self.sep_var)
        lay.addWidget(self._button("Export gNB + UE configs...", self.export))
        lay.addWidget(self._button("Clear markers", self.clear_points))

        self.status = QLabel(objectName="muted")
        self.status.setWordWrap(True)
        self.status.setMaximumWidth(330)
        lay.addSpacing(8)
        lay.addWidget(self.status)
        lay.addStretch()

        self.canvas = Canvas(self.paint_map, owner=self)
        outer.addWidget(self.canvas, 1)

        # all overlay controls live in one box in the top-right corner of the map (all on at startup)
        self.controls = QFrame(self.canvas, objectName="controls")
        self.controls.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        box = QVBoxLayout(self.controls)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(2)
        box.addWidget(self._bold_label("Overlays"))
        self.topo_opacity = TOPO_OPACITY
        self.show_cands = self._check("Candidate masts", self.redraw, checked=bool(self.candidates),
                                      enabled=bool(self.candidates))
        self.show_grid = self._check("Lon/lat grid", self.redraw, checked=True)
        self.show_topo = self._check("Topographic overlay", self.on_topo_toggle, checked=True)
        self.show_psr = self._check("Permanently shadowed regions", self.on_psr_toggle, checked=True)
        self.show_inset = self._check("Cross-section inset", self.redraw, checked=True)
        self.show_coverage = self._check("UE LOS coverage from gNB", self.redraw, checked=True)
        for check in (self.show_cands, self.show_grid, self.show_topo, self.show_psr, self.show_inset,
                      self.show_coverage):
            box.addWidget(check)
        self.controls.adjustSize()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn and obj in self._entry_owner:
            self._set_active(self._entry_owner[obj])
        return super().eventFilter(obj, event)

    def _active(self):
        return next(who for who, radio in self.radios.items() if radio.isChecked())

    def _set_active(self, who):
        self.radios[who].setChecked(True)

    def _set_status(self, text, now=False):
        self.status.setText(text)
        if now:                                      # show it before a slow load starts
            self.status.repaint()

    # ---- screens -------------------------------------------------------------
    def _load(self, path):
        if path not in self.rasters:
            self._set_status("Loading map...", now=True)
            self.rasters[path] = Raster(path)
        return self.rasters[path]

    def show_atlas(self):
        self.mode, self.region = "atlas", None
        self._map_zoom = 1.0
        self._map_pan = (0.0, 0.0)
        self.choice.setCurrentText(ATLAS_LABEL)
        self.points = {"gNB": None, "UE": None}
        try:
            self.raster = self.pole = self._load(POLE_DEM)
            self.mini_photo = pil_to_qimage(self.pole.display.resize((MINI_PX, MINI_PX)))
            self._set_status(f"Click a marker to open a region ({len(self.regions)} regions with terrain).")
        except (OSError, ValueError) as err:
            self.raster = None
            QMessageBox.critical(self, "Atlas", f"Cannot read {POLE_DEM}\n{err}")
        self._append_topo_note()
        self.update_readout(clear=True)
        self.redraw()

    def show_region(self, stem):
        region = self.regions[stem]
        try:
            raster = self._load(region.dem_path)
        except (OSError, ValueError) as err:
            QMessageBox.critical(self, "Region map", f"Cannot read {region.dem_path}\n{err}")
            return
        self.mode, self.region, self.raster, self.focus = "region", region, raster, region
        self._map_zoom = 1.0
        self._map_pan = (0.0, 0.0)
        self.choice.setCurrentText(region.label)
        self.points = {"gNB": None, "UE": None}
        note = self._apply_gnb_default(stem, raster)
        bdem = find_bdem(stem)
        warn = "" if os.path.exists(bdem) else "  WARNING: no .bdem found for this region."
        self._set_status(f"{region.label}: click the map or type coordinates.{note}{warn}")
        self._append_topo_note()
        self.update_readout(clear=True)
        self.redraw()

    def on_choice(self):
        label = self.choice.currentText()
        self.show_atlas() if label == ATLAS_LABEL else self.show_region(self.labels[label])

    # ---- drawing -------------------------------------------------------------
    def _text_size(self, font, text, width=None):
        fm = QFontMetricsF(font)
        if width:                                    # wrapped to `width` pixels
            r = fm.boundingRect(QRectF(0, 0, width, 1e6), Qt.TextFlag.TextWordWrap.value, text)
            return r.width() + 1, r.height()
        return fm.horizontalAdvance(text) + 1, fm.height()

    def _draw_text(self, p, rect, text, colour, font):
        p.setFont(font)
        p.setPen(QColor(colour))
        p.drawText(rect, Qt.AlignmentFlag.AlignLeft.value | Qt.TextFlag.TextWordWrap.value, text)

    def _text(self, p, x, y, text, colour, anchor="nw", size=None, bold=False, width=None):
        """Plain text (no plate); `width` wraps it like a tk canvas text item."""
        font = self._font(size, bold)
        self._draw_text(p, anchored_rect(*self._text_size(font, text, width), x, y, anchor), text, colour, font)

    def _label(self, p, x, y, text, fg, anchor="sw", size=None, bold=False, clamp=None):
        """Text on a dark plate so it stays readable over any map. `clamp` = (w, h) keeps it inside."""
        font = self._font(size, bold)
        rect = anchored_rect(*self._text_size(font, text), x, y, anchor)
        if clamp:
            dx = max(4 - rect.left(), 0) or min(clamp[0] - 4 - rect.right(), 0)
            dy = max(4 - rect.top(), 0) or min(clamp[1] - 4 - rect.bottom(), 0)
            rect.translate(dx, dy)
        draw_rect(p, rect.left() - 3, rect.top() - 2, rect.right() + 3, rect.bottom() + 2, fill=THEME["label_bg"])
        self._draw_text(p, rect, text, fg, font)

    def redraw(self):
        """Work out the view (scale, link, background, legend), then repaint the map and minimap."""
        self.mini.update()
        self.canvas.update()
        self.controls.move(self.canvas.width() - 12 - self.controls.width(), 12)
        if self.raster is None:
            return
        cw, ch = self.canvas.width(), self.canvas.height()
        iw, ih = self.raster.display.size
        fit_scale = min(cw / iw, ch / ih)
        scale = fit_scale * self._map_zoom
        pan_x, pan_y = self._map_pan
        ox, oy = (cw - iw * scale) / 2 + pan_x, (ch - ih * scale) / 2 + pan_y
        self._view = (scale, ox, oy, iw, ih)
        size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
        self._inset_rect = None
        self._link = self._compute_link()
        if self._link:
            self.sep_var.setText(self._sep_readout(self._link))
        self._background(size)
        if self._bg_qkey != self._bg_key:
            self._bg_qimage, self._bg_qkey = pil_to_qimage(self._bg_img), self._bg_key
        self._update_coverage()
        self._legend = self._map_legend()

    def paint_map(self, p):
        if self.raster is None:
            self._label(p, 20, 20, f"Atlas map not found. Expected: {POLE_DEM}", THEME["label_fg"], "nw")
            return
        if self._bg_qimage is None:
            return
        _, ox, oy, _, _ = self._view
        p.drawImage(QPointF(ox, oy), self._bg_qimage)
        if self._coverage:
            scale, _, _, iw, ih = self._view
            p.save()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(QRectF(ox, oy, iw * scale, ih * scale), self._coverage[0])
            p.restore()
        if self.show_grid.isChecked():
            self._draw_grid(p)
        if self.mode == "atlas":
            self._draw_atlas_markers(p)
        else:
            self._draw_region_overlays(p)
        self._draw_legend(p, *self._legend)
        self._draw_profile_inset(p)

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
        notes = [self._topo_note() if self.show_topo.isChecked() else "",
                 self._psr_note() if self.show_psr.isChecked() else ""]
        notes = [n for n in notes if n]
        if notes:
            self._set_status(self.status.text() + "  " + "  ".join(notes))

    def _current_psr(self):
        """The shadowed-region layer for the map on screen (None if there is no file)."""
        key = self.region.stem if self.mode == "region" and self.region else None
        if key not in self._psr_cache:
            path = POLE_PSR if key is None else os.path.join(REGION_DIR, f"{key}__psr.tif")
            previous = self.status.text()
            self._set_status("Loading shadowed regions...", now=True)
            try:
                layer = PsrLayer(path) if os.path.exists(path) else None
            except (OSError, ValueError):
                layer = None
            self._psr_cache[key] = layer
            self._set_status(previous)
        return self._psr_cache[key]

    def _psr_note(self):
        if self.raster is None:
            return ""
        return "" if self._current_psr() else "No permanently shadowed region file (*_psr.tif) found for this view."

    # ---- UE LOS coverage -------------------------------------------------------
    def _update_coverage(self):
        """Recompute the UE LOS coverage picture when the gNB, the heights or the map change."""
        gnb = self.points["gNB"]
        if self.mode != "region" or gnb is None or not self.show_coverage.isChecked():
            self._cov_key = self._coverage = None
            return
        try:
            heights = float(self.height_vars["gNB"].text()), float(self.height_vars["UE"].text())
        except ValueError:
            self._cov_key = self._coverage = None
            return
        key = (id(self.raster), gnb, heights)
        if key == self._cov_key:
            return
        seen = los_coverage(self.raster, gnb, *heights)
        if seen is None:
            self._coverage = None
        else:
            rgba = np.zeros(seen.shape + (4,), np.uint8)
            rgba[seen] = [int(THEME["coverage"][i:i + 2], 16) for i in (1, 3, 5)] + [int(255 * COVERAGE_OPACITY)]
            self._coverage = (pil_to_qimage(Image.fromarray(rgba, "RGBA")), float(seen.mean()))
        self._cov_key = key

    def on_psr_toggle(self):
        if self.show_psr.isChecked():
            self._set_status(self._psr_note() or "Permanently shadowed regions shown.")
        self.redraw()

    def on_topo_toggle(self):
        if self.show_topo.isChecked():
            self._set_status(self._topo_note() or "Topographic overlay on.")
        self.redraw()

    def _background(self, size):
        """The map picture at `size`, with the overlay composited on top when it is switched on."""
        overlay = self._current_overlay() if self.show_topo.isChecked() else None
        psr = self._current_psr() if self.show_psr.isChecked() else None

        opacity = round(self.topo_opacity, 2)
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

    # ---- gNB-UE link: line of sight and cross-section inset -------------------
    def _compute_link(self):
        """Terrain profile and line-of-sight check between the placed gNB and UE, or None."""
        if self.mode != "region" or not all(self.points.values()):
            return None
        g, u = self.lonlat("gNB"), self.lonlat("UE")
        link = {"sep": distance_m(g, u), "status": "unknown", "message": ""}
        if g == u:
            link["message"] = "gNB and UE are at the same position."
            return link
        try:
            gnb_h, ue_h = float(self.height_vars["gNB"].text()), float(self.height_vars["UE"].text())
        except ValueError:
            gnb_h = ue_h = float("nan")
        dist, terrain = elevation_profile(self.raster, self.points["gNB"], self.points["UE"])
        link.update(dist=dist, terrain=terrain, gnb_h=gnb_h, ue_h=ue_h)
        if not (np.isfinite(gnb_h) and np.isfinite(ue_h)):
            link["message"] = "Antenna heights must be numbers."
        elif not (np.isfinite(terrain[0]) and np.isfinite(terrain[-1])):
            link["message"] = "The DEM has no elevation data at the gNB or the UE."
        else:
            chord = chord_height(dist, float(terrain[0]), gnb_h, float(terrain[-1]), ue_h)
            clearance = float(np.nanmin(chord - terrain))      # NaN (no-data) samples are ignored
            # straight-line (LOS) path length between the antenna tops: ground arc, elevation and mast heights
            R = BODY_RADIUS_M
            ra, rb = R + float(terrain[0]) + gnb_h, R + float(terrain[-1]) + ue_h
            path = math.sqrt((rb - ra) ** 2 + 4 * ra * rb * math.sin(link["sep"] / R / 2) ** 2)
            link.update(chord=chord, clearance=clearance, path=path,
                        status="clear" if clearance >= 0 else "blocked")
        return link

    def _link_colour(self, link):
        key = {"clear": "los_clear", "blocked": "los_blocked"}.get(link["status"] if link else None, "link")
        return THEME[key]

    @staticmethod
    def _fmt_dist(d):
        return f"{d:.1f} m" if d < 1000 else f"{d / 1000:.3f} km"

    def _link_text(self, link):
        """Label for the line: the LOS path length (with elevation) when known, else the ground distance."""
        text = self._fmt_dist(link.get("path", link["sep"]))
        return text + {"clear": " LOS", "blocked": " NLOS"}.get(link["status"], "")

    def _sep_readout(self, link):
        text = f"Ground separation: {self._fmt_dist(link['sep'])}"
        if "path" in link:
            text += f"\nLOS path (with elevation): {self._fmt_dist(link['path'])}"
        return text

    def _controls_bottom(self):
        """Bottom edge, in canvas pixels, of the overlay-controls box."""
        return 12 + self.controls.height()

    def _in_inset(self, event):
        r = self._inset_rect
        return bool(r and r[0] <= event.x <= r[2] and r[1] <= event.y <= r[3])

    def _in_inset_handle(self, event):
        r = self._inset_handle
        return bool(r and r[0] <= event.x <= r[2] and r[1] <= event.y <= r[3])

    def _in_inset_header(self, event):
        r = self._inset_rect
        return bool(r and r[0] <= event.x <= r[2] and r[1] <= event.y <= r[1] + 38)

    def _draw_profile_inset(self, p):
        """Mini cross section of the gNB-UE line; movable and resizable on the map."""
        link = self._link
        if link is None or not self.show_inset.isChecked():
            self._inset_handle = None
            return
        t = THEME
        cw = self.canvas.width()
        ch = self.canvas.height()
        default_w = min(440, int(cw * 0.45))
        if self._inset_size is None:
            w, h = default_w, 235
        else:
            w, h = self._inset_size
        w = max(240, min(w, cw - 24))
        h = max(160, min(h, ch - 24))
        self._inset_size = (w, h)
        if cw < 264 or ch < 184:
            return
        if self._inset_position is None:                    # default: top right, just below the overlay controls
            x0, y0 = cw - 12 - w, self._controls_bottom() + 8
        else:
            x0, y0 = self._inset_position
        x0 = max(12, min(x0, cw - 12 - w))
        y0 = max(12, min(y0, ch - 12 - h))
        x1, y1 = x0 + w, y0 + h
        self._inset_rect = (x0, y0, x1, y1)
        self._inset_handle = (x0, y0, x0 + 12, y0 + 12)
        small = max(self.font_size - 1, 7)
        colour = self._link_colour(link)
        draw_rect(p, x0, y0, x1, y1, fill=t["label_bg"], outline=t["border"], width=2)
        hx0, hy0, hx1, hy1 = self._inset_handle
        draw_rect(p, hx0, hy0, hx1, hy1, fill=t["border"])
        self._text(p, x0 + 8, y0 + 7, "Cross section", t["label_focus_fg"], "nw", bold=True)
        if link["message"]:
            self._text(p, x0 + 8, y0 + 30, link["message"], t["label_fg"], "nw", size=small, width=w - 16)
            return
        status = ({"clear": f"LOS clear, {link['clearance']:.0f} m margin",
                   "blocked": f"NLOS: terrain blocks the line by {-link['clearance']:.0f} m"}[link["status"]])
        self._text(p, x0 + 8, y0 + 26, status, colour, "nw", size=small, bold=True)

        dist, terrain, chord = link["dist"], link["terrain"], link["chord"]
        left, right, top, bottom = x0 + 46, x1 - 14, y0 + 50, y1 - 40
        xmax = max(float(dist[-1]), 1.0)
        valid = np.isfinite(terrain)
        values = np.concatenate((terrain[valid].astype(float), chord))
        zmin, zmax = float(values.min()), float(values.max())
        pad = max(zmax - zmin, 1.0) * 0.12
        zmin, zmax = zmin - pad, zmax + pad
        px = lambda d: left + d / xmax * (right - left)
        py = lambda z: bottom - (z - zmin) / (zmax - zmin) * (bottom - top)

        draw_line(p, [(left, bottom), (right, bottom)], "#9e9e9e")
        draw_line(p, [(left, top), (left, bottom)], "#9e9e9e")
        idx = np.flatnonzero(valid)                                  # each run of valid DEM data on its own
        for run in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
            if len(run) < 2:
                continue
            pts = [(px(float(dist[i])), py(float(terrain[i]))) for i in run]
            draw_polygon(p, [(pts[0][0], bottom)] + pts + [(pts[-1][0], bottom)], t["terrain_fill"])
            draw_line(p, pts, t["terrain_line"], width=2)
        line = [(px(float(d)), py(float(z))) for d, z in zip(dist, chord)]
        draw_line(p, line, colour, width=2, dash=(6, 3))             # the 3-D line, curvature included
        for who, i, height, color in (("gNB", 0, link["gnb_h"], t["gnb"]), ("UE", -1, link["ue_h"], t["ue"])):
            x, y_top = px(float(dist[i])), py(float(chord[i]))
            draw_line(p, [(x, py(float(terrain[i]))), (x, y_top)], color, width=3)
            draw_oval(p, x - 4, y_top - 4, x + 4, y_top + 4, fill=color, outline="#ffffff")
            self._label(p, x + (6 if who == "gNB" else -6), y_top - 5, f"{height:g} m", t["label_fg"],
                        "sw" if who == "gNB" else "se", size=small)
        m = len(dist) // 2
        self._label(p, px(float(dist[m])), py(float(chord[m])) - 8, self._link_text(link), t["label_fg"], "s",
                    size=small, bold=True)
        for frac in (0.0, 0.5, 1.0):                                  # distance axis
            d = xmax * frac
            self._text(p, px(d), bottom + 4, f"{d:.0f} m" if xmax < 1000 else f"{d / 1000:.2f} km",
                       t["label_fg"], "n", size=small)
        for z in (zmin + pad, zmax - pad):                            # elevation axis (data min / max)
            self._text(p, left - 4, py(z), f"{z:.0f}", t["label_fg"], "e", size=small)
        exaggeration = (xmax / (right - left)) / ((zmax - zmin) / (bottom - top))
        self._text(p, x0 + 8, y1 - 6, f"elevation in m, vertical exaggeration x{exaggeration:.1f}",
                   t["label_fg"], "sw", size=small)

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
                     ("dash", t["los_clear"], "Line of sight (LOS) clear"),
                     ("dash", t["los_blocked"], "Line of sight blocked (NLOS)")]
            if self.show_cands.isChecked():
                items += [("dot", t["cand_ridge"], "Candidate mast (ridge)"),
                          ("dot", t["cand_landing"], "Candidate mast (landing site)")]
        if self._coverage:
            items.append(("fill", t["coverage"], f"UE would have LOS to gNB ({self._coverage[1]:.0%} of map)"))
        if self.show_psr.isChecked() and self._current_psr():
            items.append(("fill", t["psr"], "Permanently shadowed region"))
        if self.show_topo.isChecked() and self._current_overlay() is not None:
            items.append(("line", "#bdbdbd", "Topographic overlay"))
        if self.show_grid.isChecked():
            items.append(("line", t["grid"], "Lon/lat grid"))
        zoom, ox, oy, iw, ih = self._view
        return items, scale_bar(self.raster.width * self.raster.dx / (iw * zoom))

    def _draw_legend(self, p, items, scale=None):
        """Legend in the bottom-right corner of the window, and a plain scale bar (no plate) directly on
        the map at the bottom-left of the visible map picture. items: [(kind, colour, text)], kind one
        of dot / ring / line / dash / box / fill, or None for plain text. scale: (bar pixels, label)."""
        t = THEME
        font = self._font()
        cw, ch = self.canvas.width(), self.canvas.height()
        row = int(self.font_size * 2.2) + 2
        legend = ([], [])                  # (drawing steps laid out from (0, 0), the area each covers)

        def text_at(group, x, y, text, anchor):
            rect = anchored_rect(*self._text_size(font, text), x, y, anchor)
            group[1].append(rect)
            group[0].append(lambda p: self._draw_text(p, rect, text, t["label_fg"], font))

        def bbox(group):
            boxes = group[1]
            return (min(b.left() for b in boxes), min(b.top() for b in boxes),
                    max(b.right() for b in boxes), max(b.bottom() for b in boxes)) if boxes else None

        def settle(group, right, bottom):
            """Draw `group` with its bottom-right corner at (right, bottom - 6) on a plate, and return
            the plate rectangle (x1, y1, x2, y2)."""
            box = bbox(group)
            if not box:
                return None
            dx, dy = right - box[2], bottom - 6 - box[3]
            plate = (box[0] + dx - 8, box[1] + dy - 6, box[2] + dx + 8, box[3] + dy + 6)
            draw_rect(p, *plate, fill=t["label_bg"], outline=t["border"])
            p.save()
            p.translate(dx, dy)
            for step in group[0]:
                step(p)
            p.restore()
            return plate

        steps, boxes = legend
        y = 0
        for kind, colour, text in items:
            cy = y + row / 2
            if kind == "dot":
                boxes.append(QRectF(3, cy - 6, 12, 12))
                steps.append(lambda p, cy=cy, colour=colour: draw_oval(
                    p, 4, cy - 5, 14, cy + 5, fill=colour, outline=t["marker_outline"], width=2))
            elif kind == "ring":
                boxes.append(QRectF(3, cy - 6, 12, 12))
                steps.append(lambda p, cy=cy, colour=colour: draw_oval(p, 4, cy - 5, 14, cy + 5, outline=colour, width=2))
            elif kind in ("line", "dash"):
                boxes.append(QRectF(0, cy - 2, 24, 4))
                dash = (5, 3) if kind == "dash" else None
                steps.append(lambda p, cy=cy, colour=colour, dash=dash: (
                    draw_line(p, [(0, cy), (24, cy)], "#cfd8dc", width=4),   # light backing keeps dark lines visible
                    draw_line(p, [(0, cy), (24, cy)], colour, width=2, dash=dash)))
            elif kind == "box":
                boxes.append(QRectF(1, cy - 6, 16, 12))
                steps.append(lambda p, cy=cy, colour=colour: draw_rect(p, 2, cy - 5, 16, cy + 5, outline=colour, width=2))
            elif kind == "fill":
                boxes.append(QRectF(2, cy - 5, 14, 10))
                steps.append(lambda p, cy=cy, colour=colour: draw_rect(p, 2, cy - 5, 16, cy + 5, fill=colour))
            text_at(legend, 30 if kind else 2, cy, text, "w")
            y += row
        settle(legend, cw - 16, ch - 10)                               # window corner, not tied to the map

        if scale:
            length, label = scale
            zoom, ox, oy, iw, ih = self._view
            text_w, text_h = self._text_size(font, label)
            left = max(ox, 0) + 16                                     # visible bottom-left corner of the map
            y = min(oy + ih * zoom, ch) - 14 - text_h - 11             # top of the end ticks
            draw_line(p, [(left, y + 4), (left + length, y + 4)], t["scale"], width=2)
            for x in (left, left + length):
                draw_line(p, [(x, y), (x, y + 8)], t["scale"], width=2)
            self._text(p, left + length / 2, y + 11, label, t["scale"], "n")

    def _canvas_xy(self, fx, fy):
        scale, ox, oy, iw, ih = self._view
        return ox + fx * iw * scale, oy + fy * ih * scale

    def _draw_atlas_markers(self, p):
        t = THEME
        size = (self.canvas.width(), self.canvas.height())
        self._hits = []
        for stem, reg in self.regions.items():
            x, y = self._canvas_xy(*self.raster.xy_to_frac(*lonlat_to_xy(*reg.lonlat)))
            draw_oval(p, x - 6, y - 6, x + 6, y + 6, fill=t["marker"], outline=t["marker_outline"], width=2)
            if reg is not self.focus:                       # the focused region gets a bold label instead
                tag = " [gNB]" if stem in self.gnb_defaults else ""
                self._label(p, x + 9, y - 9, reg.label + tag, t["label_fg"], "sw", clamp=size)
            self._hits.append((x, y, stem))
        for sid, name, lon, lat in self.missing:            # no terrain tile: hollow, grey
            x, y = self._canvas_xy(*self.raster.xy_to_frac(*lonlat_to_xy(lon, lat)))
            draw_oval(p, x - 4, y - 4, x + 4, y + 4, outline=t["missing_fg"], width=2)
            self._label(p, x + 8, y - 8, f"{sid} (no tile)", t["missing_fg"], "sw", clamp=size)
            self._hits.append((x, y, ("missing", name)))
        self._draw_highlight(p, self.focus, self._canvas_xy, size, self.font_size + 2, 16)

    def _draw_highlight(self, p, region, to_canvas, size, font_size, min_box):
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
        draw_rect(p, cx - half_w, cy - half_h, cx + half_w, cy + half_h, outline=THEME["footprint"], width=2)
        above = cy - half_h > 30
        ty, anchor = (cy - half_h - 4, "s") if above else (cy + half_h + 4, "n")
        self._label(p, cx, ty, region.label, THEME["label_focus_fg"], anchor,
                    size=font_size, bold=True, clamp=size)

    def paint_minimap(self, p):
        draw_rect(p, 0.5, 0.5, MINI_PX + 1.5, MINI_PX + 1.5, outline=THEME["border"])   # 1 px border
        if self.pole is None or self.mini_photo is None:
            return
        p.translate(1, 1)
        p.setClipRect(QRectF(0, 0, MINI_PX, MINI_PX))
        p.drawImage(QPointF(0, 0), self.mini_photo)
        to_canvas = lambda fx, fy: (fx * MINI_PX, fy * MINI_PX)
        for reg in self.regions.values():
            x, y = to_canvas(*self.pole.xy_to_frac(*lonlat_to_xy(*reg.lonlat)))
            draw_oval(p, x - 2, y - 2, x + 2, y + 2, fill=THEME["marker"])
        self._draw_highlight(p, self.focus, to_canvas, (MINI_PX, MINI_PX), max(self.font_size - 1, 8), 12)

    def _draw_region_overlays(self, p):
        t = THEME
        if self.show_cands.isChecked():
            colors = {"ridge": t["cand_ridge"], "landing_site": t["cand_landing"]}
            for x, y, cls in self.candidates:
                fx, fy = self.raster.xy_to_frac(x, y)
                if 0 <= fx <= 1 and 0 <= fy <= 1:
                    cx, cy = self._canvas_xy(fx, fy)
                    draw_oval(p, cx - 3, cy - 3, cx + 3, cy + 3, fill=colors.get(cls, "#ffffff"), outline="#000000")
        size = (self.canvas.width(), self.canvas.height())
        mid = None
        if all(self.points.values()):                        # line between gNB and UE, follows the markers
            (x1, y1), (x2, y2) = self._canvas_xy(*self.points["gNB"]), self._canvas_xy(*self.points["UE"])
            draw_line(p, [(x1, y1), (x2, y2)], self._link_colour(self._link), width=3, dash=(6, 4))
            mid = ((x1 + x2) / 2, (y1 + y2) / 2)
        for who, pt in self.points.items():
            if pt:
                cx, cy = self._canvas_xy(*pt)
                draw_oval(p, cx - 8, cy - 8, cx + 8, cy + 8, fill=t["gnb" if who == "gNB" else "ue"],
                          outline=t["marker_outline"], width=2)
                lon, lat = self.lonlat(who)
                self._label(p, cx + 11, cy - 11, f"({lon:.5f}, {lat:.5f})", t["label_fg"], "sw",
                            bold=True, clamp=size)
        if mid and self._link:                               # separation written on the line itself
            self._label(p, mid[0], mid[1], self._link_text(self._link), t["label_fg"], "center",
                        bold=True, clamp=size)

    def _draw_grid(self, p):
        r, t = self.raster, THEME
        lon0, lon1, lat0, lat1, pole = raster_lonlat_extent(r)
        pad = (lat1 - lat0) * 0.05                       # sampled extent slightly underestimates
        lat0, lat1 = max(-90.0, lat0 - pad), min(-0.1, lat1 + pad)
        if not pole:
            pad = (lon1 - lon0) * 0.05
            lon0, lon1 = lon0 - pad, lon1 + pad
        lat_step = grid_step(lat1 - lat0)
        lon_step = 30 if pole else grid_step(lon1 - lon0)
        size = (self.canvas.width(), self.canvas.height())

        def trace(points, text, anchor):
            """Project the points, draw each on-screen run as a solid line, label its start."""
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
                    draw_line(p, pts, t["grid"], width=2)
            if runs and runs[0]:
                self._label(p, *runs[0][0], text, t["grid_label"], anchor,
                            size=max(self.font_size - 1, 7), clamp=size)

        def fmt(v, step):
            d = max(0, math.ceil(-math.log10(step) - 1e-9))
            return f"{v:.{d}f}°"

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
        if self.raster is None or self._in_inset(event):
            if self._in_inset_handle(event):
                w, h = self._inset_size if self._inset_size else (440, 235)
                x0, y0, x1, y1 = self._inset_rect
                self._inset_drag = ("resize", event.x, event.y, x0, y0, x1, y1, w, h)
            elif self._in_inset_header(event):
                x0, y0, _, _ = self._inset_rect
                self._inset_drag = ("move", event.x, event.y, x0, y0)
            return
        if self.mode == "atlas":
            hits = [(math.hypot(event.x - x, event.y - y), t) for x, y, t in self._hits]
            if hits and min(hits, key=lambda h: h[0])[0] <= 14:
                target = min(hits, key=lambda h: h[0])[1]
                if isinstance(target, tuple):
                    QMessageBox.information(self, "No terrain tile",
                                            f"{target[1]} has no region tile in this atlas release.")
                else:
                    self.show_region(target)
        else:
            self.place(event)

    def on_drag(self, event):
        if self._inset_drag:
            cw, ch = self.canvas.width(), self.canvas.height()
            if self._inset_drag[0] == "resize":
                _, start_x, start_y, _, _, fixed_x1, fixed_y1, _, _ = self._inset_drag
                new_x0 = max(12, min(event.x, fixed_x1 - 240))
                new_y0 = max(12, min(event.y, fixed_y1 - 160))
                self._inset_position = (new_x0, new_y0)
                self._inset_size = (max(240, fixed_x1 - new_x0),
                                    max(160, fixed_y1 - new_y0))
            else:
                _, start_x, start_y, start_x0, start_y0 = self._inset_drag
                w, h = self._inset_size or (440, 235)
                new_x0 = max(12, min(cw - w - 12, start_x0 + event.x - start_x))
                new_y0 = max(12, min(ch - h - 12, start_y0 + event.y - start_y))
                self._inset_position = (new_x0, new_y0)
            self.redraw()
            return
        if self.mode == "region" and not self._in_inset(event):
            self.place(event)

    def on_release(self, event):
        self._inset_drag = None

    def on_pan_press(self, event):
        self._map_pan_drag = (event.x, event.y, self._map_pan)

    def on_pan_drag(self, event):
        if self._map_pan_drag:
            start_x, start_y, pan = self._map_pan_drag
            self._map_pan = (pan[0] + event.x - start_x, pan[1] + event.y - start_y)
            self.redraw()

    def on_pan_release(self, event):
        self._map_pan_drag = None

    def on_mousewheel_zoom(self, event, factor):
        if self.raster is None:
            return
        cw, ch = self.canvas.width(), self.canvas.height()
        iw, ih = self.raster.display.size
        scale, ox, oy, _, _ = self._view
        fx = (event.x - ox) / (iw * scale)
        fy = (event.y - oy) / (ih * scale)
        self._map_zoom = max(1.0, min(8.0, self._map_zoom * factor))
        new_scale = min(cw / iw, ch / ih) * self._map_zoom
        pan_x = event.x - (cw - iw * new_scale) / 2 - iw * new_scale * fx
        pan_y = event.y - (ch - ih * new_scale) / 2 - ih * new_scale * fy
        self._map_pan = (pan_x, pan_y)
        self.redraw()

    def place(self, event):
        fx, fy = self._frac(event)
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            self._set_status("Click inside the map: points must lie within the terrain tile.")
            return
        self.points[self._active()] = (fx, fy)
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
                self.lon_vars[who].setText(f"{v[0]:.6f}")
                self.lat_vars[who].setText(f"{v[1]:.6f}")
            elif clear:
                self.lon_vars[who].setText("")
                self.lat_vars[who].setText("")
        g, u = ll["gNB"], ll["UE"]
        self.sep_var.setText(f"Separation: {distance_m(g, u):.0f} m" if g and u else "Separation: -")

    def clear_points(self):
        self.points = {"gNB": None, "UE": None}
        self.update_readout(clear=True)
        self.redraw()

    # ---- typed coordinates and default gNB -----------------------------------
    def place_from_entries(self, who):
        """Put `who` at the typed lon/lat. Returns True on success."""
        if self.mode != "region":
            QMessageBox.information(self, "Open a region", "Open a region first.")
            return False
        try:
            lon, lat = float(self.lon_vars[who].text()), float(self.lat_vars[who].text())
        except ValueError:
            QMessageBox.warning(self, "Invalid coordinates", f"{who}: longitude and latitude must be numbers.")
            return False
        fx, fy = self.raster.xy_to_frac(*lonlat_to_xy(lon, lat))
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            QMessageBox.warning(self, "Outside the tile", f"{who}: that position is outside this region's map.")
            return False
        self.points[who] = (fx, fy)
        self._set_active(who)
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
            self.height_vars["gNB"].setText(f"{d[2]:g}")
        return "  Default gNB placed."

    def save_default(self):
        if not self.place_from_entries("gNB"):
            return
        try:
            height = float(self.height_vars["gNB"].text())
        except ValueError:
            QMessageBox.warning(self, "Invalid height", "gNB height must be a number.")
            return
        lon, lat = self.lonlat("gNB")
        self.gnb_defaults[self.region.stem] = (lon, lat, height)
        save_gnb_defaults(self.gnb_defaults)
        self._set_status(f"Saved default gNB for {self.region.label} ({lon:.5f}, {lat:.5f}, {height:g} m).")

    def clear_default(self):
        if self.mode == "region" and self.gnb_defaults.pop(self.region.stem, None):
            save_gnb_defaults(self.gnb_defaults)
            self._set_status(f"Cleared the default gNB for {self.region.label}.")
        else:
            self._set_status("No saved default for this region.")

    def place_optimal_gnb(self):
        """Run optimal_gNB.find_best_mast() for the open region and place the result as the gNB."""
        if self.mode != "region":
            QMessageBox.information(self, "Open a region", "Open a region first.")
            return
        try:
            from optimal_gNB import find_best_mast
        except ImportError as err:
            QMessageBox.critical(self, "Missing dependency",
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
            QMessageBox.critical(self, "Optimal gNB", str(err))
            return
        if best is None:
            QMessageBox.warning(
                self, "Optimal gNB",
                f"No candidate mast found for {self.region.label} "
                f"(region id {region_id}) in site_tiles_index.csv.")
            return
        lon, lat = float(best["lon_e"]), float(best["lat"])
        fx, fy = self.raster.xy_to_frac(*lonlat_to_xy(lon, lat))
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            QMessageBox.warning(self, "Outside the tile",
                                "The optimal mast for this region lies outside its terrain tile.")
            return
        self.points["gNB"] = (fx, fy)
        self.height_vars["gNB"].setText(f"{float(best['mast_height_m']):g}")
        self._set_active("gNB")
        self.update_readout()
        self.redraw()
        coverage_col = f"area_km2_{OPTIMAL_GNB_FREQ_GHZ:.3f}GHz"
        self._set_status(
            f"Optimal gNB for {self.region.label}: mast {best['cand_id']} "
            f"({lon:.5f}, {lat:.5f}), {float(best[coverage_col]):.1f} km² "
            f"coverage @ {OPTIMAL_GNB_FREQ_GHZ:g} GHz.")

    # ---- export --------------------------------------------------------------
    def export(self):
        if self.mode != "region" or not all(self.points.values()):
            QMessageBox.warning(self, "Not ready", "Open a region and place both the gNB and the UE.")
            return
        try:
            heights = {w: float(v.text()) for w, v in self.height_vars.items()}
        except ValueError:
            QMessageBox.warning(self, "Invalid height", "Antenna heights must be numbers.")
            return
        g, u = self.lonlat("gNB"), self.lonlat("UE")
        if g == u:
            QMessageBox.warning(self, "Same point", "gNB and UE are at the same position.")
            return
        bdem = find_bdem(self.region.stem)
        if not os.path.exists(bdem) and QMessageBox.question(
                self, "Missing .bdem",
                f"{bdem} was not found.\nThe simulator would fall back to flat terrain. Export anyway?"
        ) != QMessageBox.StandardButton.Yes:
            return
        os.makedirs(EXPORT_DIR, exist_ok=True)
        out_dir = QFileDialog.getExistingDirectory(self, "Choose output folder (a dated subfolder is created)",
                                                   EXPORT_DIR)
        if not out_dir:
            return
        run_dir = make_run_folder(out_dir, self.region.label)
        export_configs(run_dir, TEMPLATE_DIR, g, u, heights["gNB"], heights["UE"], bdem)
        self._set_status(f"Exported to:\n{run_dir}")


def main():
    # Qt's GTK3 theme plugin loads GTK, which on Linux GNOME 42 can abort on a removed GSettings key.
    # Qt's built-in GNOME theme avoids GTK; Windows and macOS do not support this workaround.
    if sys.platform.startswith("linux"):
        if os.environ.get("QT_QPA_PLATFORMTHEME", "") in ("", "gtk3", "xdgdesktopportal"):
            os.environ["QT_QPA_PLATFORMTHEME"] = "gnome"
    app = QApplication(sys.argv)
    try:
        regions, missing = load_catalog()
    except (OSError, KeyError, ValueError) as err:
        QMessageBox.critical(None, "Site list", f"Could not read {SITES_CSV}:\n{err}")
        return
    window = PlannerApp(regions, missing if SHOW_SITES_WITHOUT_TILE else [], load_candidates())
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
