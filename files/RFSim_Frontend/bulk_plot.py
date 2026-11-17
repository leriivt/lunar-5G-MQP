"""Plot a bulk run's results: UL BLER vs measured UL SNR, every point on one graph,
one colour-coded curve per MCS.

Drawn with Qt's QPainter (no matplotlib: the system matplotlib does not load with this
machine's NumPy 2). Written to <bulk folder>/data/bler_vs_snr.png.

    python3 bulk_plot.py <bulk folder>      # re-plot any bulk run from its CSV

x = the run's measured UL SNR (ul_snr_db, already the mean over the run's samples).
Runs that repeat the same plan, MCS and target SINR are merged into one point: mean SNR,
mean BLER. Rows with no BLER or SNR (the UE never synced) are left out. With several site
plans, each plan gets its own marker shape. BLER is on a linear 0..1 axis, ticks every 0.1.
"""
import csv
import math
import os
import sys
from collections import defaultdict

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPolygonF

CSV_NAME = "bler_sinr_by_mcs.csv"
Y_STEP = 0.1                     # BLER axis: 0..1, a tick and grid line every Y_STEP
WIDTH, HEIGHT = 1100, 700
LEGEND_W = 230
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 70, 20, 50, 60


def _num(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def load_curves(csv_path, y_col="ul_bler"):
    """{(plan, mcs): [(mean SNR, mean BLER), ...] sorted by SNR}, one point per target SINR."""
    acc = defaultdict(list)
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            snr, y = _num(row.get("ul_snr_db")), _num(row.get(y_col))
            mcs, target = _num(row.get("mcs")), _num(row.get("target_sinr_db"))
            if None in (snr, y, mcs):
                continue
            acc[(row["plan"], int(mcs), target)].append((snr, y))
    curves = defaultdict(list)
    for (plan, mcs, _target), pts in acc.items():
        curves[(plan, mcs)].append((sum(p[0] for p in pts) / len(pts),
                                    sum(p[1] for p in pts) / len(pts)))
    return {key: sorted(pts) for key, pts in curves.items()}


def mcs_color(mcs):
    """Low MCS = blue/purple, high MCS = red, spread over the 0..28 range."""
    return QColor.fromHsv(int(260 - 260 * min(max(mcs, 0), 28) / 28), 210, 210)


def _nice_step(span):
    raw = span / 8 if span > 0 else 1
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def _marker(p, pt, shape, r=4):
    if shape == 1:
        p.drawRect(QRectF(pt.x() - r, pt.y() - r, 2 * r, 2 * r))
    elif shape == 2:
        p.drawPolygon(QPolygonF([QPointF(pt.x(), pt.y() - r - 1), QPointF(pt.x() - r - 1, pt.y() + r),
                                 QPointF(pt.x() + r + 1, pt.y() + r)]))
    elif shape == 3:
        p.drawPolygon(QPolygonF([QPointF(pt.x(), pt.y() - r - 1), QPointF(pt.x() + r + 1, pt.y()),
                                 QPointF(pt.x(), pt.y() + r + 1), QPointF(pt.x() - r - 1, pt.y())]))
    else:
        p.drawEllipse(pt, r, r)


def _draw_panel(p, rect, curves, x_label, title, shapes):
    """The BLER-vs-SNR graph inside rect (QRectF); curves: {(plan, mcs): [(x, y), ...]}."""
    plot = QRectF(rect.left() + MARGIN_L, rect.top() + MARGIN_T,
                  rect.width() - MARGIN_L - MARGIN_R, rect.height() - MARGIN_T - MARGIN_B)
    xs = [x for pts in curves.values() for x, _ in pts]
    p.setPen(QColor("#222"))
    p.setFont(QFont("Sans", 12, QFont.Weight.DemiBold))
    p.drawText(QRectF(rect.left(), rect.top() + 8, rect.width(), 30),
               Qt.AlignmentFlag.AlignHCenter, title)
    p.setFont(QFont("Sans", 9))
    if not xs:
        p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "no data")
        return
    x0, x1 = min(xs), max(xs)
    if x1 - x0 < 1e-9:
        x0, x1 = x0 - 1, x1 + 1
    step = _nice_step(x1 - x0)
    x0, x1 = math.floor(x0 / step) * step, math.ceil(x1 / step) * step
    def to_px(x, y):
        fy = min(max(y, 0.0), 1.0)
        return QPointF(plot.left() + (x - x0) / (x1 - x0) * plot.width(),
                       plot.bottom() - fy * plot.height())

    # grid + ticks
    grid = QPen(QColor("#dddddd"), 1)
    for i in range(int(round(1 / Y_STEP)) + 1):
        v = i * Y_STEP
        y = to_px(x0, v).y()
        p.setPen(grid)
        p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        p.setPen(QColor("#333"))
        p.drawText(QRectF(plot.left() - 60, y - 9, 54, 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v:.1f}")
    n = int(round((x1 - x0) / step))
    for i in range(n + 1):
        x = x0 + i * step
        px = to_px(x, 1).x()
        p.setPen(grid)
        p.drawLine(QPointF(px, plot.top()), QPointF(px, plot.bottom()))
        p.setPen(QColor("#333"))
        p.drawText(QRectF(px - 30, plot.bottom() + 4, 60, 18), Qt.AlignmentFlag.AlignHCenter, f"{x:g}")
    p.setPen(QPen(QColor("#555"), 1))
    p.drawRect(plot)
    p.drawText(QRectF(plot.left(), plot.bottom() + 26, plot.width(), 20),
               Qt.AlignmentFlag.AlignHCenter, x_label)
    p.save()
    p.translate(rect.left() + 16, plot.center().y())
    p.rotate(-90)
    p.drawText(QRectF(-150, -10, 300, 20), Qt.AlignmentFlag.AlignHCenter,
               "UL BLER (first round)")
    p.restore()

    # curves
    p.setClipRect(plot.adjusted(-6, -6, 6, 6))
    for key in sorted(curves):
        plan, mcs = key
        color = mcs_color(mcs)
        pts = [(to_px(x, y), y) for x, y in curves[key]]
        p.setPen(QPen(color, 2))
        for (a, _), (b, _) in zip(pts, pts[1:]):
            p.drawLine(a, b)
        for pt, y in pts:
            p.setBrush(color)
            _marker(p, pt, shapes[plan])
    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_legend(p, left, top, mcs_list, plans, shapes):
    p.setFont(QFont("Sans", 10, QFont.Weight.DemiBold))
    p.setPen(QColor("#222"))
    p.drawText(QPointF(left, top), "MCS")
    p.setFont(QFont("Sans", 9))
    row_h = min(20, (HEIGHT - top - 40 - 22 * len(plans)) / max(len(mcs_list), 1))
    y = top
    for mcs in mcs_list:
        y += row_h
        p.setPen(QPen(mcs_color(mcs), 3))
        p.drawLine(QPointF(left, y), QPointF(left + 26, y))
        p.setPen(QColor("#222"))
        p.drawText(QPointF(left + 34, y + 4), str(mcs))
    if len(plans) > 1:
        y += 30
        p.setFont(QFont("Sans", 10, QFont.Weight.DemiBold))
        p.drawText(QPointF(left, y), "Site plan")
        p.setFont(QFont("Sans", 8))
        for plan in plans:
            y += 20
            p.setPen(QPen(QColor("#222"), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            _marker(p, QPointF(left + 6, y), shapes[plan])
            p.drawText(QPointF(left + 18, y + 4), plan[:30])


def plot_bulk(root):
    """Write data/bler_vs_snr.png (all plans and MCS on one graph). Returns [png path] or []."""
    csv_path = os.path.join(root, "data", CSV_NAME)
    if not os.path.isfile(csv_path):
        return []
    curves = load_curves(csv_path)
    if not curves:
        return []
    plans = sorted({plan for plan, _ in curves})
    shapes = {plan: i % 4 for i, plan in enumerate(plans)}
    img = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_panel(p, QRectF(0, 10, WIDTH - LEGEND_W, HEIGHT - 10), curves,
                "Measured UL SNR (dB, mean over the run)",
                f"UL BLER vs UL SNR: {os.path.basename(os.path.normpath(root))}", shapes)
    _draw_legend(p, WIDTH - LEGEND_W + 20, 80, sorted({m for _, m in curves}), plans, shapes)
    p.end()
    path = os.path.join(root, "data", "bler_vs_snr.png")
    img.save(path)
    return [path]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python3 bulk_plot.py <bulk run folder>")
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    paths = plot_bulk(sys.argv[1])
    print("\n".join(paths) if paths else "no data to plot")
