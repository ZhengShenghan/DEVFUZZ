#!/bin/bash
# Quick status check for running experiments
echo "=== DEVFUZZ Experiment Status $(date) ==="
echo ""
for d in run-ims_pcu-probe run-ims_pcu-postprobe run-pegasus-probe run-pegasus-postprobe; do
  echo "--- $d ---"
  if [ -f /home/ubuntu/DEVFUZZ/$d/qemu.pid ]; then
    PID=$(cat /home/ubuntu/DEVFUZZ/$d/qemu.pid 2>/dev/null)
    ps -p $PID > /dev/null 2>&1 && echo "QEMU: alive" || echo "QEMU: DEAD"
  fi
  sudo cat /home/ubuntu/DEVFUZZ/$d/out/fuzzer_stats 2>/dev/null | grep -E "bitmap_cvg|paths_total|execs_done|unique_crashes|paths_found|cycles_done|execs_per_sec" || echo "  (no stats)"
  echo ""
done
echo "Processes: $(ps aux | grep -E 'qemu-system|afl-fuzz' | grep -v grep | wc -l) total"
