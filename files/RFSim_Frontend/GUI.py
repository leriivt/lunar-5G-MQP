"""RFSim Frontend: a basic PyQt6 GUI for running OAI RFSim (gNB + UE)

Needs: 
    pip install PyQt6
    pip install 

Run:  python3 GUI.py

"""
import json
import os
import sys
import re
import time
from pathlib import Path
from PyQt6.QtCore import QFileSystemWatcher, QProcess, Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                             QTabWidget, QDialog, QScrollArea,
                             QVBoxLayout, QWidget, QFileDialog)

# GUI.py sits in a subfolder; plans.py, settings.py, export.py and the planner are one level up
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plans import (append_row, build_queue, delete_plan, load_plans, make_bulk_run,
                   RAW_TEMPLATE_KEY, centered_sinr_points, classify_link, parse_mcs_centers, run_dir, set_ul_sinr, write_plan_confs, write_raw_confs,
                   write_run_confs)
from bulk_plot import load_curves, plot_bulk
from mcs_dialog import McsCenterDialog, format_centers
from live_graph import BlerSnrGraph, LiveGraph
from settings import (APP_DIR, BULK_ATTACH_S, BULK_MEASURE_S, BULK_SETTLE_S, BULK_TA_RETRIES,
                      PLANS_DIR)

# ----------------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------------
OAI_DIR = "/home/lunar5g/openairinterface5g"
OAI_BUILD_DIR = os.path.join(OAI_DIR, "cmake_targets", "ran_build", "build")
#CONF_DIR = os.path.join(OAI_DIR, "targets", "PROJECTS", "GENERIC-NR-5GC", "CONF")
CONF_DIR = os.path.join(OAI_DIR, "targets", "PROJECTS", "GENERIC-NR-5GC", "CONF", "RF_SIMULATION")
DEFAULT_GNB_CONF = os.path.join(CONF_DIR, "gnb1.sa.band78.fr1.106PRB.prs.usrpx310.conf")
DEFAULT_UE_CONF = os.path.join(CONF_DIR, "ue.bictr.conf")
# gNB conf loaded when switching to PHY test mode (real USRP X310)
PHY_GNB_CONF = os.path.join(Path(__file__).parent.parent, "Templates", "gnb1.sa.band78.fr1.106PRB.prs.usrpx310.conf")
# last gNB/UE .conf chosen in the GUI, restored on the next launch (per machine, not in git)
LAST_CONFS_FILE = os.path.join(Path(__file__).parent, "last_confs.json")
BULK_SETTINGS_FILE = os.path.join(Path(__file__).parent, "last_bulk_settings.json")  # bulk-run form, kept between sessions
STATS_REFRESH_MS = 500      # how often refresh_stats() should run once implemented
NR_MAC_STATS = os.path.join(OAI_BUILD_DIR, "nrMAC_stats.log")  
NR_L1_STATS = os.path.join(OAI_BUILD_DIR, "nrL1_stats.log")

#TODO Get around sudo issue and modify these bash scripts

SH_DIR = os.path.join(Path(__file__).parent, ".sh")
UE_MAKE = os.path.join(SH_DIR, "ue-bictr-gui.sh")
GNB_MAKE = os.path.join(SH_DIR, "gnb-bictr-gui.sh")
UE_MAKE_PHY = os.path.join(SH_DIR, "ue-bictr-gui-phy.sh")
GNB_MAKE_PHY = os.path.join(SH_DIR, "gnb-bictr-gui-phy.sh")
STOP_ALL = os.path.join(SH_DIR, "stop-all.sh")

# "UE 1234: dlsch_rounds 270/31/22/19, dlsch_errors 17, ..."
DL_RE = re.compile(r"dlsch_rounds ([\d/]+), dlsch_errors (\d+)")
UL_RE = re.compile(r"ulsch_rounds ([\d/]+), ulsch_DTX \d+, ulsch_errors (\d+)")
# same lines end in "... BLER 0.00000 MCS 9": the MCS the gNB is currently using
DL_MCS_RE = re.compile(r"dlsch_rounds .*MCS (\d+)")
UL_MCS_RE = re.compile(r"ulsch_rounds .*MCS (\d+)")
# "ulsch_power[0] 50,0 ulsch_noise_power[0] 30.8" (OAI prints the first value with a comma)
# link health: PUSCH attempts the gNB found empty (DTX), its RSRP for the UE, and the UE's TA total
UL_DTX_RE = re.compile(r"ulsch_rounds ([\d/]+), ulsch_DTX (\d+)")
RSRP_RE = re.compile(r"average RSRP (-?\d+)")
TA_RE = re.compile(r"TA total (-?\d+)")
UL_SNR_RE = re.compile(r"ulsch_power\[0\] (\d+[.,]\d) ulsch_noise_power\[0\] (\d+[.,]\d)")
# nr-uesoftmodem prints this once it has synced to the gNB (executables/nr-ue.c). In phy-test the
# gNB schedules the UE from the moment it starts, so everything before this line is DTX, not data.
UE_SYNC_MARK = "Got synch:"

DEFAULT_SAVE_DIR = os.path.join(Path(__file__).parent, "saved_runs")
SAVE_DIR = DEFAULT_SAVE_DIR

# Bulk data collection: the site planner sits next to this file, plans are saved in PLANS_DIR
PLANNER_SCRIPT = os.path.join(APP_DIR, "qt_lunar_site_planner.py")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RFSim Frontend")
        self.resize(1000, 820)
        self.sim_mode = True  # default simulation mode: true = RFSim, False = PHY test mode
        self._rfsim_gnb_conf = None  # RFSim gNB conf to restore when leaving PHY test mode
        self._build_widgets()

        #-----gnb/ue processes----
        self.p_gnb = None 
        self.p_ue = None
        self.timer = None
        self.stopper = None
        self._closing = False
        self._shutdown_check = None
        #-------live stats -------
        self.ul_bler = 0 
        self.dl_bler = 0
        self.snr = 0
        self.dl_mcs = self.ul_mcs = None
        self._reset_attach()
        self._manual_confs = None   # (plan file, (gnb_conf, ue_conf)) of the last manual plan run
        self._gnb_start_time = time.time()
        
    # ---- layout --------------------------------------------------------------
    def _build_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        #main buttons:

        main_btns = QGroupBox("Other stuff")
        btns = QFormLayout(main_btns)

        self.mode_toggle = QPushButton(f"Switch to {'PHY test' if self.sim_mode else 'RFSim'} mode")
        self.mode_toggle.clicked.connect(self.toggle_mode)
        btns.addRow(self.mode_toggle)

        flush_logs = QPushButton("Flush log files")
        flush_logs.clicked.connect(self.flush_log_files)
        btns.addRow(flush_logs)   
        layout.addWidget(main_btns)

        # Config templates: one row per node, path box + Browse. Manual and bulk runs build their
        # confs from these with the ticked site plan(s); with no plan ticked they run as they are.
        configs = QGroupBox("Config templates")
        form = QFormLayout(configs)
        last = self._load_last_confs()
        self.gnb_conf = QLineEdit(last.get("gnb_conf", DEFAULT_GNB_CONF))
        self.ue_conf = QLineEdit(last.get("ue_conf", DEFAULT_UE_CONF))
        # typing a path by hand counts as choosing it (bulk runs use setText, which doesn't fire this)
        self.gnb_conf.editingFinished.connect(self._save_last_confs)
        self.ue_conf.editingFinished.connect(self._save_last_confs)

        form.addRow("gNB .conf", self._path_row(self.gnb_conf, self.browse_gnb_config))
        form.addRow("UE .conf", self._path_row(self.ue_conf, self.browse_ue_config))
        # run output directory: a row of this box rather than its own box, to save height
        self.save_dir_edit = QLineEdit(SAVE_DIR)
        self.save_dir_edit.setReadOnly(True)
        form.addRow("Save directory", self._path_row(self.save_dir_edit, self.browse_save_dir))
        layout.addWidget(configs)

        layout.addWidget(self._build_plans_group())
        bulk = self._build_bulk_group()

        # Process controls: start/stop buttons and a status     label per node
        controls = QGroupBox("Processes")
        grid = QGridLayout(controls)
        self.gnb_status = QLabel("gNB: Stopped")
        self.ue_status = QLabel("UE: Stopped")
        for row, (name, status, start) in enumerate((
                ("gNB", self.gnb_status, self.start_gnb),
                ("UE", self.ue_status, self.start_ue))):
            grid.addWidget(status, row, 0)
            grid.addWidget(self._button(f"Start {name}", start), row, 1)
        grid.addWidget(self._button("Stop all", self.stop_all), 0, 2, 2, 1)
        # manual-run MCS / SINR (bulk runs set their own per run)
        self.manual_mcs = QSpinBox()
        self.manual_mcs.setRange(0, 28)
        self.manual_mcs.setValue(9)
        self.manual_mcs.setToolTip("phy-test fixed MCS for DL and UL (-m / -t), applied on Start gNB")
        self.manual_sinr = QDoubleSpinBox()
        self.manual_sinr.setRange(-51.0, 100.0)       # the minimum shows as "template"
        self.manual_sinr.setDecimals(1)
        self.manual_sinr.setSuffix(" dB")
        self.manual_sinr.setSpecialValueText("template")
        self.manual_sinr.setValue(self.manual_sinr.minimum())
        self.manual_sinr.setToolTip("Target UPLINK SINR, set as noise_power_dB like bulk runs. "
                                    "'template' (lowest value) keeps the template's noise.")
        mcs_sinr = QHBoxLayout()
        for label, box in (("MCS", self.manual_mcs), ("UL SINR", self.manual_sinr)):
            mcs_sinr.addWidget(QLabel(label))
            mcs_sinr.addWidget(box)
        mcs_sinr.addStretch()
        grid.addLayout(mcs_sinr, 2, 0, 1, 3)
        # manual runs (Processes) and bulk runs side by side, to leave room for the logs/graph
        runs_row = QHBoxLayout()
        runs_row.addWidget(controls, 1)
        runs_row.addWidget(bulk, 2)
        layout.addLayout(runs_row)
        self._restore_bulk_settings()       # bulk + manual settings from the last session

        # Live stats: one value label per metric
        stats = QGroupBox("Live stats")
        stats_row = QHBoxLayout(stats)
        self.stat_labels = {}
        for key in ("DL MCS", "UL MCS", "DL BLER", "UL BLER", "DL SNR (dB)", "UL SNR (dB)"):
            value = QLabel("-")
            self.stat_labels[key] = value
            stats_row.addWidget(QLabel(f"{key}:"))
            stats_row.addWidget(value)
            stats_row.addSpacing(20)
        stats_row.addStretch()
        layout.addWidget(stats)

        # Output: one read-only log per process
        self.logs = QTabWidget()
        self.gnb_log = QPlainTextEdit(readOnly=True)
        self.ue_log = QPlainTextEdit(readOnly=True) 
        self.logs.addTab(self.gnb_log, "gNB output")
        self.logs.addTab(self.ue_log, "UE output")
        # Live graph tab: BLER / UL SNR / MCS over time (left), UL BLER vs mean UL SNR (right)
        self.graph = LiveGraph()
        self.bler_graph = BlerSnrGraph()
        graph_tab = QWidget()
        graph_row = QHBoxLayout(graph_tab)
        graph_row.setContentsMargins(0, 0, 0, 0)
        graph_row.setSpacing(4)
        graph_row.addWidget(self.graph, 3)
        graph_row.addWidget(self.bler_graph, 2)
        self.logs.addTab(graph_tab, "Live graph")
        layout.addWidget(self.logs, 1)

    # ---- bulk data collection ------------------------------------------------
    def _build_plans_group(self):
        """Site plans made in the planner: used by manual runs (one ticked) and bulk runs."""
        os.makedirs(PLANS_DIR, exist_ok=True)
        group = QGroupBox("Site plans (none ticked = config templates as they are)")
        v = QVBoxLayout(group)

        top = QHBoxLayout()
        top.addWidget(self._button("Open site planner", self.open_planner))
        top.addWidget(self._button("Refresh plans", self.refresh_plans))
        top.addWidget(self._button("Remove selected", self.remove_selected_plans))
        top.addStretch()
        v.addLayout(top)

        self.plan_list = QListWidget()
        self.plan_list.setMaximumHeight(120)
        v.addWidget(self.plan_list)
        self.plan_note = QLabel()
        v.addWidget(self.plan_note)

        # new plans saved from the planner show up without pressing Refresh
        self.plan_watcher = QFileSystemWatcher([PLANS_DIR], self)
        self.plan_watcher.directoryChanged.connect(lambda _path: self.refresh_plans())
        self.refresh_plans()
        return group

    def _build_bulk_group(self):
        """MCS list, SINR range and timing; runs every ticked site plan (or the raw templates)."""
        group = QGroupBox("Bulk data collection (BLER / SINR vs MCS)")
        v = QVBoxLayout(group)

        form = QFormLayout()
        self.mcs_centers = QLineEdit("9: 5")
        self.mcs_centers.setPlaceholderText("e.g.  5: 2;  9: 5;  12-13: 8.5")
        self.mcs_centers.setToolTip(
            "Each MCS to run and the target SINR its sweep is centred on.\n"
            "Entries separated by ';':  <MCS>: <centre SINR dB>   (MCS 0-28)\n"
            "The MCS part can be a list or range sharing one centre (12-13: 8.5).\n"
            "Each MCS sweeps centre - range ... centre + range in steps of 'step'.\n"
            "'Choose MCS...' picks them from a table and writes this field for you.")
        centers_row = QHBoxLayout()
        centers_row.addWidget(self.mcs_centers, 1)
        centers_row.addWidget(self._button("Choose MCS...", self.choose_mcs))
        form.addRow("MCS : centre SINR", centers_row)
        self._mcs_table_centers = {}    # every MCS's centre from the table, ticked or not (saved)

        sinr_row = QHBoxLayout()
        self.sinr_span, self.sinr_step = QDoubleSpinBox(), QDoubleSpinBox()
        self.sinr_span.setRange(0.0, 50.0)
        self.sinr_span.setValue(3.0)
        self.sinr_span.setPrefix("\u00b1 ")
        self.sinr_step.setRange(0.1, 50.0)
        self.sinr_step.setValue(1.0)
        for box in (self.sinr_span, self.sinr_step):
            box.setDecimals(1)
            box.setSuffix(" dB")
        for label, box in (("range", self.sinr_span), ("step", self.sinr_step)):
            sinr_row.addWidget(QLabel(label))
            sinr_row.addWidget(box)
        sinr_row.addStretch()
        form.addRow("SINR around centre", sinr_row)

        timing = QHBoxLayout()
        self.settle_s, self.attach_s, self.measure_s = (QSpinBox() for _ in range(3))
        for label, box, value in (("gNB settle", self.settle_s, BULK_SETTLE_S),
                                  ("UE attach wait", self.attach_s, BULK_ATTACH_S),
                                  ("measure", self.measure_s, BULK_MEASURE_S)):
            box.setRange(1, 3600)
            box.setValue(value)
            box.setSuffix(" s")
            timing.addWidget(QLabel(label))
            timing.addWidget(box)
        timing.addStretch()
        form.addRow("Per-run timing", timing)
        v.addLayout(form)

        bottom = QHBoxLayout()
        bottom.addWidget(self._button("Create bulk run folder", self.create_bulk_run))
        self.bulk_start_btn = self._button("Start bulk run", self.start_bulk_run)
        self.bulk_abort_btn = self._button("Abort", self.abort_bulk)
        self.bulk_abort_btn.setEnabled(False)
        bottom.addWidget(self.bulk_start_btn)
        bottom.addWidget(self.bulk_abort_btn)
        self.bulk_status = QLabel("")
        self.bulk_status.setWordWrap(True)
        bottom.addWidget(self.bulk_status, 1)
        v.addLayout(bottom)

        self.bulk_dir = None
        self._bulk_running = False
        self._bulk_gen = 0              # bumped on abort so stale timers do nothing
        self._bulk_queue, self._bulk_i = [], 0
        self._bulk_retry, self._bulk_redo = 0, False
        self._bulk_saved_confs = None
        return group

    def _bulk_setting_widgets(self):
        """name -> widget for every run setting kept between sessions (plan ticks are not kept)."""
        return {"manual_mcs": self.manual_mcs, "manual_sinr": self.manual_sinr, "mcs_centers": self.mcs_centers,
                "sinr_span": self.sinr_span, "sinr_step": self.sinr_step, "settle_s": self.settle_s,
                "attach_s": self.attach_s, "measure_s": self.measure_s}

    def _restore_bulk_settings(self):
        """Fill the bulk-run form from the last session, then save it whenever it changes."""
        try:
            with open(BULK_SETTINGS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        try:
            self._mcs_table_centers = {int(m): float(c) for m, c in
                                       (saved.get("mcs_table_centers") or {}).items()}
        except (AttributeError, TypeError, ValueError):
            self._mcs_table_centers = {}
        for name, widget in self._bulk_setting_widgets().items():
            value = saved.get(name) if isinstance(saved, dict) else None
            try:
                if isinstance(widget, QLineEdit):
                    if isinstance(value, str):
                        widget.setText(value)
                elif value is not None:
                    widget.setValue(type(widget.value())(value))   # spin boxes clamp to their range
            except (TypeError, ValueError):
                pass
            if isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._save_bulk_settings)
            else:
                widget.valueChanged.connect(self._save_bulk_settings)

    def _save_bulk_settings(self, *_):
        values = {name: (w.text() if isinstance(w, QLineEdit) else w.value())
                  for name, w in self._bulk_setting_widgets().items()}
        values["mcs_table_centers"] = {str(m): c for m, c in sorted(self._mcs_table_centers.items())}
        try:
            with open(BULK_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(values, f, indent=2)
        except OSError:
            pass

    def choose_mcs(self):
        """Open the MCS table; on OK, write the ticked MCS and centres into the text field."""
        try:
            selected = parse_mcs_centers(self.mcs_centers.text())
        except ValueError:
            selected = {}                   # empty or unreadable field: start from nothing ticked
        dialog = McsCenterDialog(self, selected, self._mcs_table_centers,
                                 self.sinr_span.value(), self.sinr_step.value(),
                                 len(self.checked_plans()),
                                 self.settle_s.value() + self.attach_s.value() + self.measure_s.value())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._mcs_table_centers = dialog.centres_all()
        self.mcs_centers.setText(format_centers(dialog.selected()))
        self._save_bulk_settings()

    def open_planner(self):
        """Start the site planner as its own program. Plans it saves land in PLANS_DIR."""
        if not os.path.exists(PLANNER_SCRIPT):
            QMessageBox.warning(self, "Site planner", f"Not found:\n{PLANNER_SCRIPT}")
            return
        started, _pid = QProcess.startDetached(sys.executable, [PLANNER_SCRIPT], APP_DIR)
        if not started:
            QMessageBox.warning(self, "Site planner", "Could not start the site planner.")
        else:
            self.bulk_status.setText("Planner opened. Place the gNB and UE, then use "
                                     "'Save site plan for bulk run...'.")

    def refresh_plans(self):
        """Reload the plan list, keeping the ticks of plans that are still there (all unticked at startup)."""
        ticked = {self.plan_list.item(i).data(Qt.ItemDataRole.UserRole)
                  for i in range(self.plan_list.count())
                  if self.plan_list.item(i).checkState() == Qt.CheckState.Checked}
        self.plan_list.clear()
        for plan in load_plans():
            item = QListWidgetItem(f"{plan['name']}  [{plan['region_label']}, "
                                   f"{plan.get('separation_m', '?')} m]")
            item.setData(Qt.ItemDataRole.UserRole, plan["file"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if plan["file"] in ticked else Qt.CheckState.Unchecked)
            self.plan_list.addItem(item)
        self.plan_note.setText(f"{self.plan_list.count()} saved plan(s) in {PLANS_DIR}")

    def remove_selected_plans(self):
        rows = self.plan_list.selectedItems()
        if rows and QMessageBox.question(self, "Remove plans",
                                         f"Delete {len(rows)} saved plan file(s)?"
                                         ) == QMessageBox.StandardButton.Yes:
            for item in rows:
                delete_plan(item.data(Qt.ItemDataRole.UserRole))
            self.refresh_plans()

    def checked_plans(self):
        files = {self.plan_list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.plan_list.count())
                 if self.plan_list.item(i).checkState() == Qt.CheckState.Checked}
        return [p for p in load_plans() if p["file"] in files]

    def create_bulk_run(self):
        """Validate the inputs, then create the timestamped folder for raw runs and data."""
        plans = self.checked_plans()      # none ticked: run the raw templates (plans.RAW_TEMPLATE_KEY)
        try:
            centers = parse_mcs_centers(self.mcs_centers.text())
            sinr = {m: centered_sinr_points(c, self.sinr_span.value(), self.sinr_step.value())
                    for m, c in centers.items()}          # each MCS's own target SINR list
        except ValueError as err:
            QMessageBox.warning(self, "Bulk run", str(err))
            return False
        mcs = list(centers)
        n_points = sum(len(pts) for pts in sinr.values())
        runs = max(len(plans), 1) * n_points
        parent = SAVE_DIR          # the "Run output" save directory; the bulk folder is created inside it
        try:
            os.makedirs(parent, exist_ok=True)
            # build every run from the gNB/UE .conf selected above, i.e. the same cell config
            # as Start gNB / Start UE; only the plan's channel geometry and the noise change per run
            self.bulk_dir = make_bulk_run(parent, plans, mcs, sinr,
                                          gnb_template=self._gnb_conf_path(),
                                          ue_template=self._ue_conf_path())
        except OSError as err:
            QMessageBox.critical(self, "Bulk run", f"Could not create the folder:\n{err}")
            return False
        what = f"{len(plans)} plan(s)" if plans else "raw template (no site plan)"
        per_mcs = len(next(iter(sinr.values())))
        self.bulk_status.setText(f"Created {self.bulk_dir}\n{what} x {len(mcs)} MCS x {per_mcs} SINR "
                                 f"points (\u00b1{self.sinr_span.value():g} dB around each centre) = {runs} runs")
        return True

    # ---- sequential bulk run -------------------------------------------------
    def _later(self, ms, fn):
        """Run fn after ms, unless the bulk run was aborted or finished in the meantime."""
        gen = self._bulk_gen
        QTimer.singleShot(ms, lambda: fn() if gen == self._bulk_gen and self._bulk_running else None)

    def start_bulk_run(self):
        """Create the folder, then run every plan x MCS x SINR one after another."""
        if self._bulk_running:
            return
        busy = [p for p in (self.p_gnb, self.p_ue)
                if p is not None and p.state() != QProcess.ProcessState.NotRunning]
        if busy:
            QMessageBox.warning(self, "Bulk run", "Stop the gNB and UE first (Stop all).")
            return
        if not self.create_bulk_run():
            return
        with open(os.path.join(self.bulk_dir, "manifest.json"), encoding="utf-8") as f:
            self._bulk_queue = build_queue(json.load(f))
        self._bulk_i = 0
        self._bulk_retry = 0                      # attempts already redone for the current point
        self._bulk_redo = False
        self.bler_graph.set_curves({})            # this bulk run's points build up from empty
        self._bulk_saved_confs = (self.gnb_conf.text(), self.ue_conf.text())
        self._bulk_running = True
        self._bulk_gen += 1
        self.bulk_start_btn.setEnabled(False)
        self.bulk_abort_btn.setEnabled(True)
        self._bulk_next()

    def abort_bulk(self):
        if self._bulk_running:
            self._bulk_end("Aborted", stop=True)

    def _bulk_end(self, message, stop=False):
        self._bulk_running = False
        self._bulk_gen += 1
        if stop:
            self.stop_all()
        if self._bulk_saved_confs:
            self.gnb_conf.setText(self._bulk_saved_confs[0])
            self.ue_conf.setText(self._bulk_saved_confs[1])
        self.bulk_start_btn.setEnabled(True)
        self.bulk_abort_btn.setEnabled(False)
        self.bulk_status.setText(f"{message}. Data: {os.path.join(self.bulk_dir, 'data')}")
        self.show_bulk_plots(self.bulk_dir)

    def show_bulk_plots(self, root):
        """Plot UL BLER vs measured UL SNR (all points on one graph, a curve per MCS) and show it.
        Also runs after an abort, with whatever rows were recorded."""
        try:
            paths = plot_bulk(root)
        except (OSError, ValueError) as err:
            self.bulk_status.setText(self.bulk_status.text() + f"\nPlot failed: {err}")
            return
        if not paths:
            self.bulk_status.setText(self.bulk_status.text() + "\nNo BLER rows to plot.")
            return
        self.bulk_status.setText(self.bulk_status.text() + f"\nPlots: {os.path.dirname(paths[0])}")
        dialog = QDialog(self)
        dialog.setWindowTitle(f"BLER vs SNR: {os.path.basename(root)}")
        inner = QWidget()
        column = QVBoxLayout(inner)
        for path in paths:
            label = QLabel()
            label.setPixmap(QPixmap(path))
            label.setToolTip(path)
            column.addWidget(label)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        QVBoxLayout(dialog).addWidget(scroll)
        dialog.resize(1140, 760)
        dialog.show()
        self._plot_dialog = dialog            # keep a reference so it stays open

    def _bulk_next(self):
        if self._bulk_i >= len(self._bulk_queue):
            self._bulk_end(f"Finished {len(self._bulk_queue)} runs")
            return
        key, mcs, sinr = self._bulk_queue[self._bulk_i]
        try:
            gnb_conf, ue_conf = write_run_confs(self.bulk_dir, key, mcs, sinr)
        except (OSError, ValueError) as err:
            QMessageBox.critical(self, "Bulk run", str(err))
            self._bulk_end("Stopped: could not write run configs")
            return
        self.gnb_conf.setText(gnb_conf)
        self.ue_conf.setText(ue_conf)
        self._bulk_samples = {"dl": [], "ul": [], "snr": []}
        retry = f" [retry {self._bulk_retry}/{BULK_TA_RETRIES} after TA drift]" if self._bulk_retry else ""
        self.bulk_status.setText(f"Run {self._bulk_i + 1}/{len(self._bulk_queue)}: {key}, "
                                 f"MCS {mcs}, target SINR {sinr:g} dB{retry} (starting gNB)")
        self.start_gnb(mcs=mcs)
        self.graph.set_target_sinr(sinr)
        self._later(self.settle_s.value() * 1000, self._bulk_start_ue)

    def _bulk_start_ue(self):
        self.start_ue()
        self.bulk_status.setText(self.bulk_status.text().replace("starting gNB", "UE attaching"))
        self._later(self.attach_s.value() * 1000, self._bulk_measure_begin)

    def _bulk_measure_begin(self):
        self.bulk_status.setText(self.bulk_status.text().replace("UE attaching", "measuring"))
        self._bulk_left = self.measure_s.value()
        self._restart_stats()      # BLER baseline = first MAC dump in the measure window
        self._bulk_sample()

    def _bulk_sample(self):
        """Once a second: note the stats, but only those counted since the UE synced."""
        s = self._bulk_samples
        if self._stats_valid["dl"]:
            s["dl"].append(self.dl_bler)
        if self._stats_valid["ul"]:
            s["ul"].append(self.ul_bler)
        if self._stats_valid["snr"]:
            s["snr"].append(self.snr)
        self._bulk_left -= 1
        self._later(1000, self._bulk_sample if self._bulk_left > 0 else self._bulk_finish_run)

    def _bulk_finish_run(self):
        """Record the row, keep the raw logs, stop everything, then start the next run."""
        key, mcs, sinr = self._bulk_queue[self._bulk_i]
        s = self._bulk_samples
        fmt = lambda v: f"{v:.6f}" if v is not None else ""
        # live_stats counts BLER from the start of the measure window (or the UE's sync, if later),
        # so the last value is the window's BLER (empty if the UE never synced); SNR fluctuates,
        # so its samples over the same window are averaged.
        ul_bler = s["ul"][-1] if s["ul"] else None
        link = classify_link(ul_bler, self._max_abs_ta, self.rsrp)
        append_row(self.bulk_dir, {
            "plan": key, "mcs": mcs, "target_sinr_db": f"{sinr:g}", "link": link,
            "dl_bler": fmt(s["dl"][-1] if s["dl"] else None),
            "ul_bler": fmt(ul_bler),
            "ul_snr_db": fmt(sum(s["snr"]) / len(s["snr"]) if s["snr"] else None),
            "ul_dtx_frac": fmt(self.ul_dtx_frac), "max_abs_ta": self._max_abs_ta,
            "rsrp_db": "" if self.rsrp is None else self.rsrp,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")})
        if link != "ok":
            self.bulk_status.setText(self.bulk_status.text() + f"  [flagged: {link}]")
        # timing-advance runaway is a simulator fault, not a channel result: run the point again
        self._bulk_redo = link == "ta_drift" and self._bulk_retry < BULK_TA_RETRIES
        if self._bulk_redo:
            self.bulk_status.setText(self.bulk_status.text() +
                                     f" - redoing ({self._bulk_retry + 1}/{BULK_TA_RETRIES})")
        self.bler_graph.set_live(None)
        try:
            self.bler_graph.set_curves(load_curves(os.path.join(self.bulk_dir, "data",
                                                                "bler_sinr_by_mcs.csv"))[0])
        except (OSError, ValueError):
            pass
        out = run_dir(self.bulk_dir, key, mcs, sinr)
        for name, log in (("gnb.log", self.gnb_log), ("ue.log", self.ue_log)):
            if self._bulk_redo:     # keep the failed attempt's logs; gnb.log/ue.log = the last attempt
                name = name.replace(".log", f"_ta_drift_{self._bulk_retry + 1}.log")
            try:
                with open(os.path.join(out, name), "w", encoding="utf-8") as f:
                    f.write(log.toPlainText())
            except OSError:
                pass
            log.clear()
        self.stop_all()
        self._bulk_wait_stopped(tries=20)

    def _bulk_wait_stopped(self, tries):
        """Wait (up to ~10 s) for both processes to exit, then a short pause for the ports."""
        busy = any(p is not None and p.state() != QProcess.ProcessState.NotRunning
                   for p in (self.p_gnb, self.p_ue))
        if busy and tries > 0:
            self._later(500, lambda: self._bulk_wait_stopped(tries - 1))
            return
        if self._bulk_redo:
            self._bulk_retry += 1               # same point again
        else:
            self._bulk_i += 1
            self._bulk_retry = 0
        self._later(2000, self._bulk_next)

    def start_timer(self):
        if self.timer is not None:
            return  # Timer already running
        self.timer = QTimer()
        self.timer.setInterval(STATS_REFRESH_MS) #set timer interval to check BLER, SNR every 100ms
        self.timer.timeout.connect(self.live_stats)
        self.timer.start()

    def toggle_mode(self):
        #---------------- Make sure no gNB or UE is running before switching modes
        running = any(p is not None and p.state() != QProcess.ProcessState.NotRunning
                      for p in (self.p_gnb, self.p_ue))
        if running or self._bulk_running:
            return
        #----------------
        self.sim_mode = not self.sim_mode
        self.mode_toggle.setText(f"Switch to {'PHY test' if self.sim_mode else 'RFSim'} mode")
        # PHY test needs a USRP gNB conf; remember the RFSim one so switching back restores it.
        # The UE conf box is left alone: the PHY UE script takes no conf.
        if self.sim_mode:
            self.gnb_conf.setText(self._rfsim_gnb_conf)
        else:
            self._rfsim_gnb_conf = self.gnb_conf.text()
            self.gnb_conf.setText(PHY_GNB_CONF)

    def flush_log_files(self):
        """Flush the gnb/ue log files."""
        for log_file in (NR_MAC_STATS, NR_L1_STATS):
            try:
                with open(log_file, "w"):
                    pass
            except OSError as e:
                print(f"Error flushing {log_file}: {e}")


    def _button(self, text, command):
        button = QPushButton(text)
        button.clicked.connect(lambda _checked=False: command())
        return button

    def _path_row(self, line_edit, browse):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(line_edit, 1)
        h.addWidget(self._button("Browse...", browse))
        return row

    # ---- 3. interchangeable .conf files --------------------------------------
    @staticmethod
    def _load_last_confs():
        """{'gnb_conf': path, 'ue_conf': path} from the last session; files that are gone are dropped."""
        try:
            with open(LAST_CONFS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in saved.items()
                if k in ("gnb_conf", "ue_conf") and isinstance(v, str) and os.path.isfile(v)}

    def _save_last_confs(self):
        """Remember the chosen gNB/UE .conf for the next launch (not called for bulk-run confs)."""
        try:
            with open(LAST_CONFS_FILE, "w", encoding="utf-8") as f:
                json.dump({"gnb_conf": self.gnb_conf.text(), "ue_conf": self.ue_conf.text()}, f, indent=2)
        except OSError:
            pass

    def _conf_dialog_dir(self, line_edit):
        """Open the file dialog where the current file is, if it exists."""
        folder = os.path.dirname(line_edit.text())
        return folder if os.path.isdir(folder) else CONF_DIR

    def browse_gnb_config(self):
        """Pick a gNB .conf file and put its path in self.gnb_conf."""
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select gNB .conf file", self._conf_dialog_dir(self.gnb_conf), "Config files (*.conf)"
        )
        if file_name:
            self.gnb_conf.setText(file_name)
            self._save_last_confs()

    def browse_ue_config(self):
        """Pick a UE .conf file and put its path in self.ue_conf."""
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select UE .conf file", self._conf_dialog_dir(self.ue_conf), "Config files (*.conf)"
        )
        if file_name:
            self.ue_conf.setText(file_name)
            self._save_last_confs()

    def browse_save_dir(self):
        """Choose the directory where run summaries are saved."""
        global SAVE_DIR
        directory = QFileDialog.getExistingDirectory(
            self, "Select run save directory", SAVE_DIR
        )
        if directory:
            SAVE_DIR = directory
            self.save_dir_edit.setText(SAVE_DIR)

    # ---- 1. gNB ---------------------------------------------------------------
    def start_gnb(self, mcs=None):
        """Launch nr-softmodem in RFSim phy-test mode with the selected gNB .conf.
        mcs: fixed DL and UL MCS (phy-test -m / -t); bulk runs pass theirs, manual runs use the
        Processes box's MCS."""
        if self.p_gnb is not None and self.p_gnb.state() != QProcess.ProcessState.NotRunning:
            return
        if not self._bulk_running and self._manual_plan_confs(check_only=True) is False:
            return
        self.p_gnb = QProcess()
        process = self.p_gnb
        process.readyReadStandardOutput.connect(self._read_gnb_output)
        process.readyReadStandardError.connect(self._read_gnb_output)
        process.started.connect(lambda: self.gnb_status.setText("gNB: Running"))
        process.finished.connect(lambda *_: self._gnb_finished(process))
        process.errorOccurred.connect(
            lambda error: self._process_error("gNB", process, error)
        )
        conf = self._gnb_conf_path()
        if not self._bulk_running:                  # manual run: use the ticked site plan, if any
            confs = self._manual_plan_confs(new=True)
            if confs is False:
                return
            if confs:
                conf = confs[0]
            mcs = self.manual_mcs.value()
        script = GNB_MAKE if self.sim_mode else GNB_MAKE_PHY
        args = [script, conf]
        if mcs is not None:
            args += [str(mcs), str(mcs)]
        process.start("bash", args)
        self._gnb_start_time = time.time()
        self.graph.clear()
        if not self._bulk_running:
            self.graph.set_target_sinr(self._manual_sinr_value())
        self.dl_mcs = self.ul_mcs = None
        for key in ("DL MCS", "UL MCS"):
            self.stat_labels[key].setText("-")
        self._reset_attach()
        self.start_timer()  # Start the timer to refresh stats
        self.gnb_status.setText("gNB: Starting")
  

    # ---- 2. UE ----------------------------------------------------------------
    def start_ue(self):
        """Launch nr-uesoftmodem in RFSim mode with the selected UE .conf."""
        if self.p_ue is not None and self.p_ue.state() != QProcess.ProcessState.NotRunning:
            return
        conf = self._ue_conf_path()
        if not self._bulk_running:                  # manual run: same plan confs as the gNB
            confs = self._manual_plan_confs(new=False)
            if confs is False:
                return
            if confs:
                conf = confs[1]
        self.p_ue = QProcess()
        process = self.p_ue
        process.readyReadStandardOutput.connect(self._read_ue_output)
        process.readyReadStandardError.connect(self._read_ue_output)
        process.started.connect(lambda: self.ue_status.setText("UE: Running"))
        process.finished.connect(lambda *_: self._ue_finished(process))
        process.errorOccurred.connect(
            lambda error: self._process_error("UE", process, error)
        )
        
        self._reset_attach()
        if self.sim_mode:
            process.start("bash", [UE_MAKE, conf])
        else:
            process.start("bash", [UE_MAKE_PHY])   # real USRP: no .conf (see below)
        self.ue_status.setText("UE: Starting")

    def _manual_sinr_value(self):
        """The manual UL SINR target in dB, or None for 'template' (keep the template's noise)."""
        box = self.manual_sinr
        return None if box.value() <= box.minimum() else box.value()

    def _manual_plan_confs(self, new=False, check_only=False):
        """Confs for a manual run: the config templates plus the ticked site plan and UL SINR.

        None  = no plan ticked and SINR 'template': use the config templates as they are.
        False = more than one plan ticked, or the confs could not be written (the user was told).
        (gnb_conf, ue_conf) otherwise, written to <save dir>/manual/<plan or raw_template>/:
        the plan's channel geometry, DEM and DL gain (plans.write_plan_confs), then the UL noise
        for the SINR target (plans.set_ul_sinr).
        new=True (Start gNB) rebuilds them; Start UE reuses the gNB's pair if nothing changed."""
        plans = self.checked_plans()
        if len(plans) > 1:
            QMessageBox.warning(self, "Site plan", "Tick only one site plan for Start gNB / Start UE "
                                "(or none to use the config templates as they are).")
            return False
        plan = plans[0] if plans else None
        sinr = self._manual_sinr_value()
        if check_only or (plan is None and sinr is None):
            return None
        ident = (plan["file"] if plan else None, sinr, self._gnb_conf_path(), self._ue_conf_path())
        if not new and self._manual_confs and self._manual_confs[0] == ident \
                and all(os.path.exists(p) for p in self._manual_confs[1]):
            return self._manual_confs[1]
        key = os.path.splitext(os.path.basename(plan["file"]))[0] if plan else RAW_TEMPLATE_KEY
        out = os.path.join(SAVE_DIR, "manual", key)
        try:
            if plan:
                confs = write_plan_confs(out, plan, self._gnb_conf_path(), self._ue_conf_path())
            else:
                confs = write_raw_confs(out, self._gnb_conf_path(), self._ue_conf_path())
            if sinr is not None:
                for path in confs:
                    set_ul_sinr(path, sinr)
        except (OSError, ValueError) as err:
            QMessageBox.critical(self, "Manual run", f"Could not build the run's confs:\n{err}")
            return False
        self._manual_confs = (ident, confs)
        what = f"site plan '{plan['name']}'" if plan else "config templates"
        what += f", UL SINR {sinr:g} dB" if sinr is not None else ", template noise"
        for log in (self.gnb_log, self.ue_log):
            log.appendPlainText(f"[GUI] {what}: {out}")
        return confs

    def _gnb_conf_path(self):
        return self.gnb_conf.text()

    def _ue_conf_path(self):
        return self.ue_conf.text()

    def _read_gnb_output(self):
        process = self.p_gnb
        if process is not None:
            data = process.readAllStandardOutput() + process.readAllStandardError()
            if data:
                self.gnb_log.appendPlainText(bytes(data).decode(errors="replace"))

    def _read_ue_output(self):
        process = self.p_ue
        if process is not None:
            data = process.readAllStandardOutput() + process.readAllStandardError()
            if data:
                text = bytes(data).decode(errors="replace")
                self.ue_log.appendPlainText(text)
                for ta in TA_RE.findall(text):
                    self._max_abs_ta = max(self._max_abs_ta, abs(int(ta)))
                if self._ue_sync_time is None:
                    # keep a short tail so a marker split across two reads is still found
                    seen = self._ue_tail + text
                    if UE_SYNC_MARK in seen:
                        self._ue_sync_time = time.time()
                        self.graph.mark(self._ue_sync_time - self._gnb_start_time, "UE sync")
                        self.ue_log.appendPlainText("[GUI] UE synced: BLER/SNR averages start now")
                    self._ue_tail = seen[-len(UE_SYNC_MARK):]

    def _gnb_finished(self, process):
        if self.p_gnb is process:
            self.gnb_status.setText("gNB: Stopped")
            self._gnb_end_time = time.time()

    def _ue_finished(self, process):
        if self.p_ue is process:
            self.ue_status.setText("UE: Stopped")

    def _process_error(self, name, process, error):
        if name == "gNB" and self.p_gnb is process:
            self.gnb_status.setText(f"gNB: Error ({error.name})")
        elif name == "UE" and self.p_ue is process:
            self.ue_status.setText(f"UE: Error ({error.name})")

    def _terminate_process(self, process, status_label, name):
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            status_label.setText(f"{name}: Stopped")
            return
        status_label.setText(f"{name}: Stopping")
        process.terminate()
        QTimer.singleShot(1500, lambda: self._kill_if_running(process))

    def _kill_if_running(self, process):
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
        
    def stop_all(self):
        """Stop the UE, then the gNB."""
        print("Stopping all processes...")
        self.stopper = QProcess(self)
        stopper = self.stopper
        stopper.finished.connect(self._stopper_finished)
        stopper.start("bash", [STOP_ALL])
        self.stopper.closeWriteChannel()

        self.ue_status.setText("UE: Stopped")
        self.gnb_status.setText("gNB: Stopped")
        self._terminate_process(self.p_ue, self.ue_status, "UE")
        self._terminate_process(self.p_gnb, self.gnb_status, "gNB")

        # Last-resort escalation if the stop script is unable to clean children.
        QTimer.singleShot(1500, self._force_kill_managed_processes)

    def _stopper_finished(self, *_):
        if self.stopper is not None:
            self.stopper = None

    def _force_kill_managed_processes(self):
        for process in (self.p_ue, self.p_gnb):
            if process is not None and process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
        

    # ---- 4. BLER / SNR live stats --------------------------------------------

    def _reset_attach(self):
        """Forget the UE's sync: stats wait for the next 'Got synch' before counting."""
        self._ue_sync_time = None      # wall time the UE synced, None = not yet
        self._ue_tail = ""
        self._baseline = {}            # "dl"/"ul" -> OAI counters [r0, r1, .., errors] at sync
        self._stats_valid = {"dl": False, "ul": False, "snr": False}
        self._measure_start = None     # bulk runs: wall time the measure window began
        self._reset_health()
        if hasattr(self, "stat_labels"):
            for key in ("DL BLER", "UL BLER", "UL SNR (dB)"):
                self.stat_labels[key].setText("waiting for UE")

    def _stats_since(self):
        """Stats dumps older than this are ignored: the UE's sync, or in a bulk run the start of
        the measure window if that is later (so BLER and SNR cover the same window)."""
        return max(self._ue_sync_time, self._measure_start or 0.0)

    def _restart_stats(self):
        """Start counting again from the next stats dump (the counters keep running in OAI)."""
        self._measure_start = time.time()
        self.graph.mark(self._measure_start - self._gnb_start_time, "measure")
        self._baseline = {}
        self._stats_valid = {"dl": False, "ul": False, "snr": False}
        self._reset_health()

    def _reset_health(self):
        """Link-health numbers for the CSV (TA and RSRP feed classify_link), same span as BLER."""
        self._max_abs_ta = 0           # largest |TA total| the UE logged
        self._snr_samples = []         # UL SNR values over the same span (live BLER-vs-SNR point)
        if hasattr(self, "bler_graph"):
            self.bler_graph.set_live(None)
        self.ul_dtx_frac = None        # share of PUSCH attempts that were DTX
        self.rsrp = None               # gNB's latest RSRP for the UE (dB)

    def live_stats(self):
        """Parse the gNB's stats dumps and update the live stats.

        OAI's HARQ counters are cumulative since the gNB started, and in phy-test the gNB
        schedules the UE before it has synced, so those early slots all count as failures.
        Nothing is shown until the UE log says it synced; the first MAC dump written after
        that is the baseline, and BLER is computed from the counts since then."""
        t = time.time() - self._gnb_start_time      # live graph time axis
        if self.p_gnb is not None and self.p_gnb.state() != QProcess.ProcessState.NotRunning:
            self.graph.tick(t)                       # freeze the axis once the gNB has stopped
        # MCS is a setting, not a running count, so it is shown as soon as the gNB reports it
        mac = self._read_stats_file(NR_MAC_STATS)
        if mac is not None:
            for name, regex, label in (("dl", DL_MCS_RE, "DL MCS"), ("ul", UL_MCS_RE, "UL MCS")):
                m = regex.search(mac)
                if m:
                    setattr(self, f"{name}_mcs", int(m.group(1)))
                    self.stat_labels[label].setText(m.group(1))
                    self.graph.add(label, t, int(m.group(1)))
        if self._ue_sync_time is None:
            return
        mac = self._read_stats_file(NR_MAC_STATS, since=self._stats_since())
        if mac is not None:
            for name, regex, label in (("dl", DL_RE, "DL BLER"), ("ul", UL_RE, "UL BLER")):
                m = regex.search(mac)
                if not m:
                    continue
                counts = [int(c) for c in m.group(1).split("/")] + [int(m.group(2))]
                base = self._baseline.get(name)
                if base is None or len(base) != len(counts) or any(c < b for c, b in zip(counts, base)):
                    self._baseline[name] = counts          # first dump after sync (or counters reset)
                    continue
                delta = [c - b for c, b in zip(counts, base)]
                if delta[0] == 0:
                    continue                               # no new first transmissions yet
                bler = self._bler("/".join(map(str, delta[:-1])), delta[-1])
                setattr(self, f"{name}_bler", bler)
                self._stats_valid[name] = True
                self.stat_labels[label].setText(f"{bler:.3f}")
                self.graph.add(label, t, bler)
            m = UL_DTX_RE.search(mac)
            if m:
                counts = [sum(int(c) for c in m.group(1).split("/")), int(m.group(2))]  # attempts, DTX
                base = self._baseline.get("ul_dtx")
                if base is None or counts[0] < base[0] or counts[1] < base[1]:
                    self._baseline["ul_dtx"] = counts
                elif counts[0] > base[0]:
                    self.ul_dtx_frac = (counts[1] - base[1]) / (counts[0] - base[0])
            m = RSRP_RE.search(mac)
            if m:
                self.rsrp = int(m.group(1))
        l1 = self._read_stats_file(NR_L1_STATS, since=self._stats_since())
        if l1 is not None:
            m = UL_SNR_RE.search(l1)
            if m:
                power, noise = (float(g.replace(",", ".")) for g in m.groups())
                self.snr = power - noise
                self._stats_valid["snr"] = True
                self.stat_labels["UL SNR (dB)"].setText(f"{self.snr:.1f}")
                self.graph.add("UL SNR", t, self.snr)
                self._snr_samples.append(self.snr)
        if self._stats_valid["ul"] and self._snr_samples:
            self.bler_graph.set_live(sum(self._snr_samples) / len(self._snr_samples), self.ul_bler,
                                     self.ul_mcs)

    def _read_stats_file(self, path, since=None):
        """Return the file's text, or None if it's missing or older than `since`
        (default: the gNB start, i.e. left over from the previous run)."""
        try:
            if os.path.getmtime(path) < (self._gnb_start_time if since is None else since):
                return None
            with open(path) as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def _bler(rounds, errors):
        """First-round BLER: share of first transmissions that needed a retransmission.

        OAI prints `rounds` as "r0/r1/r2/r3": r0 = first transmissions, r1 = first
        retransmissions (one per failed first transmission), so BLER = r1 / r0.
        With harq_round_max = 1 only r0 is printed and every failure goes straight to
        `errors`, so then BLER = errors / r0."""
        counts = [int(c) for c in rounds.split("/")]
        if not counts[0]:
            return 0.0
        failed = counts[1] if len(counts) > 1 else int(errors)
        return failed / counts[0]

    
    # ---- shutdown -------------------------------------------------------------
    def closeEvent(self, event):
        if self._closing:
            super().closeEvent(event)
            return

        event.ignore()
        self._closing = True
        self._save_bulk_settings()
        self._bulk_running = False
        if self.timer is not None:
            self.timer.stop()
        # self._signal_process_group(self.stopper, signal.SIGTERM)
        self.stop_all()

        # Give managed process groups time to exit before escalating.
        QTimer.singleShot(2000, self._finish_shutdown)

    def _finish_shutdown(self):
        self._force_kill_managed_processes()
        super().close()

  
    # # ---- save runs in file -------------------------------------------------------------
    # def save_run(self):
    #     """Save the current run's configuration and stats to a text file, and save the log files in the same directory"""
    #     print("Saving run...")
    #     # #create special identifier
    #     # os.makedirs(SAVE_DIR, exist_ok=True)
    #     # file = os.path.join(SAVE_DIR, f"run_{time.strftime('%Y-%m-%d_%H-%M-%S')}.txt")

    #     with open(file, "w") as f:
    #         f.write(f"Run saved at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    #         f.write(f"gNB config: {self._gnb_conf_path()}\n")
    #         f.write(f"UE config: {self._ue_conf_path()}\n")
    #         f.write(f"DL MCS: {self.dl_mcs}\n")
    #         f.write(f"UL MCS: {self.ul_mcs}\n")
    #         f.write(f"DL BLER: {self.dl_bler:.5f}\n")
    #         f.write(f"UL BLER: {self.ul_bler:.5f}\n")
    #         f.write(f"SNR: {self.snr:.5f} dB\n")
    #         f.write(f"run time: {self._gnb_end_time - self._gnb_start_time:.2f} s\n") 

    #     #     f.write("Packets sent: \n") #fill in here
        
        




def main():
    # Qt's GTK3 theme loads GTK, which aborts on this machine's GNOME 42 ("...xsettings does not
    # contain a key named 'antialiasing'"). Qt's built-in GNOME theme avoids GTK.
    if sys.platform.startswith("linux"):
        if os.environ.get("QT_QPA_PLATFORMTHEME", "") in ("", "gtk3", "xdgdesktopportal"):
            os.environ["QT_QPA_PLATFORMTHEME"] = "gnome"
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
