# `bin/windows/` – Windows Host Tools

This directory contains Windows-compatible versions of the firmware utilities used in the RZ software build flow.
They are invoked automatically when the build system detects a Windows host, but it can also build them from source if required.

## Contents

| Tool               | Platform Use Case                | Purpose |
|--------------------|----------------------------------|---------|
| `bpgen.exe`        | RZ/G2L, RZ/V2L, RZ/V2H           | Generates the boot parameter binary (`bl2_bp_<board>.bin`) used by Boot ROM to load BL2|
| `fiptool.exe`      | All                              | Creates and manipulates Firmware Image Packages (FIP) for ARM Trusted Firmware (TF-A). |

## Building from Source

The prebuilt binaries are already prepared in this directory; however, they can also be compiled from source if needed.

### Prerequisites
- MinGW-w64 or MSVC
- MinGW-w64 OpenSSL: https://packages.msys2.org/packages/mingw-w64-x86_64-openssl

### Source Repositories
- `bpgen`: https://github.com/Renesas-SST/rz-utils/tree/styhead/rz-cmn/tools/bpgen
- `fiptool`: https://github.com/Renesas-SST/rz-atf/blob/styhead/rz-cmn/tools/fiptool

### Build Steps (Windows - MinGW)

1. Clone repositories:

```powershell
cd ~/workspace
git clone https://github.com/Renesas-SST/rz-atf.git -b styhead/rz-cmn
git clone https://github.com/Renesas-SST/rz-utils.git -b styhead/rz-cmn
```

2. Build bpgen:

```powershell
cd ~/workspace/rz-utils/tools/bpgen
gcc -o bpgen bpgen.c
```

3. Build Fiptool

- Install MinGW-w64 OpenSSL
 - Download the package: https://packages.msys2.org/packages/mingw-w64-x86_64-openssl
 - Extract it into C:/mingw64.

- Navigate to the fiptool folder:

```powershell
cd ~/workspace/rz-atf/tools/fiptool
```

- Compile using mingw make

```powershell
mingw32-make   OPENSSL_DIR=/c/mingw64   CFLAGS+=" -I/c/mingw64/include"   LDFLAGS+=" -L/c/mingw64/lib"
```

## Usage Examples (PowerShell)

```powershell
# Boot parameter
.\bpgen.exe --soc v2h --image bl2.bin --mode {xspi|mmc|scif|esd} --dest 0xADDR -o bl2_bp.bin [--copies N]

# Create an FIP package
.\fiptool.exe create --soc-fw bl31.bin --nt-fw u-boot.bin fip.bin
```