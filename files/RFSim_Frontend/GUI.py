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
from PyQt6.QtWidgets import (QApplication, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                             QTabWidget,
                             QVBoxLayout, QWidget, QFileDialog)

# GUI.py sits in a subfolder; plans.py, settings.py, export.py and the planner are one level up
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from plans import (append_row, build_queue, delete_plan, load_plans, make_bulk_run, parse_mcs,
                   run_dir, sinr_points, write_run_confs)
from settings import APP_DIR, BULK_ATTACH_S, BULK_MEASURE_S, BULK_SETTLE_S, PLANS_DIR

# ----------------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------------
OAI_DIR = "/home/lunar5g/openairinterface5g"
OAI_BUILD_DIR = os.path.join(OAI_DIR, "cmake_targets", "ran_build", "build")
#CONF_DIR = os.path.join(OAI_DIR, "targets", "PROJECTS", "GENERIC-NR-5GC", "CONF")
CONF_DIR = os.path.join(OAI_DIR, "targets", "PROJECTS", "GENERIC-NR-5GC", "CONF", "RF_SIMULATION")
DEFAULT_GNB_CONF = os.path.join(CONF_DIR, "gnb0.sa.band78.fr1.106PRB.prs.usrpx310.conf")
DEFAULT_UE_CONF = os.path.join(CONF_DIR, "ue.bictr.conf")
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
# "ulsch_power[0] 50,0 ulsch_noise_power[0] 30.8" (OAI prints the first value with a comma)
UL_SNR_RE = re.compile(r"ulsch_power\[0\] (\d+[.,]\d) ulsch_noise_power\[0\] (\d+[.,]\d)")

DEFAULT_SAVE_DIR = os.path.join(Path(__file__).parent, "saved_runs")
SAVE_DIR = DEFAULT_SAVE_DIR

# Bulk data collection: the site planner sits next to this file, plans are saved in PLANS_DIR
PLANNER_SCRIPT = os.path.join(APP_DIR, "qt_lunar_site_planner.py")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RFSim Frontend")
        self.resize(1000, 900)
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
        self._gnb_start_time = time.time()
        self.sim_mode = True  # default simulation mode: true for RFSim, False for PHY test mode
    # ---- layout --------------------------------------------------------------
    def _build_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Config files: one row per node, path box + Browse
        configs = QGroupBox("Config files")
        form = QFormLayout(configs)
        self.gnb_conf = QLineEdit(DEFAULT_GNB_CONF)
        self.ue_conf = QLineEdit(DEFAULT_UE_CONF) 

        form.addRow("gNB .conf", self._path_row(self.gnb_conf, self.browse_gnb_config))
        form.addRow("UE .conf", self._path_row(self.ue_conf, self.browse_ue_config))
        layout.addWidget(configs)

        # Run output directory
        output = QGroupBox("Run output")
        output_form = QFormLayout(output)
        self.save_dir_edit = QLineEdit(SAVE_DIR)
        self.save_dir_edit.setReadOnly(True)
        output_form.addRow("Save directory", self._path_row(self.save_dir_edit, self.browse_save_dir))
        layout.addWidget(output)

        layout.addWidget(self._build_bulk_group())

        # Process controls: start/stop buttons and a status label per node
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
        layout.addWidget(controls)

        # Live stats: one value label per metric
        stats = QGroupBox("Live stats")
        stats_row = QHBoxLayout(stats)
        self.stat_labels = {}
        for key in ("DL BLER", "UL BLER", "DL SNR (dB)", "UL SNR (dB)"):
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
        layout.addWidget(self.logs, 1)

    # ---- bulk data collection ------------------------------------------------
    def _build_bulk_group(self):
        """Site plans (made in the planner), MCS list, SINR range, output folder."""
        os.makedirs(PLANS_DIR, exist_ok=True)
        group = QGroupBox("Bulk data collection (BLER / SINR vs MCS)")
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

        form = QFormLayout()
        self.mcs_edit = QLineEdit("0-27")
        self.mcs_edit.setToolTip("MCS indices, e.g. 0-9, 12, 15-20  (valid range 0-28)")
        form.addRow("MCS to run", self.mcs_edit)

        sinr_row = QHBoxLayout()
        self.sinr_min, self.sinr_max, self.sinr_step = (QDoubleSpinBox() for _ in range(3))
        for box, value in ((self.sinr_min, -5.0), (self.sinr_max, 30.0)):
            box.setRange(-50.0, 100.0)
            box.setDecimals(1)
            box.setValue(value)
            box.setSuffix(" dB")
        self.sinr_step.setRange(0.1, 50.0)
        self.sinr_step.setDecimals(1)
        self.sinr_step.setValue(1.0)
        self.sinr_step.setSuffix(" dB")
        for label, box in (("from", self.sinr_min), ("to", self.sinr_max), ("step", self.sinr_step)):
            sinr_row.addWidget(QLabel(label))
            sinr_row.addWidget(box)
        sinr_row.addStretch()
        form.addRow("SINR range", sinr_row)

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

        # new plans saved from the planner show up without pressing Refresh
        self.plan_watcher = QFileSystemWatcher([PLANS_DIR], self)
        self.plan_watcher.directoryChanged.connect(lambda _path: self.refresh_plans())
        self.bulk_dir = None
        self._bulk_running = False
        self._bulk_gen = 0              # bumped on abort so stale timers do nothing
        self._bulk_queue, self._bulk_i = [], 0
        self._bulk_saved_confs = None
        self.refresh_plans()
        return group

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
        """Reload the plan list, keeping the ticks of plans that are still there."""
        ticked = {self.plan_list.item(i).data(Qt.ItemDataRole.UserRole)
                  for i in range(self.plan_list.count())
                  if self.plan_list.item(i).checkState() == Qt.CheckState.Checked}
        first_load = self.plan_list.count() == 0
        self.plan_list.clear()
        for plan in load_plans():
            item = QListWidgetItem(f"{plan['name']}  [{plan['region_label']}, "
                                   f"{plan.get('separation_m', '?')} m]")
            item.setData(Qt.ItemDataRole.UserRole, plan["file"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = plan["file"] in ticked or first_load
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
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
        plans = self.checked_plans()
        if not plans:
            QMessageBox.warning(self, "Bulk run", "Tick at least one site plan "
                                "(open the site planner to make some).")
            return False
        try:
            mcs = parse_mcs(self.mcs_edit.text())
            sinr = sinr_points(self.sinr_min.value(), self.sinr_max.value(), self.sinr_step.value())
        except ValueError as err:
            QMessageBox.warning(self, "Bulk run", str(err))
            return False
        runs = len(plans) * len(mcs) * len(sinr)
        parent = SAVE_DIR          # the "Run output" save directory; the bulk folder is created inside it
        try:
            os.makedirs(parent, exist_ok=True)
            self.bulk_dir = make_bulk_run(parent, plans, mcs, sinr)
        except OSError as err:
            QMessageBox.critical(self, "Bulk run", f"Could not create the folder:\n{err}")
            return False
        self.bulk_status.setText(f"Created {self.bulk_dir}\n{len(plans)} plan(s) x {len(mcs)} MCS x "
                                 f"{len(sinr)} SINR points = {runs} runs")
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
        self.bulk_status.setText(f"Run {self._bulk_i + 1}/{len(self._bulk_queue)}: {key}, "
                                 f"MCS {mcs}, target SINR {sinr:g} dB (starting gNB)")
        self.start_gnb()
        self._later(self.settle_s.value() * 1000, self._bulk_start_ue)

    def _bulk_start_ue(self):
        self.start_ue()
        self.bulk_status.setText(self.bulk_status.text().replace("starting gNB", "UE attaching"))
        self._later(self.attach_s.value() * 1000, self._bulk_measure_begin)

    def _bulk_measure_begin(self):
        self.bulk_status.setText(self.bulk_status.text().replace("UE attaching", "measuring"))
        self._bulk_left = self.measure_s.value()
        self._bulk_sample()

    def _bulk_sample(self):
        """Once a second: note the stats if the gNB's dump files are fresh."""
        mac, l1 = self._read_stats_file(NR_MAC_STATS), self._read_stats_file(NR_L1_STATS)
        s = self._bulk_samples
        if mac and DL_RE.search(mac):
            s["dl"].append(self.dl_bler)
        if mac and UL_RE.search(mac):
            s["ul"].append(self.ul_bler)
        if l1 and UL_SNR_RE.search(l1):
            s["snr"].append(self.snr)
        self._bulk_left -= 1
        self._later(1000, self._bulk_sample if self._bulk_left > 0 else self._bulk_finish_run)

    def _bulk_finish_run(self):
        """Record the row, keep the raw logs, stop everything, then start the next run."""
        key, mcs, sinr = self._bulk_queue[self._bulk_i]
        s = self._bulk_samples
        fmt = lambda v: f"{v:.6f}" if v is not None else ""
        # BLER counters in OAI's dumps are cumulative since the gNB started, so the last value is
        # the run's BLER; SNR fluctuates, so it is averaged.
        append_row(self.bulk_dir, {
            "plan": key, "mcs": mcs, "target_sinr_db": f"{sinr:g}",
            "dl_bler": fmt(s["dl"][-1] if s["dl"] else None),
            "ul_bler": fmt(s["ul"][-1] if s["ul"] else None),
            "ul_snr_db": fmt(sum(s["snr"]) / len(s["snr"]) if s["snr"] else None),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")})
        out = run_dir(self.bulk_dir, key, mcs, sinr)
        for name, log in (("gnb.log", self.gnb_log), ("ue.log", self.ue_log)):
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
        self._bulk_i += 1
        self._later(2000, self._bulk_next)

    def start_timer(self):
        if self.timer is not None:
            return  # Timer already running
        self.timer = QTimer()
        self.timer.setInterval(STATS_REFRESH_MS) #set timer interval to check BLER, SNR every 100ms
        self.timer.timeout.connect(self.live_stats)
        self.timer.start()
    
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
    def browse_gnb_config(self):
        """Pick a gNB .conf file and put its path in self.gnb_conf."""
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select gNB .conf file", CONF_DIR, "Config files (*.conf)"
        )
        if file_name:
            self.gnb_conf.setText(file_name)
        

    def browse_ue_config(self):
        """Pick a UE .conf file and put its path in self.ue_conf."""
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select UE .conf file", CONF_DIR, "Config files (*.conf)"
        )
        if file_name:
            self.ue_conf.setText(file_name)
        
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
    def start_gnb(self):
        """Launch nr-softmodem in RFSim mode with the selected gNB .conf."""
        if self.p_gnb is not None and self.p_gnb.state() != QProcess.ProcessState.NotRunning:
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
        process.start("bash", [GNB_MAKE, self._gnb_conf_path()])
        self._gnb_start_time = time.time()
        self.start_timer()  # Start the timer to refresh stats
        self.gnb_status.setText("gNB: Starting")
  

    # ---- 2. UE ----------------------------------------------------------------
    def start_ue(self):
        """Launch nr-uesoftmodem in RFSim mode with the selected UE .conf."""
        if self.p_ue is not None and self.p_ue.state() != QProcess.ProcessState.NotRunning:
            return
        self.p_ue = QProcess()
        process = self.p_ue
        process.readyReadStandardOutput.connect(self._read_ue_output)
        process.readyReadStandardError.connect(self._read_ue_output)
        process.started.connect(lambda: self.ue_status.setText("UE: Running"))
        process.finished.connect(lambda *_: self._ue_finished(process))
        process.errorOccurred.connect(
            lambda error: self._process_error("UE", process, error)
        )
        
        process.start("bash", [UE_MAKE, self._ue_conf_path()])
        self.ue_status.setText("UE: Starting")

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
                self.ue_log.appendPlainText(bytes(data).decode(errors="replace"))

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

    def live_stats(self):
        """Parse the gNB's stats dumps and update the lives stats inside"""
        mac = self._read_stats_file(NR_MAC_STATS)
        if mac is not None:
            dl = DL_RE.search(mac)
            if dl:
                self.dl_bler = self._bler(*dl.groups())
                self.stat_labels["DL BLER"].setText(f"{self.dl_bler:.3f}")
            ul = UL_RE.search(mac)
            if ul:
                self.ul_bler = self._bler(*ul.groups())
                self.stat_labels["UL BLER"].setText(f"{self.ul_bler:.3f}")
        l1 = self._read_stats_file(NR_L1_STATS)
        if l1 is not None:
            m = UL_SNR_RE.search(l1)
            if m:
                power, noise = (float(g.replace(",", ".")) for g in m.groups())
                self.snr = power - noise
                self.stat_labels["UL SNR (dB)"].setText(f"{self.snr:.1f}")



    def _read_stats_file(self, path):
        """ return the file's text, or NINE if its missing or left over frim the previous run"""
        try:
            if os.path.getmtime(path) < self._gnb_start_time:
                return None
            with open(path) as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def _bler(rounds, errors):
        """residual BLER: blocks still failed after the last HARQ round / first transmissions"""
        first_tx = int(rounds.split("/")[0])
        return int(errors) / first_tx if first_tx else 0.0

    
    # ---- shutdown -------------------------------------------------------------
    def closeEvent(self, event):
        if self._closing:
            super().closeEvent(event)
            return

        event.ignore()
        self._closing = True
        self._bulk_running = False
        if self.timer is not None:
            self.timer.stop()
        self.stop_all()

        # Give the stop script and QProcess terminate signals time to finish.
        QTimer.singleShot(2000, self._finish_shutdown)

    def _finish_shutdown(self):
        self._force_kill_managed_processes()
        if self.stopper is not None and self.stopper.state() != QProcess.ProcessState.NotRunning:
            self.stopper.kill()
        super().close()

  
    # ---- save runs in file -------------------------------------------------------------
    def save_run(self):

        #create special identifier
        os.makedirs(SAVE_DIR, exist_ok=True)
        file = os.path.join(SAVE_DIR, f"run_{time.strftime('%Y-%m-%d_%H-%M-%S')}.txt")

        with open(file, "w") as f:
            f.write(f"Run saved at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"gNB config: {self._gnb_conf_path()}\n")
            f.write(f"UE config: {self._ue_conf_path()}\n")
            f.write(f"DL BLER: {self.dl_bler:.5f}\n")
            f.write(f"UL BLER: {self.ul_bler:.5f}\n")
            f.write(f"SNR: {self.snr:.5f} dB\n")
            f.write(f"run time: {self._gnb_end_time - self._gnb_start_time:.2f} s\n") 

            f.write("Packets sent: \n") #fill in here




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
