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

from export import export_configs, fill_block, make_run_folder, run_folder_name
from settings import (BLOCK_GNB_SIDE, BLOCK_UE_SIDE, BULK_MCS_KEYS, BULK_NOISE_AT_0DB_SINR,
                      BULK_NOISE_KEY, GNB_CONF, PLANS_DIR, TEMPLATE_DIR, UE_CONF)

MCS_MIN, MCS_MAX = 0, 28             # NR MCS index range (table 1: 0-28; 256QAM table: 0-27)
DATA_COLUMNS = ["plan", "mcs", "target_sinr_db", "dl_bler", "ul_bler", "ul_snr_db", "timestamp"]


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


# ----------------------------------------------------------------------------
# Bulk run folder
# ----------------------------------------------------------------------------
def make_bulk_run(parent, plans, mcs_list, sinr_list, template_dir=TEMPLATE_DIR):
    """Create <parent>/bulk_<date>_<time>/ and fill it:

        manifest.json              what was requested (plans, MCS list, SINR list, run count)
        plans/                     copies of the chosen plan files
        raw/<plan>/                gNB + UE .conf for that plan, plus one empty mcs_<N>/ folder
                                   per MCS for raw logs
        data/bler_sinr_by_mcs.csv  header only; the collector appends one row per measurement

    Returns the folder path."""
    root = make_run_folder(parent, "bulk")
    os.makedirs(os.path.join(root, "plans"))
    os.makedirs(os.path.join(root, "data"))
    entries = []
    for plan in plans:
        key = os.path.splitext(os.path.basename(plan["file"]))[0]
        shutil.copy2(plan["file"], os.path.join(root, "plans", key + ".json"))
        raw = os.path.join(root, "raw", key)
        export_configs(raw, template_dir, (plan["gnb"]["lon"], plan["gnb"]["lat"]),
                       (plan["ue"]["lon"], plan["ue"]["lat"]),
                       plan["gnb"]["height_m"], plan["ue"]["height_m"], plan["bdem"])
        for m in mcs_list:
            os.makedirs(os.path.join(raw, f"mcs_{m}"))
        entries.append({"key": key, "name": plan["name"], "region": plan["region"],
                        "separation_m": plan.get("separation_m")})
    with open(os.path.join(root, "data", "bler_sinr_by_mcs.csv"), "w", encoding="utf-8") as f:
        f.write(",".join(DATA_COLUMNS) + "\n")
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "plans": entries, "mcs": mcs_list, "sinr_db": sinr_list,
        "runs": len(entries) * len(mcs_list) * len(sinr_list),
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return root


# ----------------------------------------------------------------------------
# Sequential runner helpers (no Qt: the GUI drives these one run at a time)
# ----------------------------------------------------------------------------
def build_queue(manifest):
    """[(plan key, mcs, sinr_db), ...] in run order: plan, then MCS, then SINR."""
    return [(e["key"], m, s) for e in manifest["plans"] for m in manifest["mcs"]
            for s in manifest["sinr_db"]]


def run_dir(root, key, mcs, sinr):
    return os.path.join(root, "raw", key, f"mcs_{mcs}", f"sinr_{sinr:g}")


def _set_key(text, key, value):
    """Overwrite every `key = value;` in text. None if the key is not there."""
    new, n = re.subn(rf"(\b{key}\s*=\s*)[^;\n]*", lambda m: m.group(1) + value, text)
    return new if n else None


def write_run_confs(root, key, mcs, sinr):
    """Write this run's gNB and UE .conf into its own folder, with the MCS pinned (gNB) and the
    noise level for the target SINR set in both channel entries. Returns (gnb_path, ue_path).
    Raises ValueError naming the missing key if a conf has no place for a value."""
    out = run_dir(root, key, mcs, sinr)
    os.makedirs(out, exist_ok=True)
    noise = f"{BULK_NOISE_AT_0DB_SINR - sinr:.2f}"
    paths = []
    for name in (GNB_CONF, UE_CONF):
        with open(os.path.join(root, "raw", key, name), encoding="utf-8") as f:
            text = f.read()
        if name == GNB_CONF:
            for k in BULK_MCS_KEYS:
                text = _set_key(text, k, str(mcs))
                if text is None:
                    raise ValueError(f"'{k}' not found in the gNB conf, so the MCS cannot be set")
        for block in (BLOCK_GNB_SIDE, BLOCK_UE_SIDE):
            filled = fill_block(text, block, {BULK_NOISE_KEY: noise})
            if filled is None:
                raise ValueError(f"'{BULK_NOISE_KEY}' not found in {block} of {name}, "
                                 f"so the SINR cannot be set")
            text = filled
        path = os.path.join(out, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        paths.append(path)
    return tuple(paths)


def append_row(root, row):
    """Append one measurement to data/bler_sinr_by_mcs.csv. row: dict keyed by DATA_COLUMNS."""
    with open(os.path.join(root, "data", "bler_sinr_by_mcs.csv"), "a", newline="",
              encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=DATA_COLUMNS).writerow(row)
