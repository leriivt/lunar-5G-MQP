'''
import rasterio
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import LinearLocator

tiff = "Haworth_final_adj_5mpp_surf.tif"
offset = 1737.4

with rasterio.open(tiff) as src:
    data = src.read(1)  # Read the first band
    transform = src.transform
    #width = src.width
    #height = src.height

    # Create pixel coordinate indices
    #rows, cols = np.indices(data.shape) #rows and cols are each 2d arrays
    rows = np.indices((src.width,))
    cols = np.indices((src.height,))

    # Convert pixel (col, row) coordinates to geospatial (X, Y) coordinates
    x, y = rasterio.transform.xy(transform, rows, cols)
    x = np.array(x) #1d arr
    y = np.array(y)
    X, Y = np.meshgrid(x, y) #turn each itso a 2d coord array

    print(data.shape)   # Dimensions (height, width)
    print(src.profile)  # Metadata
    print("\n")
    print(data)
    #print(src.crs)
    print("\n")


print(data) #data is a numpy array
print(transform)

Z = data 

fig, ax = plt.subplots(subplot_kw={"projection": "3d"})

surf = ax.plot_surface(X, Y, Z, cmap="viridis", linewidth=0, antialiased=False)

ax.zaxis.set_major_locator(LinearLocator(10))
# A StrMethodFormatter is used automatically
ax.zaxis.set_major_formatter('{x:.02f}')

# Add a color bar which maps values to colors.
fig.colorbar(surf, shrink=0.5, aspect=5)

plt.show()


'''
'''
import numpy as np
import matplotlib.pyplot as plt
import rasterio
from rasterio.enums import Resampling
from matplotlib.ticker import LinearLocator

tiff = "Haworth_final_adj_5mpp_surf.tif"
downsample = 20          # 5 m/px * 20 = 100 m/px; lower = more detail, slower
vert_exag = 1.0          # set >1 to exaggerate relief

with rasterio.open(tiff) as src:
    print("Size (px):", src.width, "x", src.height)
    print("CRS:", src.crs)
    print("Nodata:", src.nodata)

    out_h = max(1, src.height // downsample)
    out_w = max(1, src.width // downsample)

    data = src.read(
        1,
        out_shape=(out_h, out_w),
        resampling=Resampling.average,
        masked=True,
    )
    transform = src.transform * src.transform.scale(
        src.width / out_w, src.height / out_h
    )

# Pixel-center coordinates (north-up, unrotated raster)
x = transform.c + transform.a * (np.arange(out_w) + 0.5)
y = transform.f + transform.e * (np.arange(out_h) + 0.5)
X, Y = np.meshgrid(x, y)

Z = data.astype("float64").filled(np.nan)   # already heights in meters
print("Z range (m):", np.nanmin(Z), "to", np.nanmax(Z))  # sanity check

fig = plt.figure(figsize=(10, 8))
ax = fig.add_subplot(projection="3d")
#surf = ax.plot_surface(X, Y, Z, cmap="viridis", linewidth=0, antialiased=False)
surf = ax.plot_surface(X, Y, Z, cmap="viridis", linewidth=0, antialiased=False,
                       rcount=out_h, ccount=out_w)

ax.set_box_aspect((np.ptp(X), np.ptp(Y), np.nanmax(Z) - np.nanmin(Z)) if vert_exag == 1
                  else (np.ptp(X), np.ptp(Y), (np.nanmax(Z) - np.nanmin(Z)) * vert_exag))
ax.zaxis.set_major_locator(LinearLocator(8))
ax.zaxis.set_major_formatter("{x:.0f}")
ax.set_xlabel("X (m, polar stereographic)")
ax.set_ylabel("Y (m, polar stereographic)")
ax.set_zlabel("Height (m)")
fig.colorbar(surf, shrink=0.5, aspect=5, label="Height (m)")
plt.show()
'''
'''
import numpy as np
import matplotlib.pyplot as plt
import rasterio
from rasterio.enums import Resampling
from matplotlib.colors import LightSource
from matplotlib.ticker import LinearLocator

# ---------------- settings ----------------
TIFF = "Haworth_final_adj_5mpp_surf.tif"
DOWNSAMPLE = 20       # 5 m/px * 20 = 100 m/px. Lower = more detail but slower 3D
VERT_EXAG = 1.0       # 1.0 = true scale; >1 exaggerates relief in the 3D plot
HILLSHADE_EXAG = 2.0  # vertical exaggeration for the hillshade map
CMAP = "magma"
CLIP_PCT = (2, 98)    # color range percentiles, so outliers don't wash out the map
SHOW_3D = True
SHOW_HILLSHADE = True
# ------------------------------------------

with rasterio.open(TIFF) as src:
    print("Size (px):", src.width, "x", src.height)
    print("CRS:", src.crs)
    print("Nodata:", src.nodata)

    out_h = max(1, src.height // DOWNSAMPLE)
    out_w = max(1, src.width // DOWNSAMPLE)

    data = src.read(
        1,
        out_shape=(out_h, out_w),
        resampling=Resampling.average,
        masked=True,
    )

    # Transform adjusted for the reduced resolution
    transform = src.transform * src.transform.scale(
        src.width / out_w, src.height / out_h
    )

# 1D pixel-center coordinates (valid for a north-up, unrotated raster)
x = transform.c + transform.a * (np.arange(out_w) + 0.5)
y = transform.f + transform.e * (np.arange(out_h) + 0.5)
X, Y = np.meshgrid(x, y)

# Heights in meters relative to the 1737.4 km reference sphere (no offset needed)
Z = data.astype("float64").filled(np.nan)
z_min, z_max = np.nanmin(Z), np.nanmax(Z)
vmin, vmax = np.nanpercentile(Z, CLIP_PCT)
norm = plt.Normalize(vmin=vmin, vmax=vmax)

print("Plotted grid:", Z.shape, "at", abs(transform.a), "m/px")
print("Z range (m):", z_min, "to", z_max)
print("Color range (m):", vmin, "to", vmax)

# ---------------- 3D surface ----------------
if SHOW_3D:
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(projection="3d")

    # Grayscale shading blended with elevation color, drawn per-face
    ls3d = LightSource(azdeg=315, altdeg=35)
    face_rgb = ls3d.shade(
        np.ma.masked_invalid(Z),
        cmap=plt.get_cmap(CMAP),
        norm=norm,
        blend_mode="soft",
        vert_exag=HILLSHADE_EXAG,
        dx=abs(transform.a),
        dy=abs(transform.e),
    )

    ax.plot_surface(
        X, Y, Z,
        facecolors=face_rgb,
        linewidth=0,
        antialiased=False,
        shade=False,
        rcount=out_h,   # by default matplotlib caps these at 50
        ccount=out_w,
    )

    ax.set_box_aspect((np.ptp(X), np.ptp(Y), (z_max - z_min) * VERT_EXAG))
    ax.zaxis.set_major_locator(LinearLocator(8))
    ax.zaxis.set_major_formatter("{x:.0f}")
    ax.set_xlabel("X (m, polar stereographic)")
    ax.set_ylabel("Y (m, polar stereographic)")
    ax.set_zlabel("Height (m)")
    ax.set_title("Haworth crater region (LOLA 5 m/px DEM)")

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.5, aspect=5, label="Height (m)")

# ---------------- hillshade map ----------------
if SHOW_HILLSHADE:
    ls = LightSource(azdeg=315, altdeg=35)
    rgb = ls.shade(
        np.ma.masked_invalid(Z),
        cmap=plt.get_cmap(CMAP),
        norm=norm,
        blend_mode="soft",   # grayscale relief shading with elevation color blended in
        vert_exag=HILLSHADE_EXAG,
        dx=abs(transform.a),
        dy=abs(transform.e),
    )

    fig2, ax2 = plt.subplots(figsize=(8, 8))
    ax2.imshow(rgb, extent=[x.min(), x.max(), y.min(), y.max()])
    ax2.set_xlabel("X (m)")
    ax2.set_ylabel("Y (m)")
    ax2.set_title("Hillshade (light from NW, %.1fx vertical exaggeration)" % HILLSHADE_EXAG)

    sm2 = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm2.set_array([])
    fig2.colorbar(sm2, ax=ax2, shrink=0.7, label="Height (m)")

plt.show()
'''
'''
import numpy as np
import matplotlib.pyplot as plt
import rasterio
from rasterio.enums import Resampling
from matplotlib.colors import LightSource, LinearSegmentedColormap
from matplotlib.ticker import LinearLocator

# ---------------- settings ----------------
TIFF = "Haworth_final_adj_5mpp_surf.tif"
DOWNSAMPLE = 20       # 5 m/px * 20 = 100 m/px. Lower = more detail but slower 3D
VERT_EXAG = 1.0       # 1.0 = true scale; >1 exaggerates relief in the 3D plot
HILLSHADE_EXAG = 2.0  # vertical exaggeration for the hillshade map
# Rainbow topography colormap modeled on the reference image's colorbar (-5..5 km)
CMAP = LinearSegmentedColormap.from_list("lunar_topo", [
    (0.00, "#000000"),  # black
    (0.10, "#2a1a6b"),  # dark indigo
    (0.20, "#3b4cc0"),  # blue
    (0.30, "#2f8fb8"),  # steel blue / teal
    (0.40, "#2fb5a0"),  # cyan-green
    (0.50, "#5cc43a"),  # green
    (0.60, "#e8e22a"),  # yellow
    (0.70, "#f39a1f"),  # orange
    (0.80, "#e0301e"),  # red
    (0.90, "#8c6a5a"),  # brown-gray
    (1.00, "#ffffff"),  # white
])
CLIP_PCT = (2, 98)    # color range percentiles, so outliers don't wash out the map
SHOW_3D = True
SHOW_HILLSHADE = True
# ------------------------------------------

with rasterio.open(TIFF) as src:
    print("Size (px):", src.width, "x", src.height)
    print("CRS:", src.crs)
    print("Nodata:", src.nodata)

    out_h = max(1, src.height // DOWNSAMPLE)
    out_w = max(1, src.width // DOWNSAMPLE)

    data = src.read(
        1,
        out_shape=(out_h, out_w),
        resampling=Resampling.average,
        masked=True,
    )

    # Transform adjusted for the reduced resolution
    transform = src.transform * src.transform.scale(
        src.width / out_w, src.height / out_h
    )

# 1D pixel-center coordinates (valid for a north-up, unrotated raster)
x = transform.c + transform.a * (np.arange(out_w) + 0.5)
y = transform.f + transform.e * (np.arange(out_h) + 0.5)
X, Y = np.meshgrid(x, y)

# Heights in meters relative to the 1737.4 km reference sphere (no offset needed)
Z = data.astype("float64").filled(np.nan)
z_min, z_max = np.nanmin(Z), np.nanmax(Z)
vmin, vmax = np.nanpercentile(Z, CLIP_PCT)
norm = plt.Normalize(vmin=vmin, vmax=vmax)

print("Plotted grid:", Z.shape, "at", abs(transform.a), "m/px")
print("Z range (m):", z_min, "to", z_max)
print("Color range (m):", vmin, "to", vmax)

# ---------------- 3D surface ----------------
if SHOW_3D:
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(projection="3d")

    # Grayscale shading blended with elevation color, drawn per-face
    ls3d = LightSource(azdeg=315, altdeg=35)
    face_rgb = ls3d.shade(
        np.ma.masked_invalid(Z),
        cmap=plt.get_cmap(CMAP),
        norm=norm,
        blend_mode="soft",
        vert_exag=HILLSHADE_EXAG,
        dx=abs(transform.a),
        dy=abs(transform.e),
    )

    ax.plot_surface(
        X, Y, Z,
        facecolors=face_rgb,
        linewidth=0,
        antialiased=False,
        shade=False,
        rcount=out_h,   # by default matplotlib caps these at 50
        ccount=out_w,
    )

    ax.set_box_aspect((np.ptp(X), np.ptp(Y), (z_max - z_min) * VERT_EXAG))
    ax.zaxis.set_major_locator(LinearLocator(8))
    ax.zaxis.set_major_formatter("{x:.0f}")
    ax.set_xlabel("X (m, polar stereographic)")
    ax.set_ylabel("Y (m, polar stereographic)")
    ax.set_zlabel("Height (m)")
    ax.set_title("Haworth crater region (LOLA 5 m/px DEM)")

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.5, aspect=5, label="Height (m)")

# ---------------- hillshade map ----------------
if SHOW_HILLSHADE:
    ls = LightSource(azdeg=315, altdeg=35)
    rgb = ls.shade(
        np.ma.masked_invalid(Z),
        cmap=plt.get_cmap(CMAP),
        norm=norm,
        blend_mode="soft",   # grayscale relief shading with elevation color blended in
        vert_exag=HILLSHADE_EXAG,
        dx=abs(transform.a),
        dy=abs(transform.e),
    )

    fig2, ax2 = plt.subplots(figsize=(8, 8))
    ax2.imshow(rgb, extent=[x.min(), x.max(), y.min(), y.max()])
    ax2.set_xlabel("X (m)")
    ax2.set_ylabel("Y (m)")
    ax2.set_title("Hillshade (light from NW, %.1fx vertical exaggeration)" % HILLSHADE_EXAG)

    sm2 = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm2.set_array([])
    fig2.colorbar(sm2, ax=ax2, shrink=0.7, label="Height (m)")

plt.show()
'''
'''
import numpy as np
import matplotlib.pyplot as plt
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from matplotlib.colors import LightSource, LinearSegmentedColormap
from matplotlib.ticker import LinearLocator

# ---------------- settings ----------------
TIFF = "Haworth_final_adj_5mpp_surf.tif"
DOWNSAMPLE = 1       # applied to the cropped window; 5 m/px * 10 = 50 m/px
VERT_EXAG = 1.0       # 1.0 = true scale; >1 exaggerates relief in the 3D plot
HILLSHADE_EXAG = 2.0  # vertical exaggeration for the hillshade map
CLIP_PCT = (2, 98)    # color range percentiles, so outliers don't wash out the map
SHOW_3D = True
SHOW_HILLSHADE = True

# --- crop to the crater ---
CENTER = (-37500, 92000)         # (x, y) in meters (polar stereographic), or None to auto-detect
                      # the crater floor (centroid of the lowest 5% of the tile)
RADIUS_M = 2500      # crop half-width in meters (square box around CENTER)
CIRCULAR_MASK = False  # also blank out everything outside the circle of RADIUS_M
# ------------------------------------------

# Rainbow topography colormap modeled on the reference image's colorbar
CMAP = LinearSegmentedColormap.from_list("lunar_topo", [
    (0.00, "#000000"), (0.10, "#2a1a6b"), (0.20, "#3b4cc0"), (0.30, "#2f8fb8"),
    (0.40, "#2fb5a0"), (0.50, "#5cc43a"), (0.60, "#e8e22a"), (0.70, "#f39a1f"),
    (0.80, "#e0301e"), (0.90, "#8c6a5a"), (1.00, "#ffffff"),
])

with rasterio.open(TIFF) as src:
    print("Size (px):", src.width, "x", src.height)
    print("CRS:", src.crs)
    print("Nodata:", src.nodata)
    T = src.transform

    # --- find the crater center if not given ---
    if CENTER is None:
        ch, cw = max(1, src.height // 50), max(1, src.width // 50)
        coarse = src.read(1, out_shape=(ch, cw), resampling=Resampling.average,
                          masked=True).astype("float64").filled(np.nan)
        ctf = T * T.scale(src.width / cw, src.height / ch)
        rr, cc = np.where(coarse <= np.nanpercentile(coarse, 5))
        cx = ctf.c + ctf.a * (cc.mean() + 0.5)
        cy = ctf.f + ctf.e * (rr.mean() + 0.5)
        print("Auto-detected center (m): x=%.0f, y=%.0f" % (cx, cy))
    else:
        cx, cy = CENTER

    # --- pixel window for the crop, clipped to the raster ---
    col0 = int(np.floor((cx - RADIUS_M - T.c) / T.a))
    col1 = int(np.ceil((cx + RADIUS_M - T.c) / T.a))
    row0 = int(np.floor((cy + RADIUS_M - T.f) / T.e))   # T.e is negative
    row1 = int(np.ceil((cy - RADIUS_M - T.f) / T.e))
    col0, col1 = max(0, col0), min(src.width, col1)
    row0, row1 = max(0, row0), min(src.height, row1)
    win = Window(col0, row0, col1 - col0, row1 - row0)
    if win.width < 2 or win.height < 2:
        raise SystemExit("Crop window is empty - check CENTER / RADIUS_M against the tile bounds: "
                         "%s" % (src.bounds,))
    print("Crop window (px): cols %d-%d, rows %d-%d" % (col0, col1, row0, row1))

    out_h = max(1, int(win.height) // DOWNSAMPLE)
    out_w = max(1, int(win.width) // DOWNSAMPLE)
    data = src.read(1, window=win, out_shape=(out_h, out_w),
                    resampling=Resampling.average, masked=True)
    wtf = src.window_transform(win)
    transform = wtf * wtf.scale(win.width / out_w, win.height / out_h)

# 1D pixel-center coordinates (valid for a north-up, unrotated raster)
x = transform.c + transform.a * (np.arange(out_w) + 0.5)
y = transform.f + transform.e * (np.arange(out_h) + 0.5)
X, Y = np.meshgrid(x, y)

# Heights in meters relative to the 1737.4 km reference sphere (no offset needed)
Z = data.astype("float64").filled(np.nan)
if CIRCULAR_MASK:
    Z[(X - cx) ** 2 + (Y - cy) ** 2 > RADIUS_M ** 2] = np.nan

z_min, z_max = np.nanmin(Z), np.nanmax(Z)
vmin, vmax = np.nanpercentile(Z, CLIP_PCT)
norm = plt.Normalize(vmin=vmin, vmax=vmax)

print("Plotted grid:", Z.shape, "at", abs(transform.a), "m/px")
print("Z range (m):", z_min, "to", z_max)
print("Color range (m):", vmin, "to", vmax)

# ---------------- 3D surface ----------------
if SHOW_3D:
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(projection="3d")

    ls3d = LightSource(azdeg=315, altdeg=35)
    face_rgb = ls3d.shade(
        np.ma.masked_invalid(Z), cmap=CMAP, norm=norm, blend_mode="soft",
        vert_exag=HILLSHADE_EXAG, dx=abs(transform.a), dy=abs(transform.e),
    )

    ax.plot_surface(X, Y, Z, facecolors=face_rgb, linewidth=0, antialiased=False,
                    shade=False, rcount=out_h, ccount=out_w)

    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(y.min(), y.max())
    ax.set_zlim(z_min, z_max)
    ax.set_box_aspect((np.ptp(X), np.ptp(Y), (z_max - z_min) * VERT_EXAG))
    ax.zaxis.set_major_locator(LinearLocator(8))
    ax.zaxis.set_major_formatter("{x:.0f}")
    ax.set_xlabel("X (m, polar stereographic)")
    ax.set_ylabel("Y (m, polar stereographic)")
    ax.set_zlabel("Height (m)")
    ax.set_title("Haworth crater (LOLA 5 m/px DEM)")

    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.5, aspect=5, label="Height (m)")

# ---------------- hillshade map ----------------
if SHOW_HILLSHADE:
    ls = LightSource(azdeg=315, altdeg=35)
    rgb = ls.shade(
        np.ma.masked_invalid(Z), cmap=CMAP, norm=norm, blend_mode="soft",
        vert_exag=HILLSHADE_EXAG, dx=abs(transform.a), dy=abs(transform.e),
    )

    fig2, ax2 = plt.subplots(figsize=(8, 8))
    ax2.imshow(rgb, extent=[x.min(), x.max(), y.min(), y.max()])
    ax2.set_xlabel("X (m)")
    ax2.set_ylabel("Y (m)")
    ax2.set_title("Hillshade (light from NW, %.1fx vertical exaggeration)" % HILLSHADE_EXAG)

    sm2 = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm2.set_array([])
    fig2.colorbar(sm2, ax=ax2, shrink=0.7, label="Height (m)")

plt.show()
'''
'''
import numpy as np
import matplotlib.pyplot as plt
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from matplotlib.colors import LightSource, LinearSegmentedColormap
from matplotlib.ticker import LinearLocator

# ---------------- settings ----------------
TIFF = "Haworth_final_adj_5mpp_surf.tif"
DOWNSAMPLE = 1        # 1 = full 5 m/px resolution (used for the hillshade map)
DOWNSAMPLE_3D = 10    # extra stride for the 3D surface only
VERT_EXAG = 1.0       # 3D box vertical scale; 1.0 = true scale
SHOW_3D = True
SHOW_HILLSHADE = True

# --- crop (square box) ---
CENTER = (-37500, 92000)         # (x, y) in meters (polar stereographic), or None to auto-detect
                      # the crater floor (centroid of the lowest 5% of the tile)
RADIUS_M = 2500      # crop half-width in meters (square box around CENTER)
CIRCULAR_MASK = False

# --- coloring ---
CLIP_PCT = (1, 99)         # color range percentiles (stops outliers saturating the ends)
SHADE_EXAG = 3.0           # vertical exaggeration used for shading only
SHADE_STRENGTH = 0.9       # 0 = flat color, 1 = strong relief shading
SUN_ALTITUDE = 35          # degrees above horizon
SUN_AZIMUTHS = (270, 315, 360)  # several light directions blended -> fewer hidden slopes
CONTOURS = True            # thin elevation contour lines on the hillshade map
# ------------------------------------------

# Rainbow topography colormap. Ends are deliberately NOT pure black/white,
# so shading detail stays visible on the lowest and highest ground.
CMAP = LinearSegmentedColormap.from_list("lunar_topo", [
    (0.00, "#2b1f6e"), (0.14, "#3b4fc4"), (0.28, "#2f93c2"), (0.42, "#33b7a0"),
    (0.56, "#7cc84a"), (0.68, "#e6df2e"), (0.80, "#f39a1f"), (0.90, "#dd4a26"),
    (1.00, "#b9a89c"),
])


def shaded_rgba(Zm, norm, dx, dy):
    """Elevation color multiplied by multi-direction hillshade (flat ground = pure color)."""
    valid = np.isfinite(Zm)
    Zf = np.where(valid, Zm, np.nanmean(Zm))
    flat = np.sin(np.radians(SUN_ALTITUDE))
    hs = np.mean([
        LightSource(azdeg=a, altdeg=SUN_ALTITUDE).hillshade(
            Zf, vert_exag=SHADE_EXAG, dx=dx, dy=dy)
        for a in SUN_AZIMUTHS
    ], axis=0)
    k = 1.0 + SHADE_STRENGTH * (hs / flat - 1.0)   # ~1 on flat ground
    rgba = CMAP(norm(np.where(valid, Zm, np.nan)))
    rgba[..., :3] = np.clip(rgba[..., :3] * k[..., None], 0, 1)
    rgba[~valid, 3] = 0.0
    return rgba


def nice_interval(span, target_lines=15):
    raw = span / target_lines
    for v in (2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if v >= raw:
            return v
    return 1000


with rasterio.open(TIFF) as src:
    print("Size (px):", src.width, "x", src.height)
    print("CRS:", src.crs)
    print("Nodata:", src.nodata)
    T = src.transform

    if CENTER is None:
        ch, cw = max(1, src.height // 50), max(1, src.width // 50)
        coarse = src.read(1, out_shape=(ch, cw), resampling=Resampling.average,
                          masked=True).astype("float64").filled(np.nan)
        ctf = T * T.scale(src.width / cw, src.height / ch)
        rr, cc = np.where(coarse <= np.nanpercentile(coarse, 5))
        cx = ctf.c + ctf.a * (cc.mean() + 0.5)
        cy = ctf.f + ctf.e * (rr.mean() + 0.5)
        print("Auto-detected center (m): x=%.0f, y=%.0f" % (cx, cy))
    else:
        cx, cy = CENTER

    col0 = max(0, int(np.floor((cx - RADIUS_M - T.c) / T.a)))
    col1 = min(src.width, int(np.ceil((cx + RADIUS_M - T.c) / T.a)))
    row0 = max(0, int(np.floor((cy + RADIUS_M - T.f) / T.e)))   # T.e is negative
    row1 = min(src.height, int(np.ceil((cy - RADIUS_M - T.f) / T.e)))
    win = Window(col0, row0, col1 - col0, row1 - row0)
    if win.width < 2 or win.height < 2:
        raise SystemExit("Crop window is empty - check CENTER / RADIUS_M against %s" % (src.bounds,))
    print("Crop window (px): cols %d-%d, rows %d-%d" % (col0, col1, row0, row1))

    out_h = max(1, int(win.height) // DOWNSAMPLE)
    out_w = max(1, int(win.width) // DOWNSAMPLE)
    data = src.read(1, window=win, out_shape=(out_h, out_w),
                    resampling=Resampling.average, masked=True)
    wtf = src.window_transform(win)
    transform = wtf * wtf.scale(win.width / out_w, win.height / out_h)

x = transform.c + transform.a * (np.arange(out_w) + 0.5)
y = transform.f + transform.e * (np.arange(out_h) + 0.5)
X, Y = np.meshgrid(x, y)
dx, dy = abs(transform.a), abs(transform.e)

Z = data.astype("float64").filled(np.nan)   # heights in meters, already relative to the sphere
if CIRCULAR_MASK:
    Z[(X - cx) ** 2 + (Y - cy) ** 2 > RADIUS_M ** 2] = np.nan

z_min, z_max = np.nanmin(Z), np.nanmax(Z)
vmin, vmax = np.nanpercentile(Z, CLIP_PCT)
norm = plt.Normalize(vmin=vmin, vmax=vmax)
print("Plotted grid:", Z.shape, "at", dx, "m/px")
print("Z range (m):", z_min, "to", z_max)
print("Color range (m):", vmin, "to", vmax)

# ---------------- 3D surface ----------------
if SHOW_3D:
    st = DOWNSAMPLE_3D
    Xs, Ys, Zs = X[::st, ::st], Y[::st, ::st], Z[::st, ::st]
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(projection="3d")

    ax.plot_surface(Xs, Ys, Zs, facecolors=shaded_rgba(Zs, norm, dx * st, dy * st),
                    linewidth=0, antialiased=False, shade=False,
                    rcount=Zs.shape[0], ccount=Zs.shape[1])

    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(y.min(), y.max())
    ax.set_zlim(z_min, z_max)
    ax.set_box_aspect((np.ptp(X), np.ptp(Y), (z_max - z_min) * VERT_EXAG))
    ax.zaxis.set_major_locator(LinearLocator(8))
    ax.zaxis.set_major_formatter("{x:.0f}")
    ax.set_xlabel("X (m, polar stereographic)")
    ax.set_ylabel("Y (m, polar stereographic)")
    ax.set_zlabel("Height (m)")
    ax.set_title("Haworth crater (LOLA 5 m/px DEM)")
    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.5, aspect=5, label="Height (m)")

# ---------------- hillshade map ----------------
if SHOW_HILLSHADE:
    fig2, ax2 = plt.subplots(figsize=(8, 8))
    ax2.imshow(shaded_rgba(Z, norm, dx, dy), extent=[x.min(), x.max(), y.min(), y.max()])

    if CONTOURS:
        step = max(1, Z.shape[0] // 600)          # keep contouring fast at full res
        iv = nice_interval(vmax - vmin)
        levels = np.arange(np.floor(vmin / iv) * iv, vmax + iv, iv)
        ax2.contour(X[::step, ::step], Y[::step, ::step], Z[::step, ::step],
                    levels=levels, colors="k", linewidths=0.3, alpha=0.35)
        print("Contour interval: %g m" % iv)

    ax2.set_xlabel("X (m)")
    ax2.set_ylabel("Y (m)")
    ax2.set_title("Haworth hillshade (multi-direction light, %.0fx shading exaggeration)" % SHADE_EXAG)
    sm2 = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm2.set_array([])
    fig2.colorbar(sm2, ax=ax2, shrink=0.7, label="Height (m)")

plt.show()
'''
import numpy as np
import matplotlib.pyplot as plt
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from matplotlib.colors import LightSource, LinearSegmentedColormap
from matplotlib.ticker import LinearLocator

# --- saving ---
SAVE_PNG = True            # save the figures as PNG files next to the script
OUTPUT_PREFIX = "haworth"  # -> haworth_hillshade.png, haworth_hillshade_raw.png, haworth_3d.png
PNG_DPI = 300              # resolution of the saved figures (with axes, colorbar, title)
SAVE_RAW_MAP = True        # also save the bare shaded map, one image pixel per DEM pixel
SHOW_WINDOWS = True        # False = just save, don't open plot windows

# ---------------- settings ----------------
TIFF = "Haworth_final_adj_5mpp_surf.tif"
FULL_TILE = True      # True = whole DEM (ignores CENTER / RADIUS_M); False = square crop
DOWNSAMPLE = 2        # 1 = full 5 m/px. The full 5960x5960 tile needs several GB of RAM at 1
DOWNSAMPLE_3D = 20    # extra stride for the 3D surface only (full tile: 20 -> ~150 cells/side)
VERT_EXAG = 1.0       # 3D box vertical scale; 1.0 = true scale
SHOW_3D = True
SHOW_HILLSHADE = True

# --- crop (only used when FULL_TILE = False) ---
CENTER = (-40000, 90000)   # (x, y) in meters, or None to auto-detect the lowest area
RADIUS_M = 12000           # half-width of the square crop in meters
CIRCULAR_MASK = False

# --- coloring ---
STYLE = "parula"           # "parula":  MATLAB-style indigo -> blue -> teal -> green -> yellow
                           #            (matches the Sun-visibility map you sent)
                           # "classic": black -> white rainbow with soft-blended shading
                           # "refined": trimmed rainbow, multi-direction shading, contours
CLIP_PCT = (2, 98) if STYLE == "classic" else (1, 99)
CONTOURS = STYLE == "refined"
SHADE_EXAG = 2.0 if STYLE == "classic" else 3.0   # vertical exaggeration used for shading only
SHADE_STRENGTH = 0.5 if STYLE == "parula" else 0.9   # 0 = pure colors (no shading), 1 = strong
                                                     # (used by "parula" and "refined")
SUN_ALTITUDE = 35          # degrees above horizon
SUN_AZIMUTHS = (270, 315, 360)   # "refined" only; classic uses a single light from the NW (315)
# ------------------------------------------

CLASSIC_CMAP = LinearSegmentedColormap.from_list("lunar_topo_classic", [
    (0.00, "#000000"), (0.10, "#2a1a6b"), (0.20, "#3b4cc0"), (0.30, "#2f8fb8"),
    (0.40, "#2fb5a0"), (0.50, "#5cc43a"), (0.60, "#e8e22a"), (0.70, "#f39a1f"),
    (0.80, "#e0301e"), (0.90, "#8c6a5a"), (1.00, "#ffffff"),
])
# Same rainbow, but the ends are not pure black/white so shading stays visible there
REFINED_CMAP = LinearSegmentedColormap.from_list("lunar_topo_refined", [
    (0.00, "#2b1f6e"), (0.14, "#3b4fc4"), (0.28, "#2f93c2"), (0.42, "#33b7a0"),
    (0.56, "#7cc84a"), (0.68, "#e6df2e"), (0.80, "#f39a1f"), (0.90, "#dd4a26"),
    (1.00, "#b9a89c"),
])
# MATLAB "parula" (approximated from its standard anchor colors) - the colormap in the
# Average Sun visibility map: dark indigo at the low end, yellow at the high end
PARULA_CMAP = LinearSegmentedColormap.from_list("parula", [
    (0.2422, 0.1504, 0.6603), (0.2810, 0.3228, 0.9579), (0.1786, 0.5289, 0.9682),
    (0.0689, 0.6948, 0.8394), (0.2161, 0.7843, 0.5923), (0.6720, 0.7793, 0.2227),
    (0.9970, 0.7659, 0.2199), (0.9769, 0.9839, 0.0805),
], N=256)
CMAP = {"parula": PARULA_CMAP, "classic": CLASSIC_CMAP, "refined": REFINED_CMAP}[STYLE]


def shaded_rgba(Zm, norm, dx, dy):
    valid = np.isfinite(Zm)
    if STYLE == "classic":
        ls = LightSource(azdeg=315, altdeg=SUN_ALTITUDE)
        return ls.shade(np.ma.masked_invalid(Zm), cmap=CMAP, norm=norm, blend_mode="soft",
                        vert_exag=SHADE_EXAG, dx=dx, dy=dy)
    Zf = np.where(valid, Zm, np.nanmean(Zm))
    flat = np.sin(np.radians(SUN_ALTITUDE))
    hs = np.mean([
        LightSource(azdeg=a, altdeg=SUN_ALTITUDE).hillshade(
            Zf, vert_exag=SHADE_EXAG, dx=dx, dy=dy)
        for a in SUN_AZIMUTHS
    ], axis=0)
    k = 1.0 + SHADE_STRENGTH * (hs / flat - 1.0)
    rgba = CMAP(norm(np.where(valid, Zm, np.nan)))
    rgba[..., :3] = np.clip(rgba[..., :3] * k[..., None], 0, 1)
    rgba[~valid, 3] = 0.0
    return rgba


def nice_interval(span, target_lines=15):
    raw = span / target_lines
    for v in (2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if v >= raw:
            return v
    return 1000


with rasterio.open(TIFF) as src:
    print("Size (px):", src.width, "x", src.height)
    print("CRS:", src.crs)
    print("Nodata:", src.nodata)
    print("Bounds:", src.bounds)
    print("tags:", src.tags())
    print("res:", src.res)

    T = src.transform

    if FULL_TILE:
        cx = (src.bounds.left + src.bounds.right) / 2
        cy = (src.bounds.bottom + src.bounds.top) / 2
        win = Window(0, 0, src.width, src.height)
    else:
        if CENTER is None:
            ch, cw = max(1, src.height // 50), max(1, src.width // 50)
            coarse = src.read(1, out_shape=(ch, cw), resampling=Resampling.average,
                              masked=True).astype("float64").filled(np.nan)
            ctf = T * T.scale(src.width / cw, src.height / ch)
            rr, cc = np.where(coarse <= np.nanpercentile(coarse, 5))
            cx = ctf.c + ctf.a * (cc.mean() + 0.5)
            cy = ctf.f + ctf.e * (rr.mean() + 0.5)
            print("Auto-detected center (m): x=%.0f, y=%.0f" % (cx, cy))
        else:
            cx, cy = CENTER
        col0 = max(0, int(np.floor((cx - RADIUS_M - T.c) / T.a)))
        col1 = min(src.width, int(np.ceil((cx + RADIUS_M - T.c) / T.a)))
        row0 = max(0, int(np.floor((cy + RADIUS_M - T.f) / T.e)))   # T.e is negative
        row1 = min(src.height, int(np.ceil((cy - RADIUS_M - T.f) / T.e)))
        win = Window(col0, row0, col1 - col0, row1 - row0)
        if win.width < 2 or win.height < 2:
            raise SystemExit("Crop window is empty - check CENTER / RADIUS_M against %s" % (src.bounds,))
    print("Window (px): cols %d-%d, rows %d-%d" % (win.col_off, win.col_off + win.width,
                                                  win.row_off, win.row_off + win.height))

    out_h = max(1, int(win.height) // DOWNSAMPLE)
    out_w = max(1, int(win.width) // DOWNSAMPLE)
    data = src.read(1, window=win, out_shape=(out_h, out_w),
                    resampling=Resampling.average, masked=True)
    #data = src.read(1)
    print(type(data))
    print(data.shape)
    wtf = src.window_transform(win)
    transform = wtf * wtf.scale(win.width / out_w, win.height / out_h)

x = transform.c + transform.a * (np.arange(out_w) + 0.5)
y = transform.f + transform.e * (np.arange(out_h) + 0.5)
X, Y = np.meshgrid(x, y)
dx, dy = abs(transform.a), abs(transform.e)

Z = data.astype("float64").filled(np.nan)   # heights in meters, already relative to the sphere
del data
if CIRCULAR_MASK and not FULL_TILE:
    Z[(X - cx) ** 2 + (Y - cy) ** 2 > RADIUS_M ** 2] = np.nan

z_min, z_max = np.nanmin(Z), np.nanmax(Z)
vmin, vmax = np.nanpercentile(Z, CLIP_PCT)
norm = plt.Normalize(vmin=vmin, vmax=vmax)
print("Plotted grid:", Z.shape, "at", dx, "m/px")
print("Z range (m):", z_min, "to", z_max)
print("Color range (m):", vmin, "to", vmax)

# ---------------- 3D surface ----------------
if SHOW_3D:
    st = DOWNSAMPLE_3D
    Xs, Ys, Zs = X[::st, ::st], Y[::st, ::st], Z[::st, ::st]
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(projection="3d")

    ax.plot_surface(Xs, Ys, Zs, facecolors=shaded_rgba(Zs, norm, dx * st, dy * st),
                    linewidth=0, antialiased=False, shade=False,
                    rcount=Zs.shape[0], ccount=Zs.shape[1])

    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(y.min(), y.max())
    ax.set_zlim(z_min, z_max)
    ax.set_box_aspect((np.ptp(X), np.ptp(Y), (z_max - z_min) * VERT_EXAG))
    ax.zaxis.set_major_locator(LinearLocator(8))
    ax.zaxis.set_major_formatter("{x:.0f}")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Height (m)")
    ax.set_title("Haworth tile (LOLA 5 m/px DEM)")
    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm.set_array([])
    fig.colorbar(sm, ax=ax, shrink=0.5, aspect=5, label="Height (m)")

# ---------------- hillshade map ----------------
if SHOW_HILLSHADE:
    fig2, ax2 = plt.subplots(figsize=(8, 8))
    ax2.imshow(shaded_rgba(Z, norm, dx, dy), extent=[x.min(), x.max(), y.min(), y.max()])

    if CONTOURS:
        step = max(1, Z.shape[0] // 600)
        iv = nice_interval(vmax - vmin)
        levels = np.arange(np.floor(vmin / iv) * iv, vmax + iv, iv)
        ax2.contour(X[::step, ::step], Y[::step, ::step], Z[::step, ::step],
                    levels=levels, colors="k", linewidths=0.3, alpha=0.35)
        print("Contour interval: %g m" % iv)

    ax2.set_xlabel("X (m)")
    ax2.set_ylabel("Y (m)")
    ax2.set_title("Haworth Tile Lunar DEM")
    sm2 = plt.cm.ScalarMappable(cmap=CMAP, norm=norm)
    sm2.set_array([])
    fig2.colorbar(sm2, ax=ax2, shrink=0.7, label="Height (m)")

if SAVE_PNG:
    if SHOW_3D:
        fig.savefig(OUTPUT_PREFIX + "_3d.png", dpi=PNG_DPI, bbox_inches="tight")
        print("Saved", OUTPUT_PREFIX + "_3d.png")
    if SHOW_HILLSHADE:
        fig2.savefig(OUTPUT_PREFIX + "_hillshade.png", dpi=PNG_DPI, bbox_inches="tight")
        print("Saved", OUTPUT_PREFIX + "_hillshade.png")

plt.show()