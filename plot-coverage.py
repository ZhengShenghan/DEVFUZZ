#!/usr/bin/env python3
"""
Plot DEVFUZZ coverage over time from timestamped gcov dumps.

The guest VM dumps ims-pcu_<seconds>s.gcda files to the 9p share.
This script reads those dumps, runs gcov on each, and plots the trend.

Usage:
  sudo python3 plot-coverage.py                    # plot all experiments
  sudo python3 plot-coverage.py --exp ims_pcu-probe  # plot one experiment
  sudo python3 plot-coverage.py --output fig.png   # custom output file
"""

import os, re, subprocess, argparse, glob
from pathlib import Path

ROOT = Path("/home/ubuntu/DEVFUZZ")
LINUX = ROOT / "linux"
DRIVER = "drivers/input/misc/ims-pcu"
PLOT_FILE = ROOT / "coverage-plot.png"

def get_gcov_pct(gcda_path):
    """Run gcov on a .gcda file, return line coverage %."""
    import shutil
    dst = LINUX / f"{DRIVER}.gcda"
    shutil.copy2(gcda_path, dst)
    try:
        r = subprocess.run(["gcov", f"{DRIVER}.c"],
                           cwd=LINUX, capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            m = re.search(r"Lines executed:([\d.]+)% of (\d+)", line)
            if m and "ims-pcu.c" in line:
                return float(m.group(1)), int(m.group(2))
            # fallback: first "Lines executed" line
            if m:
                return float(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None

def parse_fuzzer_stats(path):
    """Parse AFL fuzzer_stats file."""
    stats = {}
    try:
        with open(path) as f:
            for line in f:
                if ':' in line:
                    k, v = line.split(':', 1)
                    v = v.strip().rstrip('%')
                    try:
                        stats[k.strip()] = float(v) if '.' in v else int(v)
                    except ValueError:
                        stats[k.strip()] = v
    except FileNotFoundError:
        pass
    return stats

def scan_gcov_dumps(share_dir):
    """Scan timestamped gcda dumps and compute coverage for each."""
    pattern = os.path.join(share_dir, "ims-pcu_*s.gcda")
    files = sorted(glob.glob(pattern))
    results = []
    for f in files:
        m = re.search(r"ims-pcu_(\d+)s\.gcda", f)
        if m:
            elapsed_s = int(m.group(1))
            pct, lines = get_gcov_pct(f)
            if pct is not None:
                results.append((elapsed_s, pct, lines))
    return results

def plot(experiments, output=None):
    """Generate coverage plots."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("DEVFUZZ IMS-PCU Driver Fuzzing Coverage", fontsize=14)

    has_gcov = False
    has_afl = False

    for name, share_dir, stats_path in experiments:
        # --- gcov line coverage over time ---
        gcov_data = scan_gcov_dumps(share_dir)
        if gcov_data:
            times_min = [t / 60 for t, _, _ in gcov_data]
            coverages = [c for _, c, _ in gcov_data]
            axes[0].plot(times_min, coverages, label=f"{name} (gcov)",
                        marker='.', markersize=3, linewidth=1.5)
            has_gcov = True
            print(f"{name}: {len(gcov_data)} gcov dumps, "
                  f"latest={coverages[-1]:.1f}% at {times_min[-1]:.0f}min")

        # --- AFL stats (current snapshot) ---
        stats = parse_fuzzer_stats(stats_path)
        if stats and stats.get("execs_done", 0) > 0:
            has_afl = True

    # gcov plot
    ax = axes[0]
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("Line Coverage (%)")
    ax.set_title("gcov Line Coverage (ims-pcu.c)")
    ax.set_ylim(0, max(50, max([c for _, c, _ in gcov_data], default=0) + 10) if gcov_data else 50)
    if has_gcov:
        ax.legend(fontsize=9)
    else:
        ax.text(0.5, 0.5, "No gcov dumps found.\nGuest dumps to share-*/gcov/ims-pcu_*s.gcda",
                transform=ax.transAxes, ha='center', va='center', fontsize=10, color='gray')
    ax.grid(True, alpha=0.3)

    # AFL summary table
    ax = axes[1]
    ax.axis('off')
    ax.set_title("AFL Fuzzer Summary (current)")
    rows = []
    for name, share_dir, stats_path in experiments:
        stats = parse_fuzzer_stats(stats_path)
        if stats:
            rows.append([
                name,
                f"{stats.get('execs_done', 0):,}",
                f"{stats.get('paths_total', 0):,}",
                f"{stats.get('paths_found', 0):,}",
                f"{stats.get('bitmap_cvg', 0)}%",
                f"{stats.get('unique_crashes', 0)}",
            ])
    if rows:
        table = ax.table(
            cellText=rows,
            colLabels=["Experiment", "Execs", "Paths", "Found", "Bitmap%", "Crashes"],
            loc='center', cellLoc='center'
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 1.8)
    else:
        ax.text(0.5, 0.5, "No AFL stats available", transform=ax.transAxes,
                ha='center', va='center', fontsize=12, color='gray')

    plt.tight_layout()
    out = output or str(PLOT_FILE)
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"Plot saved to {out}")
    plt.close()

def main():
    parser = argparse.ArgumentParser(description="Plot DEVFUZZ coverage from gcov dumps")
    parser.add_argument("--output", type=str, default=None, help="Output plot file")
    parser.add_argument("--exp", type=str, default=None,
                       help="Specific experiment (e.g., ims_pcu-probe)")
    args = parser.parse_args()

    # Auto-discover experiments with gcov share dirs
    experiments = []
    for name in ["ims_pcu-probe", "ims_pcu-postprobe"]:
        share = ROOT / f"share-{name}" / "gcov"
        stats = ROOT / f"run-{name}" / "out" / "fuzzer_stats"
        if args.exp and args.exp != name:
            continue
        if share.exists() or stats.exists():
            experiments.append((name, str(share), str(stats)))

    if not experiments:
        print("No experiments found. Looking for share-*/gcov/ directories.")
        return

    plot(experiments, args.output)

if __name__ == "__main__":
    main()
