"""Live time-series graph for the RFSim GUI: BLER, UL SNR and MCS against time since gNB start.

Three stacked panels share one time axis (they have different units):
    BLER      DL and UL first-round BLER, 0..1
    UL SNR    measured UL SNR in dB (auto-scaled), with the run's target SINR dashed
    MCS       DL and UL MCS, 0..28
Vertical lines mark when the UE synced and when a bulk run's measure window began.
Drawn with QPainter, no plotting library.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

WINDOW_S = 180.0          # seconds of history shown (older points scroll off the left)
MAX_POINTS = 4000         # per series, oldest dropped first

DL_COLOR, UL_COLOR = QColor("#1f77b4"), QColor("#e8710a")
SNR_COLOR, TARGET_COLOR = QColor("#139c8a"), QColor("#777777")
MARKER_COLOR = QColor("#9c27b0")

# panel title, y range (None = auto), series drawn in it: (name, colour)
PANELS = [
    ("BLER", (0.0, 1.0), [("DL BLER", DL_COLOR), ("UL BLER", UL_COLOR)]),
    ("UL SNR (dB)", None, [("UL SNR", SNR_COLOR)]),
    ("MCS", (0.0, 28.0), [("DL MCS", DL_COLOR), ("UL MCS", UL_COLOR)]),
]


class LiveGraph(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.clear()

    # ---- data ----------------------------------------------------------------
    def clear(self):
        """Forget everything (called when the gNB starts)."""
        self.series = {name: [] for _, _, names in PANELS for name, _ in names}
        self.markers = []          # (t, label)
        self.target_sinr = None
        self.t_now = 0.0
        self.update()

    def add(self, name, t, value):
        pts = self.series[name]
        pts.append((t, float(value)))
        if len(pts) > MAX_POINTS:
            del pts[:len(pts) - MAX_POINTS]
        self.t_now = max(self.t_now, t)

    def tick(self, t):
        """Move the time axis to t and redraw (once per stats refresh)."""
        self.t_now = max(self.t_now, t)
        self.update()

    def mark(self, t, label):
        self.markers.append((t, label))
        self.update()

    def set_target_sinr(self, value):
        self.target_sinr = value
        self.update()

    # ---- drawing -------------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        left, right, top, bottom, gap = 62, 110, 8, 26, 10
        t1 = max(self.t_now, 10.0)
        t0 = max(0.0, t1 - WINDOW_S)
        h = (self.height() - top - bottom - gap * (len(PANELS) - 1)) / len(PANELS)
        w = self.width() - left - right
        for i, (title, yrange, names) in enumerate(PANELS):
            rect = QRectF(left, top + i * (h + gap), w, h)
            self._panel(p, rect, title, yrange, names, t0, t1, last=i == len(PANELS) - 1)
        p.end()

    def _panel(self, p, rect, title, yrange, names, t0, t1, last):
        visible = [v for name, _ in names for t, v in self.series[name] if t >= t0]
        if title.startswith("UL SNR") and self.target_sinr is not None:
            visible.append(self.target_sinr)
        if yrange is None:
            lo, hi = (min(visible), max(visible)) if visible else (0.0, 10.0)
            pad = max(1.0, (hi - lo) * 0.15)
            yrange = (lo - pad, hi + pad)
        y0, y1 = yrange

        def px(t, v):
            return QPointF(rect.left() + (t - t0) / (t1 - t0) * rect.width(),
                           rect.bottom() - (min(max(v, y0), y1) - y0) / (y1 - y0) * rect.height())

        small = QFont("Sans", 8)
        p.setFont(small)
        # horizontal grid: 5 divisions
        for k in range(6):
            v = y0 + (y1 - y0) * k / 5
            y = px(t0, v).y()
            p.setPen(QPen(QColor("#e6e6e6"), 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            p.setPen(QColor("#444"))
            label = f"{v:.1f}" if (y1 - y0) <= 5 else f"{v:.0f}"
            p.drawText(QRectF(rect.left() - 46, y - 8, 40, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        # vertical grid every 10/30 s
        step = 10 if t1 - t0 <= 60 else 30
        t = (int(t0) // step + 1) * step
        while t <= t1:
            x = px(t, y0).x()
            p.setPen(QPen(QColor("#efefef"), 1))
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            if last:
                p.setPen(QColor("#444"))
                p.drawText(QRectF(x - 25, rect.bottom() + 3, 50, 14), Qt.AlignmentFlag.AlignHCenter, f"{t}s")
            t += step
        p.setPen(QPen(QColor("#888"), 1))
        p.drawRect(rect)
        # markers (UE sync, measure start)
        for tm, label in self.markers:
            if t0 <= tm <= t1:
                x = px(tm, y0).x()
                p.setPen(QPen(MARKER_COLOR, 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                if title == "BLER":
                    p.setPen(MARKER_COLOR)
                    p.drawText(QPointF(x + 3, rect.top() + 11), label)
        # target SINR
        if title.startswith("UL SNR") and self.target_sinr is not None:
            y = px(t0, self.target_sinr).y()
            p.setPen(QPen(TARGET_COLOR, 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        # series
        p.setClipRect(rect.adjusted(-2, -2, 2, 2))
        for name, color in names:
            pts = [px(t, v) for t, v in self.series[name] if t >= t0 - 1]
            p.setPen(QPen(color, 2))
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
            if len(pts) == 1:
                p.drawEllipse(pts[0], 2, 2)
        p.setClipping(False)
        # title + legend with latest values, right of the panel
        lx = rect.right() + 8
        p.setFont(QFont("Sans", 9, QFont.Weight.DemiBold))
        p.setPen(QColor("#222"))
        p.drawText(QPointF(lx, rect.top() + 12), title)
        p.setFont(small)
        row = rect.top() + 28
        for name, color in names:
            pts = self.series[name]
            val = pts[-1][1] if pts else None
            text = name if val is None else f"{name}: {val:.3f}" if title == "BLER" else f"{name}: {val:.1f}" \
                if title.startswith("UL SNR") else f"{name}: {val:.0f}"
            p.setPen(QPen(color, 3))
            p.drawLine(QPointF(lx, row - 4), QPointF(lx + 12, row - 4))
            p.setPen(QColor("#222"))
            p.drawText(QPointF(lx + 16, row), text)
            row += 15
        if title.startswith("UL SNR") and self.target_sinr is not None:
            p.setPen(QPen(TARGET_COLOR, 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(lx, row - 4), QPointF(lx + 12, row - 4))
            p.setPen(QColor("#222"))
            p.drawText(QPointF(lx + 16, row), f"target: {self.target_sinr:g}")


class BlerSnrGraph(QWidget):
    """UL BLER vs mean UL SNR, built up while runs happen (the live version of bulk_plot).

    Finished runs: the bulk run's CSV points (ok runs only, repeats averaged), one colour-coded
    curve per MCS. Current run: a hollow diamond at (mean UL SNR so far, UL BLER so far) that
    moves as the run goes on, in its MCS colour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.curves = {}           # {(plan, mcs): [(snr, bler), ...]} from bulk_plot.load_curves
        self.live = None           # (snr, bler, mcs) of the run in progress

    def set_curves(self, curves):
        self.curves = curves or {}
        self.update()

    def set_live(self, snr=None, bler=None, mcs=None):
        self.live = None if snr is None or bler is None else (snr, bler, mcs)
        self.update()

    def paintEvent(self, _event):
        from bulk_plot import _marker, _nice_step, mcs_color   # same colours/markers as the saved plot
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        legend_w = 70
        rect = QRectF(46, 24, self.width() - 46 - 10 - legend_w, self.height() - 24 - 36)
        p.setPen(QColor("#222"))
        p.setFont(QFont("Sans", 9, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, 3, self.width() - legend_w, 18), Qt.AlignmentFlag.AlignHCenter,
                   "UL BLER vs mean UL SNR")
        small = QFont("Sans", 8)
        p.setFont(small)
        xs = [x for pts in self.curves.values() for x, _ in pts]
        if self.live:
            xs.append(self.live[0])
        x0, x1 = (min(xs), max(xs)) if xs else (0.0, 10.0)
        if x1 - x0 < 2:
            x0, x1 = (x0 + x1) / 2 - 1, (x0 + x1) / 2 + 1
        step = _nice_step(x1 - x0)
        x0, x1 = math.floor(x0 / step) * step, math.ceil(x1 / step) * step

        def px(x, y):
            return QPointF(rect.left() + (x - x0) / (x1 - x0) * rect.width(),
                           rect.bottom() - min(max(y, 0.0), 1.0) * rect.height())

        for k in range(11):                                    # BLER 0..1 every 0.1
            y = px(x0, k / 10).y()
            p.setPen(QPen(QColor("#e6e6e6"), 1))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            if k % 2 == 0:
                p.setPen(QColor("#444"))
                p.drawText(QRectF(rect.left() - 40, y - 8, 34, 16),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{k / 10:.1f}")
        for i in range(int(round((x1 - x0) / step)) + 1):
            x = x0 + i * step
            xp = px(x, 0).x()
            p.setPen(QPen(QColor("#efefef"), 1))
            p.drawLine(QPointF(xp, rect.top()), QPointF(xp, rect.bottom()))
            p.setPen(QColor("#444"))
            p.drawText(QRectF(xp - 22, rect.bottom() + 3, 44, 14), Qt.AlignmentFlag.AlignHCenter, f"{x:g}")
        p.drawText(QRectF(rect.left(), rect.bottom() + 17, rect.width(), 14),
                   Qt.AlignmentFlag.AlignHCenter, "mean UL SNR (dB)")
        p.setPen(QPen(QColor("#888"), 1))
        p.drawRect(rect)

        p.setClipRect(rect.adjusted(-6, -6, 6, 6))
        for (_plan, mcs), pts in sorted(self.curves.items()):
            color = mcs_color(mcs)
            pp = [px(x, y) for x, y in pts]
            p.setPen(QPen(color, 2))
            for a, b in zip(pp, pp[1:]):
                p.drawLine(a, b)
            p.setBrush(color)
            for pt in pp:
                _marker(p, pt, 0, r=3)
        if self.live:
            snr, bler, mcs = self.live
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(mcs_color(mcs if mcs is not None else 0), 2.5))
            _marker(p, px(snr, bler), 3, r=6)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # legend: MCS colours, then the live marker
        lx, ly = rect.right() + 10, rect.top() + 4
        mcs_list = sorted({m for _, m in self.curves} | ({self.live[2]} if self.live and self.live[2] is not None else set()))
        p.setFont(QFont("Sans", 8, QFont.Weight.DemiBold))
        p.setPen(QColor("#222"))
        p.drawText(QPointF(lx, ly + 8), "MCS")
        p.setFont(small)
        for i, m in enumerate(mcs_list[:14]):
            y = ly + 22 + i * 14
            p.setPen(QPen(mcs_color(m), 3))
            p.drawLine(QPointF(lx, y - 4), QPointF(lx + 12, y - 4))
            p.setPen(QColor("#222"))
            p.drawText(QPointF(lx + 16, y), str(m))
        y = ly + 22 + min(len(mcs_list), 14) * 14 + 10
        p.setPen(QPen(QColor("#222"), 1.5))
        _marker(p, QPointF(lx + 6, y - 4), 3, r=4)
        p.drawText(QPointF(lx + 16, y), "now")
        p.end()
