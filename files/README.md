# Lunar Site Planner

A tkinter tool for placing a gNB and a UE on a lunar terrain image and exporting OAI configuration files for the BICTR channel model (`bictr_channel.c`).

**What it does:** pick a site, click the image to place the gNB and UE, set antenna heights, and export `gnb...bictr.conf` and `ue.bictr.conf` with the correct longitude, latitude, height, body radius and DEM path filled in.

**What it does not do:** run the simulation, read or edit `.bdem` files, or write logs.

---

## 1. Requirements

| Requirement | Notes |
|---|---|
| Python 3.7 or newer | |
| tkinter | Included with Python on Windows and macOS. On Debian/Ubuntu: `sudo apt install python3-tk` |
| Pillow | `pip install pillow`. On Debian/Ubuntu, if you get an `ImageTk` error: `sudo apt install python3-pil.imagetk` |

Check your setup:

```
python -c "import tkinter, PIL; print('OK')"
```

---

## 2. Folder structure

```
lunar_site_planner/
├── lunar_site_planner.py     the application
├── README.md                 this file
└── sites/                    required: the app reads its data from here
    ├── sites.csv             required: the site list (site centres)
    ├── site01.png            one terrain image per site
    ├── site01.bdem           one elevation raster per site
    └── ...
```

The app finds the `sites/` folder relative to the script, so you can launch it from any directory.

Two other folders are chosen while the app is running:

| Folder | Required? | Purpose |
|---|---|---|
| OAI template folder, normally `targets/PROJECTS/GENERIC-NR-5GC/CONF/` | Optional | Source of `gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf` and `ue.bictr.conf`, which the app updates |
| Output folder | Required at export | The parent folder for exports. Each export creates a new date/time-stamped subfolder inside it |

---

## 3. Setup

1. Install the requirements above.
2. Put the PNG and `.bdem` file for each site in `sites/`. (The `.bdem` terrain data is not in git; copy it from your local `bictr_terrain/` folder. A `.bdem` outside `sites/` also works if you give a relative path such as `../bictr_terrain/lunar_south_pole.bdem` in the `bdem` column of `sites.csv`.)
3. Put your site table in `sites/sites.csv` (see below).

### sites.csv

One row per site, with a header row. The provided file holds the 22 Artemis III candidate regions (NASA 2022 and 2024 lists):

```
id,name,list,lat_deg,lon_deg,coord_source
01,Faustini Rim A,NASA 2022 (13 regions),-87.86,90.00,LPSC 2024 #1775 Table 1 (region centre)
```

| Column | Required? | Meaning |
|---|---|---|
| `lat_deg`, `lon_deg` | Yes (unless edge columns are given) | Site centre in degrees, east-positive longitude |
| `id` | One of `id` / `name` | Site number; shown in the dropdown and used to find the files |
| `name` | One of `id` / `name` | Site name; shown in the dropdown |
| `lon_min`, `lon_max`, `lat_min`, `lat_max` | No | Explicit tile edges. If all four are present they are used instead of the computed box |
| `png` | No | PNG file name, relative to `sites/`. If absent, the file is found by id (see below) |
| `bdem` | No | `.bdem` file name or relative path, relative to `sites/`. If absent, found by id |
| `list`, `coord_source` | No | Ignored by the app |

**How the tile edges are computed from the centre.** Each tile is a longitude/latitude box spanning ±10 km around the centre:
- Latitude half-width = 10 km as an arc on the 1,737.4 km Moon sphere, which is about 0.330°.
- Longitude half-width = the same 10 km measured at the centre's latitude, `10 km / (R · cos(lat))`. Near the pole this is wide: Connecting Ridge (03) spans 70.0° of longitude, matching your notes.

The ±10 km half-width is `TILE_HALF_WIDTH_M` at the top of `lunar_site_planner.py`. The app rejects any row whose tile would cross the ±180° seam or the pole, because `bictr_channel.c` has no wrap-around handling (none of the 22 do).

**How files are found.** If the CSV has no `png` or `bdem` column, the app looks in `sites/` for a file matching the site id, case-insensitively. For id `01` these all work: `01.png`, `1.png`, `site01.png`, `site_01_faustini.png`, and likewise for `.bdem`. If none is found, it expects `01.png` / `01.bdem` and reports the missing file. If your files are named differently, add `png` and `bdem` columns.

**Header names are matched loosely.** Case, spaces and dashes are ignored, and alternatives such as `lat`/`lon`, `latitude`/`longitude`, `west`/`east`/`south`/`north` and `dem_file` are accepted. The full list is `CSV_ALIASES` in `lunar_site_planner.py`.

Numbers may use a true minus sign (`−`) or a degree sign (`°`). Longitudes must be east-positive.

If there is no `sites.csv`, the app falls back to a `sites/sites.json` file with a `"sites"` list of `name`, `png`, `bdem` and the four edge fields.

**Important image requirement:** each PNG must be a north-up longitude/latitude box that covers exactly the tile edges (the explicit ones, or the ±10 km box computed above). The app converts a click to coordinates by linear interpolation between those bounds. If the image uses a different projection or the bounds are wrong, the exported coordinates will be wrong with no warning.

---

## 4. Running

```
python lunar_site_planner.py
```

### Using the window

1. **Site:** choose a site from the dropdown. Its image appears. If the `.bdem` file is not found, the status line shows a warning.
2. **Place:** select **gNB** or **UE**, then click on the image. The marker moves if you click again or drag. Clicks outside the image are rejected, so both points always stay inside the terrain tile.
3. **Heights:** enter the gNB and UE antenna heights in metres (default 2.0).
4. **Readout:** the side panel shows the longitude and latitude of each marker and the separation between them in metres.
5. **Template folder (optional):** click *Set OAI CONF template folder* and choose the folder containing the two template `.conf` files.
6. **Export:** click *Export gNB + UE configs...* and choose an output folder.
7. **Clear markers** removes both markers.

---

## 5. Outputs

Each export creates a new subfolder inside the output folder you choose, named after the site and the date and time, for example:

```
my_exports/
└── 01_Faustini_Rim_A_2026-10-23_14-30-05/
    ├── gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf
    └── ue.bictr.conf
```

The format is `<id>_<site_name>_<YYYY-MM-DD>_<HH-MM-SS>` using the computer's local time. Nothing is overwritten: if two exports happen in the same second, the second folder gets a `_2` suffix. Every export contains two files:

- `gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf`
- `ue.bictr.conf`

Each file contains both model entries, with TX and RX swapped between them:

| Entry | TX | RX |
|---|---|---|
| `rfsimu_channel_enB0` | gNB | UE |
| `rfsimu_channel_ue0` | UE | gNB |

Each entry contains:

| Parameter | Value |
|---|---|
| `bictr_tx_lon`, `bictr_tx_lat`, `bictr_tx_height` | Transmitter position (degrees, degrees, metres) |
| `bictr_rx_lon`, `bictr_rx_lat`, `bictr_rx_height` | Receiver position |
| `bictr_body_radius` | 1737400 (metres, the Moon) |
| `bictr_dem_file` | Absolute path to the site's `.bdem` |

**With a template folder:** the values above are written into the template, and the rest of the file is unchanged. If a template lacks one of the blocks or keys, a complete block is appended to the end of the file instead, so check the result for duplicate blocks.

**Without a template folder:** each file contains only the two model entries, for you to paste into your OAI config.

The `bictr_dem_file` path is absolute for the machine where you ran the tool. If the simulation runs elsewhere, edit that line.

---

## 6. Using the exported files

1. Copy the two files into `targets/PROJECTS/GENERIC-NR-5GC/CONF/` of your OAI tree (if you did not export there directly).
2. Check that `bictr_dem_file` points to a readable `.bdem` on the simulation machine. An empty or unreadable path makes the simulator fall back to flat terrain with only a warning.
3. Run OAI as usual. In the simulator log, check the `dist=` and `h=` values against what you expect.

---

## 7. Notes on the physics

- 0.001° of latitude is about 30 m on the Moon. Longitude spacing shrinks with cos(latitude).
- Both points must be inside the DEM bounds. Out-of-bounds lookups silently return 0 m elevation, which is why the app restricts clicks to the image.
- The DEM resolution limits how finely terrain shadowing is resolved, so very small moves mostly change interpolated heights.
- The model places reflectors automatically around the receiver. The tool does not set them.
- The displayed separation is a great-circle distance on the 1,737.4 km reference sphere. It does not include height differences.

---

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'tkinter'` | Install tkinter (see Requirements) |
| `ModuleNotFoundError: No module named 'PIL'` | `pip install pillow` |
| Dialog "Could not read the site list" | `sites/sites.csv` is missing, a row has a non-numeric latitude/longitude, or the centre columns (`lat_deg`, `lon_deg`) could not be found. The message lists the headers that were found |
| Dialog says a tile crosses the seam or the pole | A centre is too close to ±180° longitude or to the pole for a ±10 km box. Give explicit edge columns for that row, or use a smaller `TILE_HALF_WIDTH_M` |
| "Cannot open ...png" | No file in `sites/` matches the site id (and there is no `png` column value) or it does not match a file in `sites/` or the file is not a valid image |
| Status shows "WARNING: .bdem file not found" | No `.bdem` in `sites/` matches the site id (and there is no `bdem` column value), or the terrain data has not been copied. Export still works after confirming, but the simulator will use flat terrain |
| Export asks to place both points | Place a gNB and a UE marker first |
| Coordinates look wrong | The PNG is not a north-up lon/lat box, or its extent differs from the computed ±10 km tile (check `TILE_HALF_WIDTH_M`, or add explicit edge columns) |
| Exported file has a duplicated block | The template's block or one of its keys did not match, so a fresh block was appended. Remove the old block |

---

## 9. Known limitations and not yet built

- Terrain elevation at each marker is not shown.
- No flat-terrain (A/B) config export.
- No reflector placement control.
- No custom export names; folders are named automatically by site and time.
- The window has been written but not yet tested on screen; please report any display problems.
