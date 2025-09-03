# `bin/linux/` – Linux Host Tools

This folder contains the Linux-compatible versions of firmware build utilities.
They are used automatically when the build system detects a Linux host.

## Contents

| Tool               | Platform Use Case                | Purpose |
|--------------------|----------------------------------|---------|
| `bpgen.exe`        | RZ/G2L, RZ/V2L, RZ/V2H           | Generates a boot parameter binary (`bl2_bp_<board>.bin`)|
| `fiptool.exe`      | All                              | Creates and manipulates Firmware Image Packages (FIP) for ARM Trusted Firmware. |

## Building from Source

The prebuilt binaries are already prepared in this directory; however, they can also be compiled from source if needed.

### Prerequisites
- GNU toolchain and OpenSSL dev package

```
sudo apt-get install build-essential libssl-dev
```

### Source Repositories
- `bpgen`: https://github.com/Renesas-SST/rz-utils/tree/styhead/rz-cmn/tools/bpgen
- `fiptool`: https://github.com/Renesas-SST/rz-atf/blob/styhead/rz-cmn/tools/fiptool

### Build Steps (GNU)

1. Clone the repositories just in case:

```shell
cd ~/workspace
git clone https://github.com/Renesas-SST/rz-atf.git -b styhead/rz-cmn
git clone https://github.com/Renesas-SST/rz-utils.git -b styhead/rz-cmn
```

2. Build Bootparameter

```shell
cd ~/workspace/rz-utils/tools/bpgen
gcc -o bpgen bpgen.c
```

3. Build Fiptool

- Navigate to the fiptool folder:

```
cd ~/workspace/rz-atf/tools/fiptool
```

- Compile using mingw make

```
make
```

## Usage Examples (PowerShell)

```powershell
# Boot parameter
.\bpgen --soc v2h --image bl2.bin --mode {spi|mmc|scif|esd} --dest 0xADDR -o bl2_bp.bin [--copies N]

# Create an FIP package
.\fiptool create --soc-fw bl31.bin --nt-fw u-boot.bin fip.bin
```