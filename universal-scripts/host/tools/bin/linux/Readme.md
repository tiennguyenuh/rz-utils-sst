# `bin/linux/` – Linux Host Tools

This folder contains the Linux-native versions of firmware build utilities.
They are used automatically when the build system detects a Linux host.

## Contents

| Tool            | Platform Use Case                | Purpose |
|-----------------|----------------------------------|---------|
| `bootparameter` | RZ/G2L, RZ/V2L, RZ/V2M, etc.      | Generates a boot parameter binary (`bl2_bp_<board>.bin`) from a BL2 image. |
| `bptool`        | RZ/V2H                           | Generates a boot parameter binary (`bl2_bp_<board>.bin`) for RZ/V2H-specific structure. |
| `fiptool`       | All                              | Creates and manipulates Firmware Image Packages (FIP) for ARM Trusted Firmware. |

## Usage Examples

```bash
# RZ/G2L or RZ/V2L example
./bootparameter bl2.bin bl2_bp.bin

# RZ/V2H example
./bptool bl2.bin bl2_bp.bin

# Create an FIP package
./fiptool create --soc-fw bl31.bin --nt-fw u-boot.bin fip.bin
```