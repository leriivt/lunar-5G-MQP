"""Catalog for the Lunar Site Planner: which sites and regions exist, and where their files are.

No Qt, no Pillow, no numpy. Only the standard library plus constants from settings.py.

Contents:
  - Site, Region        what a site and a clickable region are
  - region_stem         site name -> file stem
  - load_catalog        sites.csv -> regions with a terrain tile, plus sites without one
  - find_bdem           locate the .bdem terrain file for a region
  - load_candidates     atlas candidate mast positions
  - gNB defaults        load_gnb_defaults / save_gnb_defaults (gnb_defaults.csv)
"""
import csv
import os
import re
from dataclasses import dataclass, field
from typing import NamedTuple

# package layout: use `from .settings import ...`
from settings import (CANDIDATES_CSV, GNB_DEFAULTS_CSV, POLE_BDEM, REGION_ALIASES, REGION_DIR,
                      SITES_CSV, TERRAIN_DIR)


class Site(NamedTuple):
    """One row of sites.csv. A NamedTuple, so old code that unpacks `(id, name, lon, lat)` or
    indexes `site[2]` keeps working, while new code can write `site.lon`."""
    id: str
    name: str
    lon: float
    lat: float


@dataclass
class Region:
    stem: str                                   # file stem, e.g. "Haworth"
    sites: list = field(default_factory=list)  # [Site, ...]

    @property
    def label(self):
        return self.stem.replace("_", " ")

    @property
    def lonlat(self):
        return self.sites[0].lon, self.sites[0].lat

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
            site = Site(row["id"].strip(), row["name"].strip(), float(lon), float(lat))
            reg = regions.setdefault(region_stem(site.name), Region(region_stem(site.name)))
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