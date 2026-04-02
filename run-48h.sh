#!/bin/bash
# DEVFUZZ 48-hour USB driver fuzzing experiments
# Features:
#   - Versioned AFL data (backed up before overwrite)
#   - Resume support: sudo bash run-48h.sh resume
#   - All entry points exercised (probe, disconnect, suspend, resume, open, close, irq)
#   - gcov coverage dumps every ~2 minutes via 9p share
#   - 10-minute watchdog timeout
#
# Usage:
#   sudo bash run-48h.sh           # fresh start (backs up old data)
#   sudo bash run-48h.sh resume    # resume from previous AFL queue

set -e
ROOT=$(dirname $(realpath $0))
cd $ROOT

echo -1 > /proc/sys/kernel/perf_event_paranoid
echo core > /proc/sys/kernel/core_pattern

MODE=${1:-fresh}  # fresh or resume
DURATION=$((48 * 3600))  # 48 hours

AFL=$ROOT/AFL/afl-fuzz
PROXY=$ROOT/afl-proxy/proxy/build/ap
QEMU=$ROOT/build-qemu-exp/x86_64-softmmu/qemu-system-x86_64
KERNEL=$ROOT/images/bzImage-master
IMAGE=$ROOT/images/stretch.img
SEED=$ROOT/tools/seed

# Experiment definitions: name:driver:shmid:core
EXPERIMENTS=(
  "ims_pcu-probe:ims_pcu:0:0"
  "pegasus-probe:pegasus_notetaker:10:4"
)

echo "=== DEVFUZZ 48-hour USB Fuzzing (mode=$MODE) ==="
echo "Duration: ${DURATION}s (48 hours)"
echo "Start: $(date)"
echo "Drivers: ims_pcu (probe), pegasus_notetaker (probe)"
echo "Entry points: probe, disconnect, suspend, resume, open, close, irq"
echo ""

# Kill any stale processes
echo "Stopping existing experiments..."
pkill -9 -f "afl-fuzz.*afl-proxy" 2>/dev/null || true
pkill -9 -f "qemu-system.*usb-sfp" 2>/dev/null || true
sleep 2

launch_experiment() {
  local EXP_DEF=$1
  IFS=: read exp dev shmid core <<< "$EXP_DEF"

  local RUN_DIR="$ROOT/run-$exp"
  local SHARE_DIR="$ROOT/share-$exp"
  local AFL_INPUT_FLAG="-i $SEED"
  local VERSION_FILE="$SHARE_DIR/version.txt"

  mkdir -p $SHARE_DIR/gcov
  chmod 777 $SHARE_DIR

  if [ "$MODE" = "resume" ] && [ -d "$RUN_DIR/out/queue" ]; then
    # === RESUME MODE ===
    AFL_INPUT_FLAG="-i-"
    local PREV_EXECS=$(cat $RUN_DIR/out/fuzzer_stats 2>/dev/null | grep execs_done | awk '{print $NF}')
    local PREV_PATHS=$(cat $RUN_DIR/out/fuzzer_stats 2>/dev/null | grep paths_total | awk '{print $NF}')
    local VER=$(tail -1 $VERSION_FILE 2>/dev/null | cut -d: -f1 || echo 0)
    VER=$((VER + 1))
    echo "${VER}:resume:$(date +%Y%m%d_%H%M%S):execs=${PREV_EXECS}:paths=${PREV_PATHS}" >> $VERSION_FILE

    # Backup fuzzer_stats
    cp $RUN_DIR/out/fuzzer_stats $SHARE_DIR/fuzzer_stats_v${VER}_resume 2>/dev/null || true

    echo "  $exp: RESUME v$VER (prev: $PREV_EXECS execs, $PREV_PATHS paths)"
  else
    # === FRESH START ===
    if [ -d "$RUN_DIR/out/queue" ]; then
      # Backup old AFL data
      local TS=$(date +%Y%m%d_%H%M%S)
      local BACKUP="$SHARE_DIR/afl_backup_${TS}"
      mkdir -p $BACKUP
      cp $RUN_DIR/out/fuzzer_stats $BACKUP/ 2>/dev/null || true
      cp -r $RUN_DIR/out/queue $BACKUP/ 2>/dev/null || true
      cp -r $RUN_DIR/out/crashes $BACKUP/ 2>/dev/null || true
      echo "  $exp: backed up old AFL data -> $BACKUP"
    fi

    rm -rf $RUN_DIR
    mkdir -p $RUN_DIR
    chmod 777 $RUN_DIR

    local VER=$(tail -1 $VERSION_FILE 2>/dev/null | cut -d: -f1 || echo 0)
    VER=$((VER + 1))
    echo "${VER}:fresh:$(date +%Y%m%d_%H%M%S)" >> $VERSION_FILE

    echo "  $exp: FRESH v$VER"
  fi

  # Launch AFL
  cd $RUN_DIR
  echo > afl.log
  AFL_SKIP_CPUFREQ=1 AFL_NO_AFFINITY=1 \
    $AFL -t 500000000+ -m 256 \
    $AFL_INPUT_FLAG -o out -d -f seed \
    $PROXY @@ $core $shmid > /dev/null 2>&1 &
  local AFL_PID=$!
  sleep 3
  cd $ROOT

  # Launch QEMU with 9p share for gcov
  SFP_SHMID=$shmid AP_DISABLED=0 TEST_PROBE=1 USE_DMA=0 USE_IRQ=0 \
    USE_STAGE2=1 USE_MODEL_PROB=75 \
    SFP_DEV_MODEL=$dev AFL_EPOCH=5 WAITGDB=0 EXPORT_DEVMEM=0 \
    MODEL_PROBE_FUZZ=1 MODEL_RESET_TIME=1 MODEL_MUTATE_PROB=50 AP_DUMP_RW=0 \
    taskset -c $core timeout $DURATION $QEMU \
    -machine q35,accel=kvm -m 2G -smp 1 \
    -kernel $KERNEL \
    -append "nokaslr nosoftlockup console=ttyS0 root=/dev/vda earlyprintk=serial biosdevname=0 net.ifnames=0 loglevel=8 security=none ro rootfstype=ext4 mitigations=off cryptomgr.notests clocksource=tsc audit=0 parport=0 kmemleak=on nosmp usb_driver=$dev" \
    -drive file=$IMAGE,if=virtio,format=raw -snapshot \
    -net none -usb -device usb-sfp -nographic \
    -fsdev local,id=test_dev,path=$SHARE_DIR,security_model=none \
    -device virtio-9p-pci,fsdev=test_dev,mount_tag=test_mount \
    -pidfile $RUN_DIR/qemu.pid -serial file:$RUN_DIR/vm.log \
    > /dev/null 2>&1 &
  local QEMU_PID=$!

  # Save PIDs
  echo $AFL_PID > $RUN_DIR/afl.pid
  echo $QEMU_PID > $RUN_DIR/qemu_outer.pid

  echo "  $exp: AFL=$AFL_PID QEMU=$QEMU_PID dev=$dev core=$core shmid=$shmid"
}

# Launch experiments
for exp_def in "${EXPERIMENTS[@]}"; do
  launch_experiment "$exp_def"
done

echo ""
echo "=== Verifying (30s)... ==="
sleep 30

for exp_def in "${EXPERIMENTS[@]}"; do
  IFS=: read exp dev shmid core <<< "$exp_def"
  echo "--- $exp ---"
  cat run-$exp/out/fuzzer_stats 2>/dev/null | grep -E "execs_done|bitmap_cvg|paths_total" || echo "  (starting...)"
  QPID=$(cat run-$exp/qemu_outer.pid 2>/dev/null)
  ps -p $QPID > /dev/null 2>&1 && echo "  QEMU: alive" || echo "  QEMU: DEAD"
done

echo ""
echo "=== Commands ==="
echo "  Status:  sudo bash check-status.sh"
echo "  Plot:    sudo python3 analyze-coverage.py"
echo "  Resume:  sudo bash run-48h.sh resume"
echo "  Stop:    sudo pkill -9 -f 'afl-fuzz|qemu-system'"
echo ""
echo "  Version history: cat share-*/version.txt"
echo "  AFL backups:     ls share-*/afl_backup_*/"
