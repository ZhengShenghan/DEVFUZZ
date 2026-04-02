## About
Code for IEEE S&P 2023 - DEVFUZZ: Automatic Device Model-Guided Device Driver Fuzzing

## Dependency
### LLVM-13
install LLVM-13:   
```
sudo ./llvm.sh 13 all
```

### WLLVM
WLLVM is used for performing static analysis on Linux

Install with pip:
```
pip install wllvm
```

## Build  DevFuzz
First, We need to build QEMU, AFL, AFL-Proxy and S2E

Under the project directory, Run:
```
make
```

Second, We need to build a image for fuzzing:
```
cd images
./build-image.sh
```
This will produce a debian image called stretch.img

At last, We need a image for S2E:
### Build From Scratch
TODO

### Use Pre-built Image
You can download a image from our google drive and extract it to **s2e/images/**
Download link  can be found inside s2e-image-link.txt

## Build Linux Kernel for Fuzzing
Clone a verison  of Linux Kernel (e.g. v5.15)
```
git clone --depth 1 --branch v5.15 https://github.com/torvalds/linux.git
```
Config the Kernel, include all the drivers you want to test as kernel modules  
Examples:
```
cd linux
make defconfig / allmodconfig / menuconfig
```
Or use an existing config
```
mv ../config-linux-5.15 .config
``` 
Apply the patch
```
git apply ../afl-proxy/stage2-guest-kernel-patch/<Patch Name>
```

Compile the kernel
```
./tools/shell_scripts/compile_and_deploy.sh
```


## Build Linux Kernel for Static Analysis
In the project directory:
```
mkdir analysis && cd analysis
git clone --depth 1 --branch v5.15 https://github.com/torvalds/linux.git
```
Config the kernel, include all the drivers you want to analyze as kernel modules
Examples:
```
cd linux
make allmodconfig
``` 

Compile the kernel with WLLVM
```
# in the root of project directory
./wllvm-compile-linux.sh
``` 

Extract Bitcode from a kernel module

Example:
```
extract-bc analysis/linux/drivers/net/ethernet/intel/e1000/e1000_main.o -l /usr/bin/llvm-link-13
``` 

## Fuzzing with Device Models
This projects ships with over 100 pre-built device models that you can perform fuzzing with. You can also build device models by yourself, which is covered in the next section. All the PCI devices are listed in **afl-proxy/aplib/pci**

### Probing Phase Fuzzing
#### Prepare Test Script
```
echo "./probe.sh" > .bashrc
./tools/shell_scripts/transfer-to-img.sh .bashrc
```

In one terminal:
```
sudo python3 ./tools/launch-afl.py -s <SHMID> -c <CORE>
```
In other terminal:
```
sudo python3 ./tools/fuzz_probe.py -c <CORE> -s <SHMID> -d <DEVICE> -p <PROB> -m <MODE>
```
They must use the same CORE (cpu id) and SHMID (shared memory id).

Example:
```
sudo python3 ./tools/launch-afl.py -s 0 -c 0
sudo python3 ./tools/fuzz_probe.py -c 0 -s 0 -d e1000 -p 50 -m fuzz
```

### Post-Probing Phase Fuzzing
#### Prepare a test script
You can have a custom test scripts to drive the device, some examples can be found in tools/test test_scripts. You can use **tools/shell_scripts/transfer-to-img.sh** to transfer a you custom scripts into the image. For example, to have a script running automatically on boot to test the Ethernet NICs, you need to insert "./test-nic.sh" into .bashrc and put it inside the image.

Fuzzing is similar to Probing Phase Fuzzing.
Example:
```
# In two seperate terminals
sudo python3 ./tools/launch-afl.py -s 0 -c 0
sudo python3 ./tools/fuzz.py -c 0 -s 0 -d e1000 -p 50 -m dma
```

## Build Device Model
Before doing anything, you need to extract the prebuilt S2E Debian/Linux image to s2e/images folder
### Initialization
```
cd s2e/projects
./setup.sh
```
### First Stage Model
Create a S2E project
```
python3 ./tools/create-s2e-project.py -d <DEV> -v <VID> -p <PID> --subvid <SUBVID> --subpid <SUBPID> --cls <ClassID> [--pio_bar <id:range>]
```
Then go to **s2e/projects**
```
./run-s2e.sh <DEV>
# After finishing running
cd <DEV>
sudo ./get_result.sh
python3 <PROJ_ROOT>/tools/generate_probe_model.py -v <VID> -p <PID> -n <DEV>  >  <HWMODEL_xxx.h>
```
### Second Stage Model
Second Stage perform one profiling run to get the DMA register and static analysis to generate a model for post-probing fuzzing
```
sudo python3 <PROJ_ROOT>/tools/generate_postprobing_model.py --file <HWMODEL_xxx.h> --bc <xxx.bc> --name <xxx> --profile_dma --verbose
```

### Insert Model into the Database
go to **afl-proxy/aplib/hw_model.cpp** to register the devide model. Examples can be found in this file.

## USB Device Fuzzing

USB device models are in **afl-proxy/aplib/usb/**. The USB fuzzing path uses the same AFL + QEMU architecture as PCI, but with different QEMU device (`usb-sfp` instead of `sfp`).

### Prerequisites
```bash
# Intel PT requires relaxed perf permissions
echo -1 | sudo tee /proc/sys/kernel/perf_event_paranoid

# Kill any stale proxy processes (they hold PT resources)
sudo pkill -9 -f "afl-fuzz|qemu-system|ap "

# Ensure the guest image has the USB probe script
# The script reads the driver name from kernel cmdline: usb_driver=<name>
```

### Prepare Guest Image
The guest `.bashrc` should run `./usb-probe.sh` which reads the driver name from the kernel command line parameter `usb_driver=`:
```bash
cat tools/test_scripts/usb-probe.sh
# #!/bin/bash
# name=$(cat /proc/cmdline | grep -oP 'usb_driver=\K\S+' || echo "ims_pcu")
# echo "USB Probing: $name"
# while [ true ]; do rmmod $name 2>/dev/null; sleep 2; modprobe $name; dmesg | tail -5; done

./tools/shell_scripts/transfer-to-img.sh tools/test_scripts/usb-probe.sh
echo "./usb-probe.sh" > .bashrc
./tools/shell_scripts/transfer-to-img.sh .bashrc
```

### Running USB Probing Fuzzing (Manual)
Unlike PCI fuzzing which uses `tools/fuzz_probe.py`, USB fuzzing currently requires direct QEMU invocation due to differences in the SFP device setup.

**Terminal 1 - Launch AFL:**
```bash
cd run-<device>-probe && echo > afl.log
sudo AFL_SKIP_CPUFREQ=1 AFL_NO_AFFINITY=1 \
  AFL/afl-fuzz -t 500000000+ -m 256 \
  -i tools/seed -o out -d -f seed \
  afl-proxy/proxy/build/ap @@ <CORE> <SHMID>
```

**Terminal 2 - Launch QEMU:**
```bash
sudo SFP_SHMID=<SHMID> AP_DISABLED=0 TEST_PROBE=1 \
  USE_DMA=0 USE_IRQ=0 USE_STAGE2=0 \
  SFP_DEV_MODEL=<DEVICE> AFL_EPOCH=5 \
  WAITGDB=0 EXPORT_DEVMEM=0 \
  MODEL_PROBE_FUZZ=1 MODEL_RESET_TIME=1 MODEL_MUTATE_PROB=50 \
  AP_DUMP_RW=0 \
  taskset -c <CORE> \
  build-qemu-exp/x86_64-softmmu/qemu-system-x86_64 \
  -machine q35,accel=kvm -m 2G -smp 1 \
  -kernel images/bzImage-master \
  -append "nokaslr nosoftlockup console=ttyS0 root=/dev/vda \
    earlyprintk=serial biosdevname=0 net.ifnames=0 loglevel=8 \
    security=none ro rootfstype=ext4 mitigations=off \
    cryptomgr.notests clocksource=tsc audit=0 parport=0 \
    kmemleak=on nosmp usb_driver=<DEVICE>" \
  -drive file=images/stretch.img,if=virtio,format=raw -snapshot \
  -net none -usb -device usb-sfp \
  -nographic -serial file:vm-testing-<SHMID>.log
```

**Example (ims_pcu on core 0, SHMID 0):**
```bash
# Terminal 1
cd run-ims_pcu-probe && echo > afl.log
sudo AFL_SKIP_CPUFREQ=1 AFL_NO_AFFINITY=1 \
  AFL/afl-fuzz -t 500000000+ -m 256 -i tools/seed -o out -d -f seed \
  afl-proxy/proxy/build/ap @@ 0 0

# Terminal 2
sudo SFP_SHMID=0 AP_DISABLED=0 TEST_PROBE=1 USE_DMA=0 USE_IRQ=0 USE_STAGE2=0 \
  SFP_DEV_MODEL=ims_pcu AFL_EPOCH=5 WAITGDB=0 EXPORT_DEVMEM=0 \
  MODEL_PROBE_FUZZ=1 MODEL_RESET_TIME=1 MODEL_MUTATE_PROB=50 AP_DUMP_RW=0 \
  taskset -c 0 build-qemu-exp/x86_64-softmmu/qemu-system-x86_64 \
  -machine q35,accel=kvm -m 2G -smp 1 \
  -kernel images/bzImage-master \
  -append "nokaslr nosoftlockup console=ttyS0 root=/dev/vda earlyprintk=serial \
    biosdevname=0 net.ifnames=0 loglevel=8 security=none ro rootfstype=ext4 \
    mitigations=off cryptomgr.notests clocksource=tsc audit=0 parport=0 \
    kmemleak=on nosmp usb_driver=ims_pcu" \
  -drive file=images/stretch.img,if=virtio,format=raw -snapshot \
  -net none -usb -device usb-sfp -nographic -serial file:vm-testing-0.log
```

### Monitoring & Resume
```bash
# Quick status
sudo bash check-status.sh

# Resume experiment if it dies (keeps AFL queue + gcov data)
sudo bash run-48h.sh resume
```

### Coverage Analysis & Plotting
gcov data is dumped every ~2 minutes by the guest VM into `share-*/gcov/`.
Each run's dumps are stored in a separate subdirectory (e.g., `run_01_old/`, `run_02_current/`).

```bash
# List available runs
sudo python3 analyze-coverage.py --list

# Plot latest run (default)
sudo python3 analyze-coverage.py

# Plot a specific old run
sudo python3 analyze-coverage.py --run run_01_old

# Plot all runs side by side
sudo python3 analyze-coverage.py --run all --output coverage-all-runs.png

# Text-only report
sudo python3 analyze-coverage.py --text
```

Results are cached in `share-*/gcov/<run>/trend_cache.json` so re-plotting is fast.

The plot shows 3 columns per driver:
1. **Coverage over time** - line coverage, branch executed, branch taken (%)
2. **Branch depth** - branches taken/executed/not-executed at each nesting depth
3. **Line depth** - lines covered/uncovered at each nesting depth

### Supported USB Devices
| Device | VID:PID | Driver | gcov Coverage |
|--------|---------|--------|---------------|
| IMS PCU | 04d8:0082 | ims_pcu | 31.2% line, 45% branch |
| Pegasus Notetaker | 0e20:0101 | pegasus_notetaker | 72.2% line, 84% branch |

### Key Differences from PCI Fuzzing
- Uses `-usb -device usb-sfp` instead of `-device sfp`
- No IOMMU needed (remove `-device intel-iommu`)
- Coverage via Intel PT (same as PCI)
- `AFL_EPOCH=5` recommended for probing (5 seconds per epoch)
- USB models have no MMIO/DMA stage2 models (empty by design)
- The QEMU SFP USB device uses the model's USB descriptors for proper driver matching

## Collect Code Coverage
We use gcov to collect code coverage. Please refer to [linux-gcov](https://github.com/yiluwusbu/DEVFUZZ/tree/master/afl-proxy/linux-gcov) for details.

## Cite

```
@INPROCEEDINGS{10179293,
  author={Wu, Yilun and Zhang, Tong and Jung, Changhee and Lee, Dongyoon},
  booktitle={2023 IEEE Symposium on Security and Privacy (SP)}, 
  title={DevFuzz: Automatic Device Model-Guided Device Driver Fuzzing}, 
  year={2023},
  volume={},
  number={},
  pages={3246-3261},
  keywords={Privacy;Operating systems;Linux;Computer bugs;Fuzzing;Universal Serial Bus;Device drivers},
  doi={10.1109/SP46215.2023.10179293}}
```
