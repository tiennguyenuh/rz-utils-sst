# firmware-compile.py

## Overview
`firmware-compile.py` is a helper script for building Renesas RZ family firmware artifacts, including **BL2**, **Boot Parameter (BP)** files, **U-Boot** binaries, and **FIP** packages.  

It automatically pulls board and flash-method–specific configuration (such as VMA addresses) from:
- [`boards_flash_config.toml`](tools/config/boards_flash_config.toml or config/boards_flash_config.toml)  
- [`flash_images.json`](target/images/flash_images.json)  

The script supports multiple boards and flash methods without hardcoding addresses.

---

## Features
- Generates **BL2 + DTB** combined binary.
- Creates **Boot Parameter + BL2** binary and `.srec` with correct VMA offset.
- Builds **U-Boot (nodtb) + DTB** combined binary.
- Generates **FIP** binary and `.srec` with correct VMA offset.
- Reads **board-specific DTB filenames** from `flash_images.json`.
- Reads **flash memory address mapping** from `boards_flash_config.toml`.
- Supports both **Windows** and **Linux** build hosts.

---

## Prerequisites
Make sure you have the following installed or available in `tools/bin/<os>` or `host/tools/bin/<os>`:
- `bootparameter`
- `fiptool`
- `objcopy` (part of GNU binutils)
- Python 3.8+ (Python 3.11+ recommended for built-in TOML parsing)

Firmware binaries and DTBs must be available in (already included in release package):

```
target/images/
```


## Usage
Basic example:

```bash
python3 firmware-compile.py --board rzg2l-sbc --method qspi
```

This will:
1. Build bl2_<board>.bin (BL2 + board DTB)
2. Build bl2_bp_<board>.bin and .srec
3. Build u-boot_<board>.bin (U-Boot + board DTB)
4. Build fip_<board>.bin and .srec

## CLI Options

| Option                | Default          | Description |
|-----------------------|------------------|-------------|
| `--board`             | `rzg2l-sbc`      | Target board name (must exist in `boards_flash_config.toml` and `flash_images.json`). |
| `--method`            | `qspi`           | Flash method (`qspi` or `emmc`). |
| `--bl2`               | auto from images | Path to BL2 binary (override default). |
| `--dtb`               | auto from JSON   | Path to ATF DTB (override default). |
| `--bl31`              | auto from images | Path to BL31 binary (override default). |
| `--u-boot-nodtb`      | auto from images | Path to U-Boot (nodtb) binary (override default). |
| `--out-dir`           | `out`            | Output directory for generated files. |
| `--bootparameter`     | auto search      | Path to `bootparameter` tool (override search path). |
| `--fiptool`           | auto search      | Path to `fiptool` tool (override search path). |
| `--objcopy`           | auto search      | Path to `objcopy` tool (override search path). |
| `--fip-align`         | `16`             | FIP alignment. |
| `--fip-vma`           | from TOML        | Override VMA for FIP `.srec`. |
| `--bl2-bp-vma`        | from TOML        | Override VMA for BL2+BP `.srec`. |
| `--fip-tb-kind`       | `soc`            | FIP firmware kind: `soc` or `tb`. |
| `--skip-bl2-output`   | *(flag)*         | Skip BL2 + DTB step. |

---

## Output Files

| File Name                     | Description                                         |
|--------------------------------|-----------------------------------------------------|
| `bl2_<board>.bin`              | BL2 + ATF DTB binary                                |
| `bl2_bp_<board>.bin`           | Boot Parameter + BL2 binary                         |
| `bl2_bp_esd_<board>.bin`       | ESD copy of BL2 BP before BL2 append                |
| `bl2_bp_<board>.srec`          | BL2 BP in Motorola S-record format (with correct VMA) |
| `u-boot_<board>.bin`           | U-Boot (nodtb) + U-Boot DTB binary                  |
| `fip_<board>.bin`              | Firmware Image Package binary                       |
| `fip_<board>.srec`             | FIP in Motorola S-record format (with correct VMA)  |

## Notes

- VMAs are pulled from boards_flash_config.toml per board and flash method.
- ATF DTB and U-Boot DTB names are taken from flash_images.json.
- All tools are prebuilt in tools/bin/<os> or host/tools/bin/<os> unless overridden.