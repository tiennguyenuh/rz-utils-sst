#!/usr/bin/env python3
from __future__ import annotations
import argparse, platform, shutil, subprocess, sys
from dataclasses import dataclass
from pathlib import Path

# ---------- repo roots / dirs ----------
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2] if HERE.name == "firmware_compile" and HERE.parent.name == "tools" else HERE

BIN_DIRS = [
    REPO / "tools" / "bin",
    REPO / "host" / "tools" / "bin",
]
IMG_DIR = REPO / "target" / "images"

CFG_CANDIDATES = [
    REPO / "tools" / "config" / "boards_flash_config.toml",
    REPO / "config" / "boards_flash_config.toml",
]

# ---------- utils ----------
def host_os_dir() -> str:
    return "windows" if "windows" in platform.system().lower() else "linux"

def find_tool(name: str) -> Path:
    exe = f"{name}.exe" if host_os_dir() == "windows" else name
    for base in BIN_DIRS:
        cand = base / host_os_dir() / exe
        if cand.exists():
            return cand
    found = shutil.which(exe)
    if found:
        return Path(found)
    search_str = " or ".join(str((b / host_os_dir() / exe)) for b in BIN_DIRS)
    raise FileNotFoundError(f"Tool '{name}' not found at {search_str} or in PATH")

def cat_files(out_path: Path, *inputs: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as out_f:
        for inp in inputs:
            with open(inp, "rb") as in_f:
                shutil.copyfileobj(in_f, out_f)

def first_that_exists(*candidates: Path) -> Path | None:
    for c in candidates:
        if c and c.exists():
            return c
    return None

def load_toml(path: Path) -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)

def load_board_cfg(board: str) -> tuple[dict, dict]:
    cfg_path = first_that_exists(*CFG_CANDIDATES)
    base = {}
    if cfg_path and cfg_path.exists():
        allcfg = load_toml(cfg_path)
        base = allcfg.get(board, {})
        return base, allcfg
    return {}, {}

def hex_norm(x: str | int) -> str:
    """Return '0x...' string from hex-ish input like '11E00', '00000', '0x11e00', or int."""
    if isinstance(x, int):
        return f"0x{x:X}"
    s = str(x).strip()
    if s.lower().startswith("0x"):
        try:
            return f"0x{int(s,16):X}"
        except ValueError:
            pass
    # bare hex digits
    try:
        return f"0x{int(s,16):X}"
    except ValueError:
        raise ValueError(f"Invalid hex value: {x}")

@dataclass
class Tools:
    bootparameter: Path
    fiptool: Path
    objcopy: Path

class FirmwareBuilder:
    """
    Pipeline:
      1) (optional) bl2_output.bin = BL2 + <board>.dtb
      2) bl2_bp_<board>.bin/.srec : bootparameter + BL2 ; SREC VMA from TOML (by method)
      3) u-boot.bin                : u-boot-nodtb.bin + <board>.dtb
      4) fip_<board>.bin/.srec    : fiptool --align <align> --{soc|tb}-fw BL31 --nt-fw u-boot.bin ; VMA from TOML
    """
    def __init__(self, args: argparse.Namespace):
        self.board = args.board
        self.method = args.method  # 'qspi' or 'emmc'

        # Defaults derived from target/images + board
        default_bl2   = IMG_DIR / "atf"    / "bl2-rz-cmn.bin"
        default_bl31a = IMG_DIR / "atf"    / f"bl31-rz-cmn.bin"
        default_bl31b = IMG_DIR / "atf"    / "bl31-rz-cmn.bin"
        default_dtb   = IMG_DIR / "u-boot" / "dtbs" / f"rzg2l-sbc.dtb"
        default_ubnd  = IMG_DIR / "u-boot" / "u-boot-nodtb-rz-cmn.bin"

        # Resolve inputs (CLI overrides > defaults)
        self.bl2   = Path(args.bl2)  if args.bl2  else default_bl2
        self.dtbs  = Path(args.dtb)  if args.dtb  else default_dtb
        self.bl31  = Path(args.bl31) if args.bl31 else (first_that_exists(default_bl31a, default_bl31b) or default_bl31b)
        self.ubnd  = Path(args.u_boot_nodtb) if args.u_boot_nodtb else default_ubnd

        self.out_dir = Path(args.out_dir or "out").resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)

        # Tools (allow override)
        self.tools = Tools(
            bootparameter=Path(args.bootparameter) if args.bootparameter else find_tool("bootparameter"),
            fiptool=Path(args.fiptool) if args.fiptool else find_tool("fiptool"),
            objcopy=Path(args.objcopy) if args.objcopy else find_tool("objcopy"),
        )

        # Load board + method config from TOML
        board_cfg, _ = load_board_cfg(self.board)
        method_cfg = board_cfg.get(self.method, {}) if board_cfg else {}

        # --- Derive VMAs from your TOML structure ---
        # BL2 VMA: QSPI -> BL2[0]; eMMC -> BL2[2]
        bl2_arr = method_cfg.get("BL2", [])
        if args.bl2_bp_vma:
            self.bl2_bp_vma = hex_norm(args.bl2_bp_vma)
        else:
            idx = 0 if self.method == "qspi" else 2
            self.bl2_bp_vma = hex_norm(bl2_arr[idx]) if len(bl2_arr) > idx else "0x11E00"  # fallback

        # FIP VMA: first (QSPI) or third (eMMC) entry per your data
        fip_arr = method_cfg.get("FIP", [])
        if args.fip_vma:
            self.fip_vma = hex_norm(args.fip_vma)
        else:
            idx = 0 if self.method == "qspi" else 2
            self.fip_vma = hex_norm(fip_arr[idx]) if len(fip_arr) > idx else "0x0"  # fallback

        # FIP align & tb-kind: allow TOML or CLI; defaults 16 / 'soc'
        self.fip_align  = int(args.fip_align) if args.fip_align else 16
        self.fip_tb_kind = (args.fip_tb_kind or "soc").lower()
        if self.fip_tb_kind not in ("soc", "tb"):
            raise ValueError("fip_tb_kind must be 'soc' or 'tb'")

        # Outputs
        self.bl2_out       = self.out_dir / f"bl2_{self.board}.bin"
        self.bl2_bp        = self.out_dir / f"bl2_bp_{self.board}.bin"
        self.bl2_bp_esd    = self.out_dir / f"bl2_bp_esd_{self.board}.bin"
        self.bl2_bp_srec   = self.out_dir / f"bl2_bp_{self.board}.srec"
        self.uboot_withdtb = self.out_dir / f"u-boot_{self.board}.bin"
        self.fip_bin       = self.out_dir / f"fip_{self.board}.bin"
        self.fip_srec      = self.out_dir / f"fip_{self.board}.srec"

        # Soft warnings
        for p, name in [(self.bl2,"BL2"),(self.dtbs,"DTB"),(self.bl31,"BL31"),(self.ubnd,"U-BOOT-NODTB")]:
            if not p.exists():
                print(f"[warn] {name} not found at: {p}")

    # ---------- steps ----------
    def step_bl2_plus_dtb(self):
        print(f"[build] BL2+DTB -> {self.bl2_out.name}")
        if not self.bl2.exists():
            raise FileNotFoundError(f"BL2 image missing: {self.bl2}")
        if not self.dtbs.exists():
            raise FileNotFoundError(f"Board DTB missing: {self.dtbs}")
        cat_files(self.bl2_out, self.bl2, self.dtbs)

    def step_bootparameter_and_srec(self):
        print(f"[build] bootparameter -> {self.bl2_bp.name}")
        subprocess.check_call([str(self.tools.bootparameter), str(self.bl2), str(self.bl2_bp)])
        shutil.copy2(self.bl2_bp, self.bl2_bp_esd)  # eSD copy before append
        with open(self.bl2_bp, "ab") as out_f, open(self.bl2, "rb") as in_f:
            shutil.copyfileobj(in_f, out_f)
        print(f"[build] objcopy -> {self.bl2_bp_srec.name} (VMA {self.bl2_bp_vma})")
        subprocess.check_call([str(self.tools.objcopy),
                               "-I","binary","-O","srec",
                               f"--adjust-vma={self.bl2_bp_vma}","--srec-forceS3",
                               str(self.bl2_bp), str(self.bl2_bp_srec)])

    def step_uboot_with_dtb(self):
        print(f"[build] U-Boot(nodtb)+DTB -> {self.uboot_withdtb.name}")
        if not self.ubnd.exists():
            raise FileNotFoundError(f"u-boot-nodtb missing: {self.ubnd}")
        if not self.dtbs.exists():
            raise FileNotFoundError(f"Board DTB missing: {self.dtbs}")
        cat_files(self.uboot_withdtb, self.ubnd, self.dtbs)

    def step_fip_and_srec(self):
        print(f"[build] FIP -> {self.fip_bin.name}")
        if not self.bl31.exists():
            raise FileNotFoundError(f"BL31 missing: {self.bl31}")
        cmd = [str(self.tools.fiptool), "create", "--align", str(self.fip_align)]
        if self.fip_tb_kind == "tb":
            cmd += ["--tb-fw", str(self.bl31)]
        else:
            cmd += ["--soc-fw", str(self.bl31)]
        cmd += ["--nt-fw", str(self.uboot_withdtb), str(self.fip_bin)]
        subprocess.check_call(cmd)
        print(f"[build] objcopy -> {self.fip_srec.name} (VMA {self.fip_vma})")
        subprocess.check_call([str(self.tools.objcopy),
                               "-I","binary","-O","srec",
                               f"--adjust-vma={self.fip_vma}","--srec-forceS3",
                               str(self.fip_bin), str(self.fip_srec)])

    def run_all(self):
        self.step_bl2_plus_dtb()
        self.step_bootparameter_and_srec()
        self.step_uboot_with_dtb()
        self.step_fip_and_srec()
        print("\n=== Artifacts ===")
        for k, v in {
            "bl2_output": self.bl2_out,
            "bl2_bp": self.bl2_bp,
            "bl2_bp_esd": self.bl2_bp_esd,
            "bl2_bp_srec": self.bl2_bp_srec,
            "u_boot": self.uboot_withdtb,
            "fip_bin": self.fip_bin,
            "fip_srec": self.fip_srec,
        }.items():
            print(f"{k:12s} -> {v}")

# ---------- CLI ----------
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build BL2/BL2_BP/U-Boot/FIP artifacts (VMAs from TOML per board/method).")
    p.add_argument("--board", default="rzg2l-sbc")
    p.add_argument("--method", choices=["qspi","emmc"], default="qspi",
                   help="Which flash method's VMA rules to use (default: qspi)")

    p.add_argument("--bl2")
    p.add_argument("--dtb")
    p.add_argument("--bl31")
    p.add_argument("--u-boot-nodtb")
    p.add_argument("--out-dir", default=f"{IMG_DIR}")

    # tools
    p.add_argument("--bootparameter")
    p.add_argument("--fiptool")
    p.add_argument("--objcopy")

    # overrides (optional)
    p.add_argument("--fip-align")
    p.add_argument("--fip-vma")
    p.add_argument("--bl2-bp-vma")
    p.add_argument("--fip-tb-kind", choices=["soc","tb"])

    return p.parse_args(argv)

def main(argv=None):
    args = parse_args(argv)
    FirmwareBuilder(args).run_all()

if __name__ == "__main__":
    main()
