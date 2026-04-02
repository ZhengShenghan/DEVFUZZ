# DEVFUZZ USB Driver Fuzzing - Progress

## Session 4: 2026-03-30 - 48h Experiments (All Entry Points)

### Experiment Setup
All entry points are now exercised in a single experiment per driver:
- **probe/disconnect**: modprobe/rmmod cycle
- **irq**: USB interrupt handler via data transfers (fires automatically)
- **suspend/resume**: USB autosuspend via sysfs (`power/control`)
- **open/close**: read from `/dev/input/eventX` (triggers input_dev open/close)

### Versioning & Resume
- AFL data backed up before each fresh start: `share-*/afl_backup_<timestamp>/`
- Resume support: `sudo bash run-48h.sh resume` uses AFL `-i-` flag
- Version history: `share-*/version.txt`
- gcov trend cache preserved across restarts: `share-*/gcov/trend_cache.json`

### Launch Command
```bash
sudo bash run-48h.sh           # fresh start
sudo bash run-48h.sh resume    # resume after kill
```

### Monitoring
```bash
sudo bash check-status.sh              # quick AFL stats
sudo python3 analyze-coverage.py       # full analysis with plot
sudo python3 analyze-coverage.py --text # text report
```

---

## Session 5: 2026-03-30 - USB Model Extraction

### Extended LLVM Stage2 Pass for USB
Added USB buffer analysis to `afl-proxy/stage2/src/apstage2.cpp`:
- **Detection**: Finds USB completion handlers by URB parameter type signature
  and `usb_fill_int_urb`/`usb_fill_bulk_urb` function pointer arguments
- **Analysis**: Follows callees up to 3 levels deep, collecting:
  - `icmp` comparisons against constants (magic values, protocol codes)
  - `switch` statement case values
  - Range constraints from inequality comparisons
- **Output**: Generates `unordered_map<int, HWInput> usb_mdl` C++ code

### Results

**ims_pcu** (11 constraints extracted):
| Offset | Value | Meaning |
|--------|-------|---------|
| 88 | 0, -104, -100, -2 | URB status codes |
| 132 | 0 | actual_length check |
| 208 | 0xe0 | `IMS_PCU_RSP_EVNT_BUTTONS` protocol response |
| 336-339 | 0 | Protocol state machine fields |

**pegasus_notetaker** (4 constraints):
| Offset | Value | Meaning |
|--------|-------|---------|
| 1 | 0xb5 | Packet marker |
| 2 | 0x0 | Position field |
| 4 | 0x0 | Button state |
| 88 | 0, -104, -100, -2 | URB status codes |

### Limitation
The ims_pcu protocol parser uses a loop (`for (i=0; i<len; i++) { switch(buf[i]) }`)
where `i` is a variable. The LLVM pass can only extract constraints at constant GEP offsets,
so it misses the STX (0x02), ETX (0x03), DLE (0x10) protocol framing constants.
These would need symbolic loop analysis or manual annotation.

### Runtime Integration (Session 5 continued)
- Added `setUSBModel()` and `feedFuzzUSBData()` to `Stage2HWModel` in `HWModel.h`
- Wired into `aplib.cpp`: when `USE_STAGE2=1`, the USB model overlays protocol-aware
  values at constrained offsets on top of AFL's fuzz data
- Generated and integrated models for both drivers:
  - `HWModel_pegasus_notetaker.h`: constraints at buf[1]=0xb5, buf[2]=0, buf[4]=0
  - `HWModel_ims_pcu.h`: constraints at buf[208]=0xe0 (response code), URB status codes
- Updated `run-48h.sh` to use `USE_STAGE2=1 USE_MODEL_PROB=75`
- Fixed `Stage2HWModel::setProb()` to also set prob on USB inputs
- Fixed `sfp-usb.c`: always use default descriptor (model descriptors cause segfault
  due to compound literal lifetime issues)

### Files Modified
- `afl-proxy/stage2/src/apstage2.cpp`: USB analysis functions
- `afl-proxy/stage2/src/apstage2.h`: USB data structures
- `afl-proxy/stage2/src/hw_input_model.h`: Added `numConstraints()`
- `afl-proxy/aplib/HWModel.h`: `setUSBModel()`, `feedFuzzUSBData()`, `setProb()` fix
- `afl-proxy/aplib/aplib.cpp`: Wire USB model into fuzz data path
- `afl-proxy/aplib/usb/HWModel_pegasus_notetaker.h`: Auto-extracted USB model
- `afl-proxy/aplib/usb/HWModel_ims_pcu.h`: Auto-extracted USB model
- `tools/generate_usb_model.py`: New USB model generator script
- `run-48h.sh`: Enable `USE_STAGE2=1`
- `qemu/hw/sfp/sfp-usb.c`: Always use default descriptor

---

## Previous Results (Sessions 1-3)

### gcov Coverage (24h ims_pcu / 17h pegasus)

| Metric | ims_pcu | pegasus_notetaker |
|--------|---------|-------------------|
| Line coverage | 31.2% of 861 | 59.6% of 198 |
| Branch coverage | 45.0% of 349 | 71.4% of 63 |
| Branches taken | 26.4% | 39.7% |
| Max nesting depth reached | 3 | 1 |
| AFL execs (total) | ~87K | ~86K |
| AFL bitmap | 100% (saturated) | 100% (saturated) |
| Unique crashes | 0 | 0 |

### ims_pcu Per-Function Coverage
| Function | Coverage | Entry Type |
|----------|----------|------------|
| `ims_pcu_process_data` | 100% | irq callback |
| `ims_pcu_send_cmd_chunk` | 100% | helper |
| `ims_pcu_buffers_free` | 100% | disconnect |
| `ims_pcu_probe` | 94.3% | probe |
| `ims_pcu_irq` | 86.7% | irq |
| `ims_pcu_disconnect` | 68.4% | disconnect |
| `ims_pcu_send_command` | 65.8% | helper |
| `ims_pcu_suspend/resume` | 0% | suspend/resume |
| All sysfs/firmware functions | 0% | post-probe only |

### pegasus Per-Function Coverage
| Function | Coverage | Entry Type |
|----------|----------|------------|
| `pegasus_disconnect` | 126.7% | disconnect |
| `pegasus_close` | 100% | close |
| `pegasus_irq` | 86.4% | irq |
| `pegasus_probe` | 79.8% | probe |
| `pegasus_open` | 69.6% | open |
| `pegasus_parse_packet` | 33.3% | irq helper |

### Coverage Plateau Root Cause
- **ims_pcu**: Stuck at 31% - GET_INFO command always times out because fuzz data doesn't match the IMS PCU framed protocol (STX/ETX/DLE/checksum)
- **pegasus**: 59.6% - simpler driver, higher coverage but also plateaus
- Both could be improved with protocol-aware USB device models (see [TODO-usb-model-extraction.md](TODO-usb-model-extraction.md))

### Key Fixes Applied
1. **sfp-usb.c**: USB data path (handle_datain/dataout/control), descriptor passthrough
2. **HWModel.h**: BAR bounds check (root cause of USB segfault - USB has no BARs)
3. **HWModel_ims_pcu.h / HWModel_pegasus_notetaker.h**: memcpy fallback for arbitrary USB sizes
4. **pt-runner.cpp**: PT retry on EBUSY, non-fatal failure, `pt_stop` flag for clean exit
5. **PTDecoder.h**: Fixed `get_ip_val()` for IPL>=4 (full 64-bit IP)
6. **aplib.cpp**: Watchdog timeout 60s -> 600s (10 min)
7. **ap.cpp**: `pt_stop` flag + `usleep(10ms)` before exit for PT thread cleanup

### Environment Requirements
```bash
echo -1 | sudo tee /proc/sys/kernel/perf_event_paranoid
```
