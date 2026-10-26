# Lunar Site Planner (v2)

Opens on a shaded-relief atlas of the lunar south pole. Click a region marker to open that region's terrain map, click to place the gNB and UE, then export OAI configuration files for the BICTR channel model (`bictr_channel.c`).

**Does:** atlas view with a minimap that highlights the open region, region view, click-to-coordinates, gNB and UE placement by click or typed coordinates, per-region default gNB locations, antenna heights, dated config export, and a single block of colour settings.
**Does not:** run the simulation, edit terrain data, or convert `.tif` to `.bdem`.

---

## 1. Requirements

| Requirement | Notes |
|---|---|
| Python 3.8 or newer | |
| tkinter | Included on Windows and macOS. Debian/Ubuntu: `sudo apt install python3-tk` |
| Pillow and numpy | `pip install pillow numpy` (no GDAL or rasterio needed) |

Check: `python -c "import tkinter, PIL, numpy; print('OK')"`

---

## 2. Folder structure

```
lunar_site_planner/
├── lunar_site_planner.py
├── README.md
├── sites.csv                                  site list (provided)
├── gnb_defaults.csv                           saved default gNB per region (created/updated by the app)
│
├── atlas_v2/bundle/context/                   from lunarrf_atlas_context_v2.0.tar
│   ├── pole_dem_160m.tif                      the opening atlas
│   └── regions/
│       ├── Haworth__dem.tif                   one per region (12 in this release)
│       └── ...
│
├── data/atlas_base/
│   └── candidates_freeze.csv                  optional: candidate masts overlay
│
├── terrain/                                   YOUR .bdem files (not in the Zenodo record)
│   └── lunar_south_pole.bdem  (or per-region files)
│
└── exports/                                   created automatically
    └── Haworth_2026-10-26_14-30-05/
        ├── gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf
        └── ue.bictr.conf
```

---

## 3. Setup

Run these inside the `lunar_site_planner/` folder so the archives' own paths land in the right place:

```
tar xf lunarrf_atlas_context_v2.0.tar
tar xf lunarrf_candidates_v2.0.tar data/atlas_base/candidates_freeze.csv
```

Then put your `.bdem` file(s) in `terrain/`.

Only these two archives are needed (about 174 MB). The mosaics, 20 m regions, `sideruns` and `validation` archives are not used.

### sites.csv

Columns used: `id`, `name`, `lat_deg`, `lon_deg` (centre of each NASA candidate region; other columns are ignored). A site's region file is found from its name: parentheses are dropped and spaces become underscores, so `de Gerlache Rim 2 (2024)` opens `regions/de_Gerlache_Rim_2__dem.tif`.

- `Leibnitz Beta Plateau` is treated as `Mons_Mouton` (same massif); see `REGION_ALIASES` in the script.
- Sites with no region tile in the atlas (02 Peak Near Shackleton, 04 Connecting Ridge Extension, 05 de Gerlache Rim 1, 07 de Gerlache-Kocher Massif) are hidden by default. To show them as grey, unclickable markers, set `SHOW_SITES_WITHOUT_TILE = True` near the top of `lunar_site_planner.py`. You can also delete their rows from `sites.csv`.
- Sites that share a region (for example Haworth 2022 and 2024) show as one marker.

### The .bdem files

The Zenodo record contains no `.bdem` files. The app looks in `terrain/` for:

1. a `.bdem` whose file name contains the region name (for example `Haworth_20m.bdem`), otherwise
2. `lunar_south_pole.bdem`, otherwise
3. it warns that no `.bdem` was found.

The exported `bictr_dem_file` is the absolute path of the file found. If the file does not cover the area you clicked, the simulator would silently read 0 m elevation, so check that your `.bdem` covers the region.

---

## 4. Running

```
python lunar_site_planner.py
```

1. **Atlas:** the pole map opens with amber markers for regions that have terrain tiles. Click one (or choose it in the dropdown) to open it. A small atlas **minimap** at the top of the side panel always shows where you are: the open region's footprint is boxed (cyan) and labelled with its name. The same box and bold name are drawn on the full atlas when you go back. Regions with a saved default gNB are tagged `[gNB]`.
2. **Place the gNB and the UE.** Each has its own group in the side panel, and each can be set either way:
   - **Click or drag on the map.** Choose the node with *Place by clicking the map*, then click. The lon/lat boxes fill in as you click or drag.
   - **Type coordinates.** Enter longitude and latitude in that node's boxes and press **Place** or Enter. The marker appears on the map and that node becomes the active one for map clicks. Clicking into a node's lon/lat box also makes it the active node.

   Clicks or typed positions outside the region's map are rejected.
3. **Heights:** each node has a height box: gNB 4.0 m and UE 1.5 m by default (the atlas `mast_height_m` and `rx_height_m`).
4. **Default gNB (optional):** see section 5.
5. **Separation** between the two nodes is shown under the groups.
6. **Candidate masts (optional):** tick *Show atlas candidate masts* to overlay the atlas's candidate transmitter positions (orange = ridge, green = landing site) as a guide for placement.
7. **Export:** optionally set the OAI `CONF` template folder, then click *Export* and choose a parent folder. A new subfolder named `<Region>_<YYYY-MM-DD>_<HH-MM-SS>` is created.
8. **Back to atlas** returns to the pole view.

---

## 5. Default gNB locations

Each region can have its own default gNB, which is placed automatically whenever you open that region (its height too, if saved). Set it in either way:

Place the gNB (by clicking, or by typing its longitude and latitude and pressing **Place**), set its height if you want it saved too, then press **Save gNB as default**. The values in the gNB boxes are what get saved.

**Clear default** removes the saved one for the open region. **Clear markers** removes the markers for this visit only; re-select the region in the dropdown to bring the default back.

Defaults are stored in `gnb_defaults.csv` and can also be edited by hand:

```
region,lon,lat,height_m
Haworth,-23.700000,-86.740000,4.5
```

`region` is the region file name without `__dem.tif` (for example `Haworth`, `Peak_near_Cabeus_B`). Defaults belong to the region, so sites that share a tile (for example Haworth 2022 and 2024) share one default. `height_m` may be left empty. A default that lies outside its tile is ignored with a note in the status line.

---

## 6. Changing the look of the interface

All colours and the font size are in one block, `THEME`, near the top of `lunar_site_planner.py` (section 1, just above the paths). Edit a value, save, and restart the app.

| Key | What it controls |
|---|---|
| `font_size` | Text size everywhere in the side panel and on map labels |
| `panel_bg`, `text`, `muted`, `border` | Side panel background, normal text, status text, outlines |
| `entry_bg`, `button_bg`, `button_active` | Input boxes and buttons (normal and under the cursor) |
| `canvas_bg` | Background around the maps |
| `label_bg`, `label_fg` | Dark plate behind every map label, and the label text |
| `label_focus_fg` | Name of the region you are in or last opened |
| `missing_fg` | Sites with no terrain tile |
| `marker`, `marker_outline` | Region markers on the atlas |
| `footprint` | Box showing the open region's extent on the atlas and minimap |
| `gnb`, `ue` | gNB and UE markers and their panel headings |
| `cand_ridge`, `cand_landing` | Candidate mast dots |

Colours are hex codes such as `"#ffffff"`. Map labels sit on dark plates so they stay readable over any shading. The default panel text colours have a contrast ratio of at least 4.5:1 against their backgrounds. The layout (which widgets appear where) is in `_build_widgets` in section 6 of the script.

---

## 7. Outputs

Each export folder holds `gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf` and `ue.bictr.conf`. Both contain both model entries with TX and RX swapped:

| Entry | TX | RX |
|---|---|---|
| `rfsimu_channel_enB0` | gNB | UE |
| `rfsimu_channel_ue0` | UE | gNB |

Each entry has `bictr_tx_lon/lat/height`, `bictr_rx_lon/lat/height`, `bictr_body_radius` (1737400) and `bictr_dem_file`.

- **With a template folder:** the values are written into the template; the rest of the file is unchanged. If a block or key doesn't match, a full block is appended instead, so check for duplicates.
- **Without a template folder:** the files contain only the two model entries, to paste into your OAI config.

---

## 8. How coordinates are computed

The atlas maps use a south polar stereographic projection on the 1,737.4 km Moon sphere (origin at the pole, central meridian 0). The app reads each GeoTIFF's own georeference, converts the click to projected metres, then inverts the projection to longitude (east-positive) and latitude. This was checked against all 11,827 rows of `candidates_freeze.csv` and matched to machine precision.

Region tiles are assumed to use the same projection as the pole map. If a region file has no GeoTIFF tags, the app reports an error rather than guessing.

---

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "Atlas map not found" | `atlas_v2/bundle/context/pole_dem_160m.tif` is missing. Extract the context archive inside this folder |
| "no GeoTIFF georeference tags" | The `.tif` lacks standard GeoTIFF tags. Tell me which file |
| Cannot read a `.tif` | Pillow may not support its compression. Send me the `gdalinfo` output |
| Atlas opens but has no markers | No `__dem.tif` files in `regions/`, or `sites.csv` names don't match them |
| Status shows "no .bdem found" | Add a `.bdem` to `terrain/` (see section 3) |
| Candidate checkbox is greyed out | `data/atlas_base/candidates_freeze.csv` is missing |
| Default gNB not placed | The note in the status line says why: usually the saved position is outside the region's map, or the region name in `gnb_defaults.csv` doesn't match the file name |
| Typed coordinates are rejected | They are outside the open region's map, or not numbers. Longitude is east-positive degrees |
| Slow first load | The pole map is 3800 x 3800 pixels; it is shaded once, then cached |

---

## 10. Limitations

- The GUI has not been run on screen by me; the data logic was tested on synthetic GeoTIFFs matching your `gdalinfo`. Please report any display problems.
- The region tiles' georeference and the `.bdem` coverage are unverified (no real files were available).
- No terrain-elevation readout at the markers, and no flat-terrain (A/B) export.
- Separation is a great-circle distance on the reference sphere, ignoring heights.
