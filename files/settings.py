"""Settings for the Lunar Site Planner: paths, defaults, constants and the colour THEME.

This module only defines values. It imports nothing from the rest of the app, so every other
module can import from it without creating a circular import, and it does no work at import
time beyond building paths from the standard library.
"""
import os

# ----------------------------------------------------------------------------
# Paths
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
GNB_DEFAULTS_CSV = os.path.join(APP_DIR, "gnb_defaults.csv")             # region,lon,lat,height_m

# optimal_gNB.py lives at the repo root, alongside its coverage/index CSVs
OPTIMAL_GNB_CANDIDATES_CSV = os.path.join(ROOT_DIR, "candidates_coverage.csv")
OPTIMAL_GNB_INDEX_CSV = os.path.join(ROOT_DIR, "site_tiles_index.csv")
OPTIMAL_GNB_FREQ_GHZ = 2.580

# ----------------------------------------------------------------------------
# Overlays and shadowed regions
# ----------------------------------------------------------------------------
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

# ----------------------------------------------------------------------------
# Display
# ----------------------------------------------------------------------------
MINI_PX = 210                            # size of the atlas minimap in the side panel
DISPLAY_MAX_PX = 1800                    # maps are shown at most this many pixels wide/high
SHOW_SITES_WITHOUT_TILE = False          # True: also draw sites with no region tile as grey, unclickable markers

# ----------------------------------------------------------------------------
# Physical constants and radio defaults
# ----------------------------------------------------------------------------
BODY_RADIUS_M = 1_737_400.0              # Moon sphere used by the atlas and bictr_body_radius
GNB_HEIGHT_M = 4.0                       # atlas radio_params.json: mast_height_m
UE_HEIGHT_M = 1.5                        # atlas radio_params.json: rx_height_m
REGION_ALIASES = {"Leibnitz_Beta_Plateau": "Mons_Mouton"}   # same massif (see Bictr notes)

# ----------------------------------------------------------------------------
# Config export
# ----------------------------------------------------------------------------
GNB_CONF = "gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf"
UE_CONF = "ue.bictr.conf"
BLOCK_GNB_SIDE = "rfsimu_channel_enB0"   # TX = gNB, RX = UE
BLOCK_UE_SIDE = "rfsimu_channel_ue0"     # TX = UE,  RX = gNB (swapped)

# ----------------------------------------------------------------------------
# LOOK AND FEEL: change colours and font size here (all UI colours live in this block)
# ----------------------------------------------------------------------------
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