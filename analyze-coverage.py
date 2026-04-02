#!/usr/bin/env python3
"""
DEVFUZZ driver coverage analysis with branch-depth tracking.

Depth = nesting level of control-flow blocks (if/switch/for/while).
  depth 0: top-level function body
  depth 1: inside first if/switch/for
  depth 2: nested if inside if
  etc.

Usage:
  sudo python3 analyze-coverage.py                # full analysis + plot
  sudo python3 analyze-coverage.py --text          # text-only
"""

import os, re, subprocess, glob, shutil, argparse
from pathlib import Path
from collections import defaultdict

ROOT = Path("/home/ubuntu/DEVFUZZ")
LINUX = ROOT / "linux"

# Driver configs: name -> (source path, object path, gcda filename in share)
DRIVERS = {
    "ims_pcu": {
        "src": "drivers/input/misc/ims-pcu.c",
        "obj": "drivers/input/misc/ims-pcu",
        "gcda_name": "ims-pcu",
    },
    "pegasus_notetaker": {
        "src": "drivers/input/tablet/pegasus_notetaker.c",
        "obj": "drivers/input/tablet/pegasus_notetaker",
        "gcda_name": "pegasus_notetaker",
    },
}

def detect_driver(share_dir):
    """Detect which driver based on gcda files in share dir."""
    for dname, dcfg in DRIVERS.items():
        if glob.glob(os.path.join(share_dir, f"{dcfg['gcda_name']}*.gcda")):
            return dname
    return None

def run_gcov_b(gcda_path, driver_name="ims_pcu"):
    """Run gcov -b, return the .gcov file path."""
    dcfg = DRIVERS[driver_name]
    dst = LINUX / f"{dcfg['obj']}.gcda"
    shutil.copy2(gcda_path, dst)
    subprocess.run(["gcov", "-b", dcfg["src"]],
                   cwd=LINUX, capture_output=True, timeout=10)
    src_basename = os.path.basename(dcfg["src"])
    gcov_file = LINUX / f"{src_basename}.gcov"
    return gcov_file if gcov_file.exists() else None

def parse_gcov_with_depth(gcov_path, src_path):
    """Parse .gcov and source to compute branch coverage at each nesting depth."""
    # First, compute nesting depth for each line from the source
    line_depth = {}
    depth = 0
    with open(src_path) as f:
        for lineno, line in enumerate(f, 1):
            stripped = line.strip()
            # Track brace nesting (simplified - doesn't handle strings/comments perfectly)
            for ch in stripped:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth = max(0, depth - 1)
            line_depth[lineno] = depth

    # Parse .gcov for branch info
    # Format:
    #   <count>: <lineno>: <source>
    #   branch  N taken X% (fallthrough)
    #   branch  N taken X%
    branches_by_depth = defaultdict(lambda: {"total": 0, "taken": 0, "executed": 0})
    lines_by_depth = defaultdict(lambda: {"total": 0, "covered": 0})
    current_lineno = 0

    with open(gcov_path) as f:
        for line in f:
            # Line with execution count
            m = re.match(r'\s*(\d+|#####|-)\s*:\s*(\d+):', line)
            if m:
                count_str, lineno_str = m.group(1), m.group(2)
                lineno = int(lineno_str)
                current_lineno = lineno
                d = line_depth.get(lineno, 0)
                # Adjust: function body starts at depth 1 in brace counting,
                # but we want depth 0 for top-level function statements
                d = max(0, d - 1)

                if count_str not in ('-', '0'):
                    if count_str == '#####':
                        lines_by_depth[d]["total"] += 1
                    else:
                        lines_by_depth[d]["total"] += 1
                        lines_by_depth[d]["covered"] += 1

            # Branch annotation
            m = re.match(r'branch\s+\d+\s+(taken\s+(\d+)%|never executed)', line)
            if m:
                d = line_depth.get(current_lineno, 0)
                d = max(0, d - 1)
                branches_by_depth[d]["total"] += 1
                if m.group(1).startswith("taken"):
                    pct = int(m.group(2))
                    branches_by_depth[d]["executed"] += 1
                    if pct > 0:
                        branches_by_depth[d]["taken"] += 1

    return branches_by_depth, lines_by_depth

def get_overall_stats(gcda_path, driver_name="ims_pcu"):
    """Get overall line/branch coverage."""
    dcfg = DRIVERS[driver_name]
    dst = LINUX / f"{dcfg['obj']}.gcda"
    shutil.copy2(gcda_path, dst)
    r = subprocess.run(["gcov", "-b", "-f", dcfg["src"]],
                       cwd=LINUX, capture_output=True, text=True, timeout=10)
    src_basename = os.path.basename(dcfg["src"])

    result = {"line_pct": 0, "line_total": 0,
              "branch_pct": 0, "branch_total": 0, "branch_taken_pct": 0,
              "functions": {}}

    lines = r.stdout.splitlines()
    current_func = None
    for i, line in enumerate(lines):
        m = re.match(r"Function '(\w+)'", line)
        if m:
            current_func = m.group(1)
        m = re.search(r"Lines executed:([\d.]+)% of (\d+)", line)
        if m and current_func:
            result["functions"][current_func] = {
                "line_pct": float(m.group(1)), "line_total": int(m.group(2))
            }
            current_func = None

        if src_basename in line and "File" in line:
            for j in range(i+1, min(i+4, len(lines))):
                m2 = re.search(r"Lines executed:([\d.]+)% of (\d+)", lines[j])
                if m2:
                    result["line_pct"] = float(m2.group(1))
                    result["line_total"] = int(m2.group(2))
                m3 = re.search(r"Branches executed:([\d.]+)% of (\d+)", lines[j])
                if m3:
                    result["branch_pct"] = float(m3.group(1))
                    result["branch_total"] = int(m3.group(2))
                m4 = re.search(r"Taken at least once:([\d.]+)% of (\d+)", lines[j])
                if m4:
                    result["branch_taken_pct"] = float(m4.group(1))
    return result

def load_trend_cache(cache_path):
    """Load cached trend data."""
    import json
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
    return {}

def save_trend_cache(cache_path, cache):
    """Save trend cache."""
    import json
    with open(cache_path, 'w') as f:
        json.dump(cache, f)

def list_runs(share_dir):
    """List available runs in a share directory."""
    runs = []
    gcov_dir = os.path.join(share_dir, "gcov")
    if not os.path.isdir(gcov_dir):
        return runs
    for entry in sorted(os.listdir(gcov_dir)):
        full = os.path.join(gcov_dir, entry)
        if os.path.isdir(full) and entry.startswith("run_"):
            count = len(glob.glob(os.path.join(full, "*_*s.gcda")))
            if count > 0:
                runs.append((entry, full, count))
    # Also check root gcov dir for dumps not in a run subdir
    root_count = len(glob.glob(os.path.join(gcov_dir, "*_*s.gcda")))
    if root_count > 0:
        runs.append(("current", gcov_dir, root_count))
    return runs

def main():
    parser = argparse.ArgumentParser(description="""
DEVFUZZ coverage analysis. Plots coverage over time, branch depth, line depth.

Examples:
  sudo python3 analyze-coverage.py                          # latest run
  sudo python3 analyze-coverage.py --run run_01_old         # specific old run
  sudo python3 analyze-coverage.py --list                   # list available runs
  sudo python3 analyze-coverage.py --run all                # overlay all runs
""", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "coverage-analysis.png"))
    parser.add_argument("--max-trend", type=int, default=200,
                       help="Max trend points to process (evenly sampled)")
    parser.add_argument("--run", type=str, default=None,
                       help="Run to analyze: 'run_01_old', 'run_02_current', 'current', 'all', or 'latest' (default)")
    parser.add_argument("--list", action="store_true", help="List available runs")
    args = parser.parse_args()

    # List runs if requested
    if args.list:
        for exp_name in ["ims_pcu-probe", "pegasus-probe"]:
            share = str(ROOT / f"share-{exp_name}")
            runs = list_runs(share)
            print(f"\n{exp_name}:")
            for rname, rpath, count in runs:
                print(f"  {rname:20s}  {count:5d} gcov dumps  ({rpath})")
        return

    # Auto-discover experiments
    experiments = []
    for exp_name in ["ims_pcu-probe", "pegasus-probe"]:
        share = ROOT / f"share-{exp_name}" / "gcov"
        if share.exists():
            driver = detect_driver(str(share))
            if not driver:
                # Check subdirs
                for entry in os.listdir(str(share)):
                    subdir = share / entry
                    if subdir.is_dir() and entry.startswith("run_"):
                        driver = detect_driver(str(subdir))
                        if driver:
                            break
            if driver:
                experiments.append((exp_name, str(share), driver))

    if not experiments:
        print("No gcov data found. Looking for share-*/gcov/ directories.")
        return

    all_data = {}
    for name, share_dir, driver_name in experiments:
        dcfg = DRIVERS[driver_name]
        src_path = LINUX / dcfg["src"]
        gcda_name = dcfg["gcda_name"]

        def _sort_key(f):
            m = re.search(r'_(\d+)s\.gcda', f)
            return int(m.group(1)) if m else 0

        def process_one_run(label, gcda_dir):
            """Process one run directory, add to all_data."""
            dumps = sorted(glob.glob(os.path.join(gcda_dir, f"{gcda_name}_*s.gcda")),
                           key=_sort_key)
            latest_f = os.path.join(gcda_dir, f"{gcda_name}.gcda")
            gcda = dumps[-1] if dumps else latest_f
            if not os.path.exists(gcda):
                return

            gcov_file = run_gcov_b(gcda, driver_name)
            if not gcov_file:
                return

            overall = get_overall_stats(gcda, driver_name)
            branches_by_depth, lines_by_depth = parse_gcov_with_depth(gcov_file, src_path)

            cache_path = os.path.join(gcda_dir, "trend_cache.json")
            cache = load_trend_cache(cache_path)

            # Sample evenly if too many dumps
            if len(dumps) > args.max_trend:
                step = len(dumps) / args.max_trend
                sampled = [dumps[int(i * step)] for i in range(args.max_trend)]
                if dumps[0] not in sampled:
                    sampled.insert(0, dumps[0])
                if dumps[-1] not in sampled:
                    sampled.append(dumps[-1])
                dumps_to_process = sampled
            else:
                dumps_to_process = dumps

            trend = []
            new_cache = 0
            for f in dumps_to_process:
                m = re.search(rf"{re.escape(gcda_name)}_(\d+)s\.gcda", f)
                if m:
                    elapsed = int(m.group(1))
                    ck = str(elapsed)
                    if ck in cache:
                        stats = cache[ck]
                    else:
                        stats = get_overall_stats(f, driver_name)
                        cache[ck] = stats
                        new_cache += 1
                    trend.append((elapsed, stats))

            if new_cache > 0:
                save_trend_cache(cache_path, cache)
                print(f"  {label}: cached {new_cache} new points ({len(cache)} total)")

            print(f"  {label}: {len(dumps)} dumps, {len(trend)} trend points")

            all_data[label] = {
                "overall": overall,
                "branches_by_depth": dict(branches_by_depth),
                "lines_by_depth": dict(lines_by_depth),
                "trend": trend,
            }

        # Determine which run(s) to process
        run_selection = args.run or "latest"
        available_runs = list_runs(os.path.dirname(share_dir))

        if run_selection == "all":
            for rname, rpath, _ in available_runs:
                process_one_run(f"{name} ({rname})", rpath)
        elif run_selection == "latest":
            # Prefer root gcov dir (current), fall back to newest run_* subdir
            root_dumps = glob.glob(os.path.join(share_dir, f"{gcda_name}_*s.gcda"))
            if root_dumps:
                process_one_run(name, share_dir)
            elif available_runs:
                rname, rpath, _ = available_runs[-1]
                process_one_run(name, rpath)
        else:
            target = os.path.join(share_dir, run_selection)
            if os.path.isdir(target):
                process_one_run(name, target)
            else:
                print(f"  {name}: run '{run_selection}' not found. Use --list to see available.")

        # (processing handled by process_one_run above)

    # Print text report
    for name, data in all_data.items():
        ov = data["overall"]
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        print(f"  Line coverage:     {ov['line_pct']:.1f}% of {ov['line_total']} lines")
        print(f"  Branch coverage:   {ov['branch_pct']:.1f}% of {ov['branch_total']} branches")
        print(f"  Branches taken:    {ov['branch_taken_pct']:.1f}%")
        print()

        # Depth analysis
        print("  Branch Coverage by Nesting Depth:")
        print("  (depth 1 = first if/switch, depth 2 = nested if, etc.)")
        print(f"  {'Depth':>6s} | {'Branches':>10s} | {'Executed':>10s} | {'Taken':>10s}")
        print(f"  {'-'*6}-|-{'-'*10}-|-{'-'*10}-|-{'-'*10}")
        bd = data["branches_by_depth"]
        for d in sorted(bd.keys()):
            s = bd[d]
            if s["total"] == 0:
                continue
            exec_pct = 100.0 * s["executed"] / s["total"] if s["total"] else 0
            taken_pct = 100.0 * s["taken"] / s["total"] if s["total"] else 0
            bar_taken = "█" * int(taken_pct / 5) + "░" * (20 - int(taken_pct / 5))
            print(f"  {d:>6d} | {s['taken']:>4d}/{s['total']:<5d} | {exec_pct:>9.1f}% | {taken_pct:>5.1f}% [{bar_taken}]")
        print()

        # Line coverage by depth
        print("  Line Coverage by Nesting Depth:")
        ld = data["lines_by_depth"]
        for d in sorted(ld.keys()):
            s = ld[d]
            if s["total"] == 0:
                continue
            pct = 100.0 * s["covered"] / s["total"] if s["total"] else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"    Depth {d}: {s['covered']:>3d}/{s['total']:<4d} ({pct:>5.1f}%) [{bar}]")
        print()

        # Per-function summary (top covered)
        print("  Top covered functions:")
        funcs = sorted(ov["functions"].items(), key=lambda x: -x[1]["line_pct"])
        for fname, fdata in funcs[:15]:
            if fdata["line_pct"] > 0:
                print(f"    {fname:40s} {fdata['line_pct']:>5.1f}% of {fdata['line_total']} lines")

        # Trend
        if data["trend"]:
            t0 = data["trend"][0][0]
            print(f"\n  Coverage Trend (t0={t0}s from VM boot):")
            print(f"  {'Time':>8s} | {'Lines':>8s} | {'Branches':>10s} | {'Taken':>8s}")
            print(f"  {'-'*8}-|-{'-'*8}-|-{'-'*10}-|-{'-'*8}")
            for elapsed, stats in data["trend"]:
                t_rel = elapsed - t0
                print(f"  {t_rel:>6d}s | {stats['line_pct']:>7.1f}% | {stats['branch_pct']:>9.1f}% | {stats['branch_taken_pct']:>7.1f}%")

    if args.text:
        return

    # Generate plot: one row per driver (3 columns each)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    n_drivers = len(all_data)
    fig, axes = plt.subplots(n_drivers, 3, figsize=(18, 6 * n_drivers),
                             squeeze=False)
    fig.suptitle("DEVFUZZ USB Driver Coverage Analysis", fontsize=16, y=0.98)

    for row, (name, data) in enumerate(all_data.items()):
        driver_label = name.replace("-", " ").replace("_", " ").title()

        # Col 1: Coverage trend over time
        ax = axes[row][0]
        if data["trend"]:
            t0 = data["trend"][0][0]  # normalize to start from 0
            times = [(t - t0) / 60 for t, _ in data["trend"]]
            lines_pct = [s["line_pct"] for _, s in data["trend"]]
            branches_pct = [s["branch_pct"] for _, s in data["trend"]]
            taken_pct = [s["branch_taken_pct"] for _, s in data["trend"]]
            ax.plot(times, lines_pct, label="Line cov", marker='.', markersize=4, color='#2196F3')
            ax.plot(times, branches_pct, label="Branch exec", marker='.', markersize=4,
                    linestyle='--', color='#4CAF50')
            ax.plot(times, taken_pct, label="Branch taken", marker='.', markersize=4,
                    linestyle=':', color='#FF9800')
        ax.set_xlabel("Time (minutes)")
        ax.set_ylabel("Coverage (%)")
        ax.set_title(f"{driver_label} - Coverage Over Time")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 100)

        # Col 2: Branch coverage by nesting depth
        ax = axes[row][1]
        bd = data["branches_by_depth"]
        depths = sorted([d for d in bd.keys() if bd[d]["total"] > 0])
        if depths:
            totals = [bd[d]["total"] for d in depths]
            taken_vals = [bd[d]["taken"] for d in depths]
            exec_not_taken = [bd[d]["executed"] - bd[d]["taken"] for d in depths]
            not_exec = [bd[d]["total"] - bd[d]["executed"] for d in depths]

            labels = [f"Depth {d}" for d in depths]
            ax.barh(labels, taken_vals, color='#4CAF50', label='Taken')
            ax.barh(labels, exec_not_taken, left=taken_vals,
                    color='#FFC107', label='Executed (not taken)')
            ax.barh(labels, not_exec,
                    left=[t+e for t, e in zip(taken_vals, exec_not_taken)],
                    color='#FF5722', alpha=0.5, label='Not executed')
            for i, d in enumerate(depths):
                ax.text(totals[i] + 0.5, i,
                        f"{taken_vals[i]}/{totals[i]}", va='center', fontsize=8)
        ax.set_xlabel("Branches")
        ax.set_title(f"{driver_label} - Branch Depth")
        ax.legend(fontsize=8)

        # Col 3: Line coverage by nesting depth
        ax = axes[row][2]
        ld = data["lines_by_depth"]
        depths = sorted([d for d in ld.keys() if ld[d]["total"] > 0])
        if depths:
            covered_vals = [ld[d]["covered"] for d in depths]
            uncov_vals = [ld[d]["total"] - ld[d]["covered"] for d in depths]
            labels = [f"Depth {d}" for d in depths]

            ax.barh(labels, covered_vals, color='#4CAF50', label='Covered')
            ax.barh(labels, uncov_vals, left=covered_vals,
                    color='#FF5722', alpha=0.5, label='Uncovered')
            for i, d in enumerate(depths):
                total = ld[d]["total"]
                pct = 100.0 * covered_vals[i] / total if total else 0
                ax.text(total + 1, i,
                        f"{covered_vals[i]}/{total} ({pct:.0f}%)", va='center', fontsize=8)
        ax.set_xlabel("Lines")
        ax.set_title(f"{driver_label} - Line Depth")
        ax.legend(fontsize=8)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(args.output, dpi=150, bbox_inches='tight')
    print(f"\nPlot saved to {args.output}")

if __name__ == "__main__":
    main()
