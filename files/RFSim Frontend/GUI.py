"""RFSim Frontend: a basic PyQt6 GUI for running OAI RFSim (gNB + UE).

Run:  python3 GUI.py        (needs: pip install PyQt6)

Planned features (README.md) - each has an empty TODO block below:
  1. Instantiate the gNB                      -> start_gnb() / stop_gnb()
  2. Instantiate the UE                       -> start_ue() / stop_ue()
  3. Interchangeable .conf files              -> browse_gnb_config() / browse_ue_config()
  4. Print BLER and SNR (like OAI Live Stats) -> refresh_stats() / update_stats()
"""
import os
import sys
import subprocess
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
STATS_REFRESH_MS = 1000                  # how often refresh_stats() should run once implemented


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RFSim Frontend")
        self.resize(1000, 700)
        self._build_widgets()

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
        self.gnb_status = QLabel("gNB: stopped")
        self.ue_status = QLabel("UE: stopped")
        for row, (name, status, start, stop) in enumerate((
                ("gNB", self.gnb_status, self.start_gnb, self.stop_gnb),
                ("UE", self.ue_status, self.start_ue, self.stop_ue))):
            grid.addWidget(status, row, 0)
            grid.addWidget(self._button(f"Start {name}", start), row, 1)
            grid.addWidget(self._button(f"Stop {name}", stop), row, 2)
        grid.addWidget(self._button("Stop all", self.stop_all), 0, 3, 2, 1)
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
        # TODO: open a file dialog (QFileDialog.getOpenFileName, filter "*.conf", start in CONF_DIR)
        # TODO: if a file was chosen, self.gnb_conf.setText(path)
        file_name = QFileDialog.getOpenFileName(self, "Select gNB .conf file", CONF_DIR, "Config files (*.conf)")
        pass

    def browse_ue_config(self):
        """Pick a UE .conf file and put its path in self.ue_conf."""
        # TODO: same as browse_gnb_config, for self.ue_conf
        pass

    # ---- 1. gNB ---------------------------------------------------------------
    def start_gnb(self):
        """Launch nr-softmodem in RFSim mode with the selected gNB .conf."""
        # TODO: check that self.gnb_conf.text() exists
        # TODO: start nr-softmodem in OAI_BUILD_DIR (e.g. with QProcess) using -O <conf> --rfsim ...
        # TODO: send its stdout/stderr to self.gnb_log
        # TODO: update self.gnb_status
        pass

    def stop_gnb(self):
        """Stop the running gNB process."""
        # TODO: terminate the gNB process, then update self.gnb_status
        pass

    # ---- 2. UE ----------------------------------------------------------------
    def start_ue(self):
        """Launch nr-uesoftmodem in RFSim mode with the selected UE .conf."""
        # TODO: check that self.ue_conf.text() exists (and that the gNB is running)
        # TODO: start nr-uesoftmodem in OAI_BUILD_DIR using -O <conf> --rfsim ...
        # TODO: send its stdout/stderr to self.ue_log
        # TODO: update self.ue_status
        pass

    def stop_ue(self):
        """Stop the running UE process."""
        # TODO: terminate the UE process, then update self.ue_status
        pass

    def stop_all(self):
        """Stop the UE, then the gNB."""
        # TODO: call stop_ue() and stop_gnb()
        pass

    # ---- 4. BLER / SNR live stats --------------------------------------------
    def refresh_stats(self):
        """Read the latest BLER and SNR values (called every STATS_REFRESH_MS once a timer is set up)."""
        # TODO: create a QTimer in __init__ that calls this every STATS_REFRESH_MS
        # TODO: get the values (parse the process output, or read OAI's stats files)
        # TODO: pass them to update_stats()
        pass

    def update_stats(self, values):
        """Show stats on screen. values: {"DL BLER": ..., "UL BLER": ..., "DL SNR (dB)": ..., "UL SNR (dB)": ...}"""
        # TODO: for each key in values, self.stat_labels[key].setText(...)
        pass

    # ---- shutdown -------------------------------------------------------------
    def closeEvent(self, event):
        # TODO: stop any running processes before the window closes (stop_all())
        super().closeEvent(event)


def main():
    # Qt's GTK3 theme loads GTK, which aborts on this machine's GNOME 42 ("...xsettings does not
    # contain a key named 'antialiasing'"). Qt's built-in GNOME theme avoids GTK.
    if os.environ.get("QT_QPA_PLATFORMTHEME", "") in ("", "gtk3", "xdgdesktopportal"):
        os.environ["QT_QPA_PLATFORMTHEME"] = "gnome"
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
