"""Pure geographic math for the Lunar Site Planner.

No Qt, no Pillow, no file I/O: only `math`, `numpy` and the body radius from settings.py,
so everything here is easy to unit test.

Contents:
  - Map projection      xy_to_lonlat, lonlat_to_xy   (south polar stereographic, sphere R)
  - Distances           distance_m                   (great-circle)
  - Curvature / LOS     curvature_drop, chord_height
  - Graticule helpers   GRID_STEPS, grid_step, frange
  - Scale bar           scale_bar
"""
import math

import numpy as np

#from settings import BODY_RADIUS_M      # package layout: `from .settings import BODY_RADIUS_M`
BODY_RADIUS_M = 1_737_400.0  

# ----------------------------------------------------------------------------
# Projection  (south polar stereographic, sphere R, true scale at the pole)
# ----------------------------------------------------------------------------
def xy_to_lonlat(x, y):
    """Projected metres -> (lon, lat) degrees, east-positive longitude."""
    rho = math.hypot(x, y)
    return math.degrees(math.atan2(x, y)), -90.0 + math.degrees(2 * math.atan(rho / (2 * BODY_RADIUS_M)))


def lonlat_to_xy(lon, lat):
    """(lon, lat) degrees -> projected metres. Inverse of xy_to_lonlat."""
    rho = 2 * BODY_RADIUS_M * math.tan(math.radians(lat + 90.0) / 2)
    return rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))


# ----------------------------------------------------------------------------
# Distances
# ----------------------------------------------------------------------------
def distance_m(a, b):
    """Great-circle distance between two (lon, lat) points, metres."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * BODY_RADIUS_M * math.asin(math.sqrt(h))


# ----------------------------------------------------------------------------
# Curvature and line of sight
# ----------------------------------------------------------------------------
def curvature_drop(d):
    """How far (m) the surface falls below a flat tangent plane at ground distance `d` (m).
    Small-angle form d^2 / 2R, used for the coverage ray casting. Works on floats or arrays."""
    return d ** 2 / (2 * BODY_RADIUS_M)


def chord_height(dist, z_a, h_a, z_b, h_b):
    """Height (m, above the reference sphere) of the straight 3-D line between two antennas at
    each ground distance in `dist`. z = ground elevation, h = antenna height. Includes the
    curvature of the Moon, so long links dip below the horizon as they should."""
    R = BODY_RADIUS_M
    theta = dist[-1] / R
    ra, rb = R + z_a + h_a, R + z_b + h_b
    e0, e1 = rb * math.sin(theta), rb * math.cos(theta) - ra          # B - A, with A = (0, ra)
    phi = np.asarray(dist, dtype=float) / R
    return (-ra * e0) / (np.sin(phi) * e1 - np.cos(phi) * e0) - R


# ----------------------------------------------------------------------------
# Graticule (lon/lat grid) helpers
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# Scale bar
# ----------------------------------------------------------------------------
def scale_bar(m_per_px, target_px=110):
    """(bar length in pixels, label) for a scale bar roughly target_px wide (1, 2 or 5 x 10^n)."""
    raw = m_per_px * target_px
    base = 10 ** math.floor(math.log10(raw))
    length = max(k for k in (1, 2, 5, 10) if k * base <= raw) * base
    return length / m_per_px, (f"{length:g} m" if length < 1000 else f"{length / 1000:g} km")