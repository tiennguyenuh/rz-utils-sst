# `bin/` – Prebuilt Firmware Utility Binaries

This directory contains precompiled tools required for the firmware build and packaging process.
They are organized by operating system to support cross-platform usage.

## Structure

- **`linux/`** – Executables for Linux hosts.
- **`windows/`** – Executables for Windows hosts.

## Purpose

These tools are used by scripts such as `firmware-compile.py` to:
- Generate boot parameter files.
- Build Firmware Image Packages (FIP).
- Manipulate firmware binaries.

The correct OS-specific binaries are automatically selected by the build scripts.
