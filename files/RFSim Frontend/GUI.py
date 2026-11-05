"""RFSim Frontend: a basic PyQt6 GUI for running OAI RFSim (gNB + UE)

Needs: 
    pip install PyQt6
    pip install sh

Run:  python3 GUI.py     

"""
import os
import sys
from pathlib import Path
from PyQt6.QtCore import QProcess, QTimer
from PyQt6.QtWidgets import (QApplication, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QTabWidget,
                             QVBoxLayout, QWidget, QFileDialog)

# ----------------------------------------------------------------------------
# SETTINGS
# ----------------------------------------------------------------------------
OAI_DIR = "/home/lunar5g/openairinterface5g"
OAI_BUILD_DIR = os.path.join(OAI_DIR, "cmake_targets", "ran_build", "build")
CONF_DIR = os.path.join(OAI_DIR, "targets", "PROJECTS", "GENERIC-NR-5GC", "CONF")
DEFAULT_GNB_CONF = os.path.join(CONF_DIR, "gnb.sa.band78.fr1.106PRB.usrpb210.bictr.conf")
DEFAULT_UE_CONF = os.path.join(CONF_DIR, "ue.bictr.conf")
STATS_REFRESH_MS = 100      # how often refresh_stats() should run once implemented

#TODO Get around sudo issue and modify these bash scripts

SH_DIR = "/home/lunar5g/.local/share/oai-shortcuts"
UE_MAKE = os.path.join(SH_DIR, "ue-bictr_gui.sh")
GNB_MAKE = os.path.join(SH_DIR, "gnb-bictr_gui.sh")
STOP_ALL = os.path.join(SH_DIR, "stop-all.sh")
LIVE_STATS = os.path.join(SH_DIR, "stats.sh")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RFSim Frontend")
        self.resize(1000, 700)
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

    def start_timer(self):
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
        # Finds directory where BLER, SNR, HARQ are being calculated and prints those values to stdout
        #
        #self.live_path = 
        #
        #self.ul_bler = 
        #self.dl_bler = 
        #self.snr = 

        pass

    # ---- shutdown -------------------------------------------------------------
    def closeEvent(self, event):
        if self._closing:
            super().closeEvent(event)
            return

        event.ignore()
        self._closing = True
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

        #save logs, config, everything
        pass


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
