# TODO: USB Device Model Extraction for DEVFUZZ

## Problem
DEVFUZZ's stage2 static analysis (`afl-proxy/stage2/src/apstage2.cpp`) only supports
PCI MMIO-based drivers. It scans for `ioread32`/`iowrite32`/`readl`/`writel` calls to
extract register access patterns. USB drivers don't use these - they communicate via
`usb_bulk_msg()`, `usb_control_msg()`, and `usb_submit_urb()` with protocol-specific
data in byte buffers.

## What's Needed

### 1. USB Protocol-Aware Response Model
For each USB driver, extract the expected response format from the driver source:

**Example: ims_pcu protocol**
- Frame format: `STX(0x02) | data... | checksum | ETX(0x03)`
- DLE escaping: `DLE(0x10)` before special bytes in data
- Response codes: CMD byte | 0x20 (e.g., GET_INFO=0xA5 -> RSP=0xC5)
- Ack ID tracking: response must echo `ack_id - 1`
- Checksum: sum of all data bytes == 0 (mod 256)

The model should generate valid protocol frames with fuzzed payload data,
not purely random bytes.

### 2. Extend Stage2 LLVM Pass for USB
Modify `apstage2.cpp` to also analyze:

- `usb_bulk_msg()` / `usb_control_msg()` calls - extract buffer layouts
- `usb_submit_urb()` completion handlers - extract expected response parsing
- Buffer field comparisons (e.g., `buf[0] == RESPONSE_CODE`) - extract magic values
- Protocol state machines (STX/ETX framing, checksums) - extract frame structure
- `wait_for_completion_timeout()` patterns - identify command-response pairs

### 3. USB-Specific Model Generator
Create `tools/generate_usb_model.py` that:

1. Runs the extended LLVM pass on driver bitcode
2. Extracts protocol frame format (STX/ETX/DLE/checksum patterns)
3. Extracts command-response mappings (cmd 0xA5 -> rsp 0xC5)
4. Extracts field constraints from comparison operations
5. Generates a `USBResponseModel` class that produces valid protocol frames
   with fuzzed payload data

### 4. Runtime Model Integration
Add to `HWModel.h`:
```cpp
class USBResponseModel {
  // Generate a valid protocol response for a given command
  int generateResponse(uint8_t *dest, size_t max_len,
                       uint8_t cmd, uint8_t ack_id,
                       uint8_t *fuzz_payload, size_t fuzz_len);
};
```

Wire into `usb_sfp_handle_datain()`:
- When the driver sends a command (via handle_dataout), record the cmd byte and ack_id
- When the driver reads a response (via handle_datain), generate a valid protocol frame
  using the model, with AFL's fuzz data as the payload inside the frame

### 5. S2E-Based First Stage for USB
Extend `tools/create-s2e-project.py` to support USB devices:
- Configure S2E to use `usb-sfp` device instead of `sfp`
- Make USB data transfers symbolic
- Extract protocol state machine transitions from S2E execution traces
- Generate probe-phase model from symbolic execution results

## Priority
- **High**: Items 1 (protocol model) and 4 (runtime integration) - immediate coverage improvement
- **Medium**: Item 2 (LLVM pass) and 3 (generator) - automated model extraction
- **Low**: Item 5 (S2E USB) - full automation

## Impact
With a protocol-aware model for ims_pcu, the probe would succeed (GET_INFO returns valid data),
enabling coverage of `ims_pcu_init_application_mode()`, `setup_buttons()`, `setup_gamepad()`,
`setup_backlight()`, and all sysfs/runtime functions. Expected coverage increase: 31% -> 60%+.
