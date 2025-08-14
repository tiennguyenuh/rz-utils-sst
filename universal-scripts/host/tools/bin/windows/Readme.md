# `bin/windows/` – Windows Host Tools

This folder contains the Windows-compatible versions of firmware build utilities.
They are used automatically when the build system detects a Windows host.

## Contents

| Tool               | Platform Use Case                | Purpose |
|--------------------|----------------------------------|---------|
| `bootparameter.exe`| RZ/G2L, RZ/V2L, RZ/V2M, etc.      | Generates a boot parameter binary (`bl2_bp_<board>.bin`) from a BL2 image. |
| `bptool.exe`       | RZ/V2H                           | Generates a boot parameter binary (`bl2_bp_<board>.bin`) for RZ/V2H-specific structure. |
| `fiptool.exe`      | All                              | Creates and manipulates Firmware Image Packages (FIP) for ARM Trusted Firmware. |

## Usage Examples (PowerShell)

```powershell
# RZ/G2L or RZ/V2L example
.\bootparameter.exe bl2.bin bl2_bp.bin

# RZ/V2H example
.\bptool.exe bl2.bin bl2_bp.bin

# Create an FIP package
.\fiptool.exe create --soc-fw bl31.bin --nt-fw u-boot.bin fip.bin
```