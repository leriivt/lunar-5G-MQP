"""'Choose MCS...' dialog for bulk runs: a table of every MCS (0-28) with a tick box and a centre
SINR. On OK it returns the ticked rows in the text format the bulk box's 'MCS : centre SINR'
field takes ('0: -3; 9: 6; ...'), so the field stays the single source of what a bulk run uses.

Centres of unticked rows are remembered too (centres_all()), so the GUI can save them and an
MCS can be switched off and on again without retyping its centre.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout,
                             QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget, QVBoxLayout,
                             QWidget)

from plans import centered_sinr_points

MCS_MAX = 28
RUN_OVERHEAD_S = 5          # per run on top of settle + attach + measure: stopping the processes
                            # and the 2 s pause before the next run (GUI._bulk_wait_stopped)


def default_center(mcs):
    """Starting guess for a centre SINR (dB): MCS 9 at the ~6 dB measured on this link, about
    1 dB per MCS step, smaller steps where 16QAM (10) and 64QAM (17) begin."""
    table = [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12, 13, 13.5,
             14.5, 15.5, 16.5, 17.5, 18.5, 19.5, 20.5, 21.5, 22.5, 23.5]
    return float(table[mcs])


def format_centers(centers):
    """{mcs: centre} -> '0: -3; 9: 6; ...' (the bulk box's text format)."""
    return "; ".join(f"{m}: {c:g}" for m, c in sorted(centers.items()))


def format_duration(seconds):
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h} h {m:02d} min" if h else (f"{m} min {s:02d} s" if m else f"{s} s")


class McsCenterDialog(QDialog):
    """selected: {mcs: centre} now in the bulk box (ticked); remembered: {mcs: centre} for every
    MCS from earlier edits; span/step: the box's +- range and step; n_plans: site plans ticked
    (0 = raw template, counted as 1); per_run_s: settle + attach + measure seconds."""

    def __init__(self, parent, selected, remembered, span, step, n_plans, per_run_s):
        super().__init__(parent)
        self.setWindowTitle("Choose MCS and centre SINR")
        self._span, self._step = span, step
        self._n_plans, self._per_run_s = max(n_plans, 1), per_run_s
        v = QVBoxLayout(self)

        # quick select: all / none / a range
        quick = QHBoxLayout()
        for text, fn in (("All", lambda: self._tick(range(MCS_MAX + 1), True)),
                         ("None", lambda: self._tick(range(MCS_MAX + 1), False))):
            quick.addWidget(self._button(text, fn))
        quick.addSpacing(16)
        quick.addWidget(QLabel("MCS"))
        self.range_lo, self.range_hi = QSpinBox(), QSpinBox()
        for box, value in ((self.range_lo, 0), (self.range_hi, MCS_MAX)):
            box.setRange(0, MCS_MAX)
            box.setValue(value)
        quick.addWidget(self.range_lo)
        quick.addWidget(QLabel("to"))
        quick.addWidget(self.range_hi)
        quick.addWidget(self._button("Tick range", lambda: self._tick(self._range(), True)))
        quick.addWidget(self._button("Untick range", lambda: self._tick(self._range(), False)))
        quick.addStretch()
        v.addLayout(quick)

        self.table = QTableWidget(MCS_MAX + 1, 3)
        self.table.setHorizontalHeaderLabels(["Run", "MCS", "Centre SINR"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.checks, self.centers = [], []
        for mcs in range(MCS_MAX + 1):
            check = QCheckBox()
            check.setChecked(mcs in selected)
            check.toggled.connect(self._update_summary)
            holder = QWidget()                      # centre the tick box in its cell
            h = QHBoxLayout(holder)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(check, alignment=Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(mcs, 0, holder)
            label = QLabel(str(mcs))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(mcs, 1, label)
            center = QDoubleSpinBox()
            center.setRange(-50.0, 100.0)
            center.setDecimals(1)
            center.setSingleStep(0.5)
            center.setSuffix(" dB")
            center.setValue(selected.get(mcs, remembered.get(mcs, default_center(mcs))))
            self.table.setCellWidget(mcs, 2, center)
            self.checks.append(check)
            self.centers.append(center)
        v.addWidget(self.table, 1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.resize(460, 720)
        self._update_summary()

    def _button(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        return b

    def _range(self):
        lo, hi = sorted((self.range_lo.value(), self.range_hi.value()))
        return range(lo, hi + 1)

    def _tick(self, mcs_range, on):
        for mcs in mcs_range:
            self.checks[mcs].setChecked(on)

    def _update_summary(self):
        n_mcs = sum(c.isChecked() for c in self.checks)
        per_mcs = len(centered_sinr_points(0.0, self._span, self._step))
        runs = self._n_plans * n_mcs * per_mcs
        plans = f" x {self._n_plans} plans" if self._n_plans > 1 else ""
        self.summary.setText(
            f"{n_mcs} MCS x {per_mcs} SINR points (±{self._span:g} dB, step {self._step:g} dB)"
            f"{plans} = {runs} runs, about {format_duration(runs * (self._per_run_s + RUN_OVERHEAD_S))} "
            f"(without TA-drift retries)")

    def selected(self):
        """{mcs: centre} of the ticked rows."""
        return {m: self.centers[m].value() for m in range(MCS_MAX + 1) if self.checks[m].isChecked()}

    def centres_all(self):
        """{mcs: centre} for every row, ticked or not."""
        return {m: self.centers[m].value() for m in range(MCS_MAX + 1)}
