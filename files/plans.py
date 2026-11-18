"""Site plans and bulk-run folders for the Lunar Site Planner / RFSim frontend.

No Qt, no numpy, no Pillow. Only the standard library plus export.py and settings.py.

A *site plan* is one saved gNB + UE placement (a small JSON file in PLANS_DIR). The planner
writes them; the RFSim GUI lists them, and a bulk run sweeps MCS x SINR over the chosen plans.

Contents:
  - save_plan, load_plans, delete_plan     site plan files
  - parse_mcs, sinr_points                 sweep inputs
  - make_bulk_run                          timestamped folder: raw/ + data/ + manifest.json
  - build_queue, write_run_confs, append_row   what the sequential runner needs per run
"""
import json
import os
import shutil
from datetime import datetime

# package layout: use `from .export import ...` and `from .settings import ...`
import csv
import re

from catalog import find_bdem
from export import export_configs, fill_block, make_run_folder, run_folder_name
from settings import (BLOCK_GNB_SIDE, BLOCK_UE_SIDE, BULK_DL_GAIN_DB, BULK_NOISE_AT_0DB_SINR,
                      BULK_NOISE_KEY, GNB_CONF, LINK_MAX_ABS_TA, LINK_MIN_RSRP_DB,
                      PLANS_DIR, TEMPLATE_DIR, UE_CONF)

MCS_MIN, MCS_MAX = 0, 28             # NR MCS index range (table 1: 0-28; 256QAM table: 0-27)
RAW_TEMPLATE_KEY = "raw_template"   # bulk "plan" used when no site plan is ticked: the templates as they are
DATA_COLUMNS = ["plan", "mcs", "target_sinr_db", "link", "dl_bler", "ul_bler", "ul_snr_db",
                "ul_dtx_frac", "max_abs_ta", "rsrp_db", "timestamp"]
LINK_OK = "ok"                       # the only "link" value bulk_plot plots


# ----------------------------------------------------------------------------
# Site plans
# ----------------------------------------------------------------------------
def save_plan(name, region_stem, region_label, gnb, ue, gnb_h, ue_h, bdem, separation_m,
              folder=PLANS_DIR):
    """Write one plan as JSON. gnb / ue are (lon, lat). Returns the file path."""
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, run_folder_name(name))
    path, n = base + ".json", 1
    while os.path.exists(path):
        n += 1
        path = f"{base}_{n}.json"
    plan = {
        "name": name, "region": region_stem, "region_label": region_label,
        "gnb": {"lon": gnb[0], "lat": gnb[1], "height_m": gnb_h},
        "ue": {"lon": ue[0], "lat": ue[1], "height_m": ue_h},
        "bdem": bdem, "separation_m": round(separation_m, 1),
        "saved": datetime.now().isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    return path


def load_plans(folder=PLANS_DIR):
    """All readable plans, oldest first. Each dict gets a 'file' key; bad files are skipped."""
    plans = []
    if os.path.isdir(folder):
        for fname in sorted(os.listdir(folder)):
            if not fname.lower().endswith(".json"):
                continue
            path = os.path.join(folder, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    plan = json.load(f)
                plan["gnb"]["lon"], plan["ue"]["height_m"], plan["name"], plan["bdem"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            plan["file"] = path
            plans.append(plan)
    return plans


def delete_plan(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Sweep inputs
# ----------------------------------------------------------------------------
def parse_mcs(text, lo=MCS_MIN, hi=MCS_MAX):
    """'0-5, 9, 12-14' -> [0, 1, 2, 3, 4, 5, 9, 12, 13, 14]. Raises ValueError on bad input."""
    out = set()
    for token in text.replace(";", ",").replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        a, sep, b = token.partition("-")
        try:
            first, last = int(a), int(b) if sep else int(a)
        except ValueError:
            raise ValueError(f"'{token}' is not an MCS index or range") from None
        if first > last:
            raise ValueError(f"range '{token}' runs backwards")
        if first < lo or last > hi:
            raise ValueError(f"MCS must be between {lo} and {hi} (got '{token}')")
        out.update(range(first, last + 1))
    if not out:
        raise ValueError("enter at least one MCS index")
    return sorted(out)


def sinr_points(lo, hi, step):
    """Target SINR values lo, lo+step, ... up to hi inclusive (dB)."""
    if step <= 0:
        raise ValueError("SINR step must be greater than zero")
    if hi < lo:
        raise ValueError("SINR maximum is below the minimum")
    n = int((hi - lo) / step + 1e-9)
    return [round(lo + i * step, 6) for i in range(n + 1)]


_CENTER_RE = re.compile(r"^\s*(-?\d+(?:\.\d*)?)\s*(?:dB)?\s*$", re.IGNORECASE)


def parse_mcs_centers(text):
    """MCS -> centre SINR pairs: '9: 5; 12: 8.5; 20-21: 14' -> {9: 5.0, 12: 8.5, 20: 14.0, 21: 14.0}.
    Entries are separated by ';' or new lines; each is '<MCS>: <centre SINR dB>', where the MCS
    part takes the same forms as parse_mcs (one index, a list or a range). An MCS listed twice
    keeps its last centre. Raises ValueError."""
    out = {}
    for entry in re.split(r"[;\n]", text or ""):
        if not entry.strip():
            continue
        mcs_text, sep, center_text = entry.partition(":")
        m = _CENTER_RE.match(center_text) if sep else None
        if not m:
            raise ValueError(f"MCS/centre SINR '{entry.strip()}': expected '<MCS>: <centre SINR dB>'")
        try:
            mcs_list = parse_mcs(mcs_text)
        except ValueError as err:
            raise ValueError(f"MCS/centre SINR '{entry.strip()}': {err}") from None
        for mcs in mcs_list:
            out[mcs] = float(m.group(1))
    if not out:
        raise ValueError("enter at least one MCS: centre SINR pair, e.g. 9: 5")
    return dict(sorted(out.items()))


def centered_sinr_points(center, span, step):
    """Target SINRs from center - span to center + span (dB) in steps of step, always including
    the centre itself (if span is not a multiple of step, the ends stop short of +-span)."""
    if span < 0:
        raise ValueError("SINR +- range cannot be negative")
    if step <= 0:
        raise ValueError("SINR step must be greater than zero")
    n = int(span / step + 1e-9)
    return [round(center + i * step, 6) for i in range(-n, n + 1)]


# ----------------------------------------------------------------------------
# Bulk run folder
# ----------------------------------------------------------------------------
def plan_dem(plan):
    """The .bdem to simulate a plan on: the region's full file (next to its TIFF) if it has been
    generated, so older plans that stored another path (e.g. terrain/08_Haworth.bdem, which covers
    only part of Haworth) use it too; otherwise the plan's stored path."""
    region_dem = find_bdem(plan["region"])
    return region_dem if os.path.exists(region_dem) else plan["bdem"]


def write_plan_confs(out_dir, plan, gnb_template, ue_template, template_dir=TEMPLATE_DIR):
    """Manual Start gNB / Start UE with a site plan: the selected gNB/UE .conf with the plan's
    channel geometry and DEM (as in bulk runs) and the bulk runs' downlink gain, so the UE can
    sync over the terrain. The noise is left as in the templates. Returns (gnb_path, ue_path)."""
    for path in (gnb_template, ue_template):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"template .conf not found: {path}")
    export_configs(out_dir, template_dir, (plan["gnb"]["lon"], plan["gnb"]["lat"]),
                   (plan["ue"]["lon"], plan["ue"]["lat"]),
                   plan["gnb"]["height_m"], plan["ue"]["height_m"], plan_dem(plan),
                   templates={GNB_CONF: gnb_template, UE_CONF: ue_template})
    paths = []
    for name in (GNB_CONF, UE_CONF):
        path = os.path.join(out_dir, name)
        with open(path, encoding="utf-8") as f:
            text = fill_block(f.read(), BLOCK_GNB_SIDE, {"ploss_dB": f"{BULK_DL_GAIN_DB:.2f}"})
        if text is None:
            raise ValueError(f"'ploss_dB' not found in {BLOCK_GNB_SIDE} of {name}, "
                             f"so the downlink gain cannot be set")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        paths.append(path)
    return tuple(paths)


def make_bulk_run(parent, plans, mcs_list, sinr_list, template_dir=TEMPLATE_DIR,
                  gnb_template=None, ue_template=None):
    """Create <parent>/bulk_<date>_<time>/ and fill it:

        manifest.json              what was requested (plans, MCS list, SINR list, run count)
        plans/                     copies of the chosen plan files
        raw/<plan>/                gNB + UE .conf for that plan, plus one empty mcs_<N>/ folder
                                   per MCS for raw logs
                                   (no plans: one raw/raw_template/ with the templates unchanged:
                                   no plan geometry, DEM or DL gain, only the per-run UL noise)
        data/bler_sinr_by_mcs.csv  header only; the collector appends one row per measurement

    gnb_template / ue_template: the .conf files to build each run from (the GUI passes the ones
    selected for manual runs, so bulk runs use the same cell config); None = the files in
    template_dir. sinr_list: one list of target SINRs for every MCS, or {mcs: [SINRs]} to give
    each MCS its own range (an MCS missing from the dict is not run). Returns the folder path."""
    if not isinstance(sinr_list, dict):
        sinr_list = {m: list(sinr_list) for m in mcs_list}
    sinr_by_mcs = {m: list(sinr_list.get(m, [])) for m in mcs_list}
    templates = {GNB_CONF: gnb_template or os.path.join(template_dir, GNB_CONF),
                 UE_CONF: ue_template or os.path.join(template_dir, UE_CONF)}
    for path in templates.values():
        if not os.path.isfile(path):
            raise FileNotFoundError(f"template .conf not found: {path}")
    root = make_run_folder(parent, "bulk")
    os.makedirs(os.path.join(root, "plans"))
    os.makedirs(os.path.join(root, "data"))
    entries = []
    if not plans:
        raw = os.path.join(root, "raw", RAW_TEMPLATE_KEY)
        os.makedirs(raw)
        for name, src in templates.items():
            shutil.copy2(src, os.path.join(raw, name))
        for m in mcs_list:
            os.makedirs(os.path.join(raw, f"mcs_{m}"))
        entries.append({"key": RAW_TEMPLATE_KEY, "name": "Raw template (no site plan)",
                        "region": None, "bdem": None, "separation_m": None})
    for plan in plans:
        key = os.path.splitext(os.path.basename(plan["file"]))[0]
        shutil.copy2(plan["file"], os.path.join(root, "plans", key + ".json"))
        raw = os.path.join(root, "raw", key)
        dem = plan_dem(plan)
        export_configs(raw, template_dir, (plan["gnb"]["lon"], plan["gnb"]["lat"]),
                       (plan["ue"]["lon"], plan["ue"]["lat"]),
                       plan["gnb"]["height_m"], plan["ue"]["height_m"], dem,
                       templates=templates)
        for m in mcs_list:
            os.makedirs(os.path.join(raw, f"mcs_{m}"))
        entries.append({"key": key, "name": plan["name"], "region": plan["region"], "bdem": dem,
                        "separation_m": plan.get("separation_m")})
    with open(os.path.join(root, "data", "bler_sinr_by_mcs.csv"), "w", encoding="utf-8") as f:
        f.write(",".join(DATA_COLUMNS) + "\n")
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "plans": entries, "mcs": mcs_list,
        "sinr_db_by_mcs": {str(m): pts for m, pts in sinr_by_mcs.items()},
        "templates": {"gnb": templates[GNB_CONF], "ue": templates[UE_CONF]},
        "runs": len(entries) * sum(len(pts) for pts in sinr_by_mcs.values()),
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return root


# ----------------------------------------------------------------------------
# Sequential runner helpers (no Qt: the GUI drives these one run at a time)
# ----------------------------------------------------------------------------
def build_queue(manifest):
    """[(plan key, mcs, sinr_db), ...] in run order: plan, then MCS, then SINR. Each MCS uses
    its own SINR list (sinr_db_by_mcs); older manifests have one "sinr_db" list for all."""
    by_mcs = manifest.get("sinr_db_by_mcs") or {}
    return [(e["key"], m, s) for e in manifest["plans"] for m in manifest["mcs"]
            for s in by_mcs.get(str(m), manifest.get("sinr_db", []))]


def run_dir(root, key, mcs, sinr):
    return os.path.join(root, "raw", key, f"mcs_{mcs}", f"sinr_{sinr:g}")


def set_ul_sinr(path, sinr):
    """Rewrite one .conf in place with the uplink noise for a target SINR (as in bulk runs:
    noise_power_dB = BULK_NOISE_AT_0DB_SINR - sinr in BLOCK_UE_SIDE). Used by manual runs."""
    with open(path, encoding="utf-8") as f:
        text = fill_block(f.read(), BLOCK_UE_SIDE, {BULK_NOISE_KEY: f"{BULK_NOISE_AT_0DB_SINR - sinr:.2f}"})
    if text is None:
        raise ValueError(f"'{BULK_NOISE_KEY}' not found in {BLOCK_UE_SIDE} of "
                         f"{os.path.basename(path)}, so the uplink SINR cannot be set")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_raw_confs(out_dir, gnb_template, ue_template):
    """Copy the templates unchanged into out_dir under the standard names. Returns (gnb, ue)."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, src in ((GNB_CONF, gnb_template), (UE_CONF, ue_template)):
        if not os.path.isfile(src):
            raise FileNotFoundError(f"template .conf not found: {src}")
        paths.append(os.path.join(out_dir, name))
        shutil.copy2(src, paths[-1])
    return tuple(paths)


def write_run_confs(root, key, mcs, sinr):
    """Write this run's gNB and UE .conf into its own folder, with the noise level for the target
    SINR set on the UPLINK only (BLOCK_UE_SIDE: UE transmits, gNB receives). The downlink entry
    keeps the template's noise and gets BULK_DL_GAIN_DB of signal gain (as ploss_dB) so the UE can
    sync over the plan's terrain channel; the raw-template run (no site plan) keeps the template's
    downlink as it is, like a manual run with no plan. Returns (gnb_path, ue_path).
    The MCS is NOT written here: the gNB runs in --phy-test, where the GUI passes it on the command
    line (-m DL, -t UL) and the phy-test scheduler uses it as a fixed MCS for every transmission.
    Raises ValueError naming the missing key if a conf has no place for a value."""
    out = run_dir(root, key, mcs, sinr)
    os.makedirs(out, exist_ok=True)
    noise = f"{BULK_NOISE_AT_0DB_SINR - sinr:.2f}"
    paths = []
    for name in (GNB_CONF, UE_CONF):
        with open(os.path.join(root, "raw", key, name), encoding="utf-8") as f:
            text = f.read()
        filled = fill_block(text, BLOCK_UE_SIDE, {BULK_NOISE_KEY: noise})
        if filled is None:
            raise ValueError(f"'{BULK_NOISE_KEY}' not found in {BLOCK_UE_SIDE} of {name}, "
                             f"so the uplink SINR cannot be set")
        text = filled
        if key != RAW_TEMPLATE_KEY:
            filled = fill_block(text, BLOCK_GNB_SIDE, {"ploss_dB": f"{BULK_DL_GAIN_DB:.2f}"})
            if filled is None:
                raise ValueError(f"'ploss_dB' not found in {BLOCK_GNB_SIDE} of {name}, "
                                 f"so the downlink gain cannot be set")
            text = filled
        path = os.path.join(out, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        paths.append(path)
    return tuple(paths)


def classify_link(ul_bler, max_abs_ta, rsrp_db):
    """Health of one bulk run's link over its measure window (None = not measured):
        no_sync   the UE never synced, so there is no BLER at all
        ta_drift  the UE's timing advance ran away (|TA| > LINK_MAX_ABS_TA) or the gNB stopped
                  hearing it (RSRP < LINK_MIN_RSRP_DB)
        ok        none of the above
    A high PUSCH DTX share is not a flag: OAI marks a PUSCH as DTX whenever it measures under
    pusch_dtx_threshold (5 dB by default), so low-SNR runs have it too. It is still recorded in
    the CSV (ul_dtx_frac)."""
    if ul_bler is None:
        return "no_sync"
    if (max_abs_ta is not None and max_abs_ta > LINK_MAX_ABS_TA) or \
            (rsrp_db is not None and rsrp_db < LINK_MIN_RSRP_DB):
        return "ta_drift"
    return LINK_OK


def append_row(root, row):
    """Append one measurement to data/bler_sinr_by_mcs.csv. row: dict keyed by DATA_COLUMNS."""
    with open(os.path.join(root, "data", "bler_sinr_by_mcs.csv"), "a", newline="",
              encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=DATA_COLUMNS).writerow(row)
