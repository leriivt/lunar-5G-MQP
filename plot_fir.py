#!/usr/bin/env python3
"""Visualize BICTR FIR dump CSV files.

CSV columns: tap_index, tap_delay_samples, tap_delay_s, real, imag, magnitude

Usage:
    python3 plot_bictr_fir.py bictr_fir.csv
    python3 plot_bictr_fir.py bictr_fir.csv.0 bictr_fir.csv.1     # compare channels
    python3 plot_bictr_fir.py bictr_fir.csv --save fir.png --no-show

Requires: numpy, matplotlib
"""
import argparse
import csv
import sys

import numpy as np
import matplotlib.pyplot as plt


def load_fir(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{path}: no data rows (only a header?)")
    d = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
    d["h"] = d["real"] + 1j * d["imag"]
    return d


def infer_fs_hz(d, default_hz):
    """Sample rate from tap delays: tap_delay_s = tap_delay_samples / fs."""
    ds, dt = d["tap_delay_samples"], d["tap_delay_s"]
    if len(ds) > 1 and dt[1] > 0:
        return ds[1] / dt[1]
    return default_hz


def summarize(name, d):
    h = d["h"]
    print(f"--- {name} ---")
    print(f"  taps           : {len(h)}")
    print(f"  sum |h|        : {np.sum(np.abs(h)):.6f}")
    print(f"  energy sum|h|^2: {np.sum(np.abs(h) ** 2):.6f}")
    for i, v in enumerate(h[:10]):
        print(f"  tap {int(d['tap_index'][i]):3d}: |h|={abs(v):.6f}  "
              f"phase={np.degrees(np.angle(v)):8.3f} deg  "
              f"({v.real:+.6f}{v.imag:+.6f}j)")
    if len(h) > 10:
        print(f"  ... ({len(h) - 10} more taps)")


def plot_all(files, save=None, show=True, fs_hz=None):
    data = {p: load_fir(p) for p in files}
    for p, d in data.items():
        summarize(p, d)

    fig, axs = plt.subplots(2, 2, figsize=(12, 8))
    ax_mag, ax_phase, ax_iq, ax_fr = axs.ravel()
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    n_files = len(data)

    for i, (p, d) in enumerate(data.items()):
        c = colors[i % len(colors)]
        h = d["h"]
        x = d["tap_delay_samples"]
        label = p.split("/")[-1]
        # small horizontal offset so stems from different files don't overlap
        off = (i - (n_files - 1) / 2) * 0.1 if n_files > 1 else 0.0

        # 1) magnitude vs delay
        ml, sl, bl = ax_mag.stem(x + off, np.abs(h), linefmt=c, markerfmt="o", basefmt=" ")
        plt.setp(ml, color=c)
        plt.setp(sl, color=c)
        ml.set_label(label)

        # skip empty taps: their phase (angle of 0) is meaningless
        nz = np.abs(h) > 1e-9

        # 2) phase vs delay (non-zero taps only)
        ax_phase.plot((x + off)[nz], np.degrees(np.angle(h[nz])), "o", color=c, label=label)

        # 3) complex plane (non-zero taps only)
        ax_iq.plot(h[nz].real, h[nz].imag, "o", color=c, label=label)
        for xi, v in zip(x[nz], h[nz]):
            if nz.sum() <= 20:
                ax_iq.annotate(f"{int(xi)}", (v.real, v.imag),
                               textcoords="offset points", xytext=(4, 4), fontsize=8)

        # 4) frequency response (|H(f)|), padded FFT, only meaningful for >1 tap
        nfft = max(1024, 1 << int(np.ceil(np.log2(len(h) * 8))))
        H = np.fft.fftshift(np.fft.fft(h, nfft))
        fs_use = fs_hz if fs_hz else infer_fs_hz(d, 61.44e6)
        f_mhz = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / fs_use)) / 1e6
        ax_fr.plot(f_mhz, 20 * np.log10(np.abs(H) + 1e-12), color=c, label=label)

    ax_mag.set_title("Tap magnitude vs delay")
    ax_mag.set_xlabel("delay (samples)")
    ax_mag.set_ylabel("|h|")
    ax_mag.set_ylim(bottom=0)
    ax_mag.grid(True, alpha=0.3)

    ax_phase.set_title("Tap phase vs delay (non-zero taps)")
    ax_phase.set_xlabel("delay (samples)")
    ax_phase.set_ylabel("phase (deg)")
    ax_phase.set_ylim(-190, 190)
    ax_phase.grid(True, alpha=0.3)

    ax_iq.set_title("Taps in the complex plane")
    ax_iq.set_xlabel("real")
    ax_iq.set_ylabel("imag")
    ax_iq.axhline(0, color="gray", lw=0.5)
    ax_iq.axvline(0, color="gray", lw=0.5)
    ax_iq.add_patch(plt.Circle((0, 0), 1.0, fill=False, ls="--", color="gray", lw=0.8))
    ax_iq.set_aspect("equal", adjustable="datalim")
    ax_iq.grid(True, alpha=0.3)

    ax_fr.set_title("Frequency response |H(f)|")
    ax_fr.set_xlabel("frequency offset from carrier (MHz)")
    ax_fr.set_ylabel("dB")
    ax_fr.grid(True, alpha=0.3)

    if n_files > 1:
        for ax in (ax_mag, ax_phase, ax_iq, ax_fr):
            ax.legend(fontsize=8)

    if any(len(d["h"]) == 1 for d in data.values()):
        fig.text(0.5, 0.005,
                 "Note: 1-tap FIR (flat channel, e.g. BICTR_RFSIM_FOLD_MULTIPATH=1): "
                 "only the phase carries information.",
                 ha="center", fontsize=9, style="italic")

    fig.suptitle("BICTR FIR", fontsize=14)
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))

    if save:
        fig.savefig(save, dpi=150)
        print(f"saved {save}")
    if show:
        plt.show()


def main():
    ap = argparse.ArgumentParser(description="Plot BICTR FIR dump CSV(s)")
    ap.add_argument("csv_files", nargs="+", help="one or more FIR CSV files")
    ap.add_argument("--save", help="save figure to this path (e.g. fir.png)")
    ap.add_argument("--no-show", action="store_true", help="don't open a window")
    ap.add_argument("--fs-mhz", type=float, default=None,
                    help="sample rate in MHz (default: inferred from CSV, else 61.44)")
    args = ap.parse_args()
    fs_hz = args.fs_mhz * 1e6 if args.fs_mhz else None
    plot_all(args.csv_files, save=args.save, show=not args.no_show, fs_hz=fs_hz)


if __name__ == "__main__":
    main()