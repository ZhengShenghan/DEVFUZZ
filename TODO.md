# DEVFUZZ USB Fuzzing - TODO

## Current Experiments (48h each)

### ims_pcu probe (all entry points)
- [x] probe, disconnect (modprobe/rmmod)
- [x] irq (USB interrupt handler via data transfers)
- [ ] suspend, resume (USB autosuspend - not working in KVM guest)
- [x] open, close (input device /dev/input/eventX - only works if probe succeeds)
- gcov result: 31.2% line / 45.0% branch (depths 0-3)

### pegasus_notetaker probe (all entry points)
- [x] probe, disconnect, irq, open, close
- [x] suspend, resume (100% covered in new run!)
- gcov result: 72.2% line / 84.1% branch (depths 0-1)

## USB Model Extraction (IMPLEMENTED)

### Done
- [x] Extended LLVM stage2 pass for USB buffer analysis (`apstage2.cpp`)
  - Detects USB completion handlers by URB parameter signature
  - Follows callee functions up to 3 levels deep
  - Extracts `icmp` and `switch` constraints on buffer reads
  - Generates `unordered_map<int, HWInput> usb_mdl` code
- [x] Created `tools/generate_usb_model.py` - runs pass and generates model
- [x] Tested on ims_pcu: found 11 constraints (URB status, response codes, buffer checks)
- [x] Tested on pegasus: found 4 constraints (packet fields at offsets 1,2,4)

### Done (runtime integration)
- [x] Added `setUSBModel()` + `feedFuzzUSBData()` to `Stage2HWModel` in `HWModel.h`
- [x] Wired into `aplib.cpp` - USB model feeds protocol-aware data when `USE_STAGE2=1`
- [x] Generated and integrated models for pegasus + ims_pcu
- [x] Experiments running with `USE_STAGE2=1 USE_MODEL_PROB=75`

### Remaining
- [ ] Handle loop-based protocol parsers (e.g., ims_pcu's STX/ETX state machine)
  - Current limitation: LLVM pass only finds constant-offset buffer accesses
  - Loop variables (like `urb_in_buf[i]` with variable `i`) are not analyzed
  - Need: symbolic loop analysis or manual protocol annotation

### Usage
```bash
# Run USB model extraction on a driver
python3 tools/generate_usb_model.py \
  -b analysis/linux/drivers/input/misc/ims-pcu.o.bc \
  -n ims_pcu -v

# Run on pegasus
python3 tools/generate_usb_model.py \
  -b analysis/linux/drivers/input/tablet/pegasus_notetaker.o.bc \
  -n pegasus_notetaker -v
```

## Commands
```bash
sudo bash run-48h.sh           # Launch fresh 48h run
sudo bash run-48h.sh resume    # Resume after kill
sudo bash check-status.sh      # Quick status
sudo python3 analyze-coverage.py              # Coverage plot (latest run)
sudo python3 analyze-coverage.py --run all    # All runs
sudo python3 analyze-coverage.py --list       # List available runs
```
