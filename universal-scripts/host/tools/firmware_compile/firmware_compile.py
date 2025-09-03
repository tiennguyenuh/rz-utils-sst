#!/usr/bin/env python3
"""
firmware_build.py — Build BL2(+ATF-FDTs), Boot Parameter (bpgen), U-Boot(+DTBs), and FIP artifacts.

Pipeline:
1) BL2+ATF-FDTs -> bl2_<board>.bin
2) Boot Parameter (bpgen) -> bl2_bp_<board>.bin
	- For G2L/V2L: MBR-style (0x55AA) sector created by bpgen
	- For V2H: structured AA55FFFF record(s) via bpgen --mode and --dest
	- (Optional) Append BL2(+FDTs) to BP for flows that expect BP+BL2 in one blob
	- Emit SREC with VMA from TOML or CLI override
3) U-Boot(nodtb)+DTBs -> u-boot_<board>.bin
4) FIP (fiptool) -> fip_<board>.bin and SREC with VMA from TOML/CLI

Inputs & Config:
- Artifacts typically reside under target/images/{atf|u-boot}
- Board/method-specific VMAs and BL2_DEST are loaded from boards_flash_config.toml
- Tools are discovered under tools/bin/<os>/ or PATH:
	* bpgen   (unified boot-parameter generator)
	* fiptool (TF-A)
	* objcopy (GNU binutils)

Notes:
- V2H requires BL2_DEST from TOML (destination address for bpgen --dest).
- G2L/V2L do not use --dest/--mode.
"""

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
	"""Return canonical host dir name used under tools/bin/<os>/ (linux/windows)."""
	return "windows" if "windows" in platform.system().lower() else "linux"

def find_tool(name: str) -> Path:
	"""Locate a tool binary under tools/bin/<os>/ or in PATH; raise if missing."""
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
	"""Concatenate multiple binary files into out_path (mkdir parents as needed)."""
	out_path.parent.mkdir(parents=True, exist_ok=True)
	with open(out_path, "wb") as out_f:
		for inp in inputs:
			with open(inp, "rb") as in_f:
				shutil.copyfileobj(in_f, out_f)

def first_that_exists(*candidates: Path) -> Path | None:
	"""Return the first existing file from candidates, or None if none exist."""
	for c in candidates:
		if c and c.exists():
			return c
	return None

def load_toml(path: Path) -> dict:
	"""Load and parse TOML file into a dictionary using tomllib or tomli."""
	if sys.version_info >= (3, 11):
		import tomllib
	else:
		import tomli as tomllib
	with open(path, "rb") as f:
		return tomllib.load(f)

def load_board_cfg(board: str) -> tuple[dict, dict]:
	"""Return (board_cfg, all_cfg) from boards_flash_config.toml for a given board."""
	cfg_path = first_that_exists(*CFG_CANDIDATES)
	if cfg_path and cfg_path.exists():
		allcfg = load_toml(cfg_path)
		return allcfg.get(board, {}), allcfg
	return {}, {}

def hex_norm(x: str | int) -> str:
	"""Normalize int/hex-ish string to uppercase '0x...'."""
	if isinstance(x, int):
		return f"0x{x:X}"
	s = str(x).strip()
	if s.lower().startswith("0x"):
		return f"0x{int(s,16):X}"
	return f"0x{int(s,16):X}"

@dataclass
class Tools:
	"""Paths to external tools used in the firmware build pipeline."""
	bootparameter: Path
	fiptool: Path
	objcopy: Path

class FirmwareBuilder:
	"""
	Build pipeline driver: BL2(+FDTs), Boot Parameter, U-Boot(+DTBs), FIP(+SREC).
	Resolves defaults from target/images and boards_flash_config.toml.
	"""

	def __init__(self, args: argparse.Namespace):
		"""Initialize build context: resolve inputs, outputs, tools, and VMAs."""
		self.board = args.board
		self.soc = args.soc.lower()
		self.method = args.method  # 'qspi' or 'emmc'

		# Defaults derived from target/images + board
		default_bl2   = IMG_DIR / "atf"    / "bl2-rz-cmn.bin"
		default_bl31  = IMG_DIR / "atf"    / "bl31-rz-cmn.bin"
		default_atf_fdts   = [IMG_DIR / "atf"    / "fdts" / f"{self.board}.dtb"]
		default_uboot_dtbs = [IMG_DIR / "u-boot" / "dtbs" / f"{self.board}.dtb"]
		default_ubnd  = IMG_DIR / "u-boot" / "u-boot-nodtb-rz-cmn.bin"

		# Resolve inputs (CLI overrides > defaults)
		self.bl2   = Path(args.bl2)  if args.bl2  else default_bl2
		self.atf_fdts = [Path(p) for p in (args.atf_fdts or default_atf_fdts)]
		self.uboot_dtbs = [Path(p) for p in (args.uboot_dtbs or default_uboot_dtbs)]
		self.bl31  = Path(args.bl31) if args.bl31 else default_bl31
		self.ubnd  = Path(args.u_boot_nodtb) if args.u_boot_nodtb else default_ubnd

		self.out_dir = Path(args.out_dir or "out").resolve()
		self.out_dir.mkdir(parents=True, exist_ok=True)

		# Tools (allow override)
		self.tools = Tools(
			bootparameter=Path(args.bootparameter) if args.bootparameter else find_tool("bpgen"),
			fiptool=Path(args.fiptool) if args.fiptool else find_tool("fiptool"),
			objcopy=Path(args.objcopy) if args.objcopy else find_tool("objcopy"),
		)

		# Load board + method config from TOML
		board_cfg, _ = load_board_cfg(self.board)
		method_cfg = board_cfg.get(self.method, {}) if board_cfg else {}

		# BL2_BP VMA: index 0 (qspi) or 2 (emmc), unless overridden
		bl2_arr = method_cfg.get("BL2", [])
		if args.bl2_bp_vma:
			self.bl2_bp_vma = hex_norm(args.bl2_bp_vma)
		else:
			idx = 0 if self.method == "qspi" else 2
			self.bl2_bp_vma = hex_norm(bl2_arr[idx]) if len(bl2_arr) > idx else "0x11E00"

		# FIP VMA: index 0 (qspi) or 2 (emmc), unless overridden
		fip_arr = method_cfg.get("FIP", [])
		if args.fip_vma:
			self.fip_vma = hex_norm(args.fip_vma)
		else:
			idx = 0 if self.method == "qspi" else 2
			self.fip_vma = hex_norm(fip_arr[idx]) if len(fip_arr) > idx else "0x0"

		# BL2_DEST (only relevant for V2H)
		self.bl2_dest = method_cfg.get("BL2_DEST")

		# FIP align & tb-kind
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
		for p, name in [(self.bl2,"BL2"),(self.bl31,"BL31"),(self.ubnd,"U-BOOT-NODTB")]:
			if not p.exists():
				print(f"[warn] {name} not found at: {p}")
		if not any(p.exists() for p in self.atf_fdts):
			print(f"[warn] ATF FDTs not found at: {self.atf_fdts}")
		if not any(p.exists() for p in self.uboot_dtbs):
			print(f"[warn] U-Boot DTBs not found at: {self.uboot_dtbs}")

	def step_bl2_plus_fdts(self):
		"""Concatenate BL2 with ATF FDTs into bl2_<board>.bin."""
		print(f"[build] BL2+ATF-FDTs -> {self.bl2_out.name}")
		fdts = [p for p in self.atf_fdts if p.exists()]
		if not self.bl2.exists():
			raise FileNotFoundError(f"BL2 image missing: {self.bl2}")
		if not fdts:
			raise FileNotFoundError(f"ATF FDTs missing (checked: {self.atf_fdts})")
		cat_files(self.bl2_out, self.bl2, *fdts)

	def step_bootparameter_and_srec(self):
		"""Generate boot parameter, append BL2+ATF-FDTs, and convert to SREC."""
		print(f"[build] bootparameter -> {self.bl2_bp.name}")
		bp_cmd = [str(self.tools.bootparameter), "--soc", self.soc,
				"--image", str(self.bl2_out), "-o", str(self.bl2_bp)]
		if self.soc == "v2h":
			bp_cmd += ["--mode", self.method, "--dest", self.bl2_dest]

		subprocess.check_call(bp_cmd)
		shutil.copy2(self.bl2_bp, self.bl2_bp_esd)
		with open(self.bl2_bp, "ab") as out_f, open(self.bl2_out, "rb") as in_f:
			shutil.copyfileobj(in_f, out_f)
		print(f"[build] objcopy -> {self.bl2_bp_srec.name} (VMA {self.bl2_bp_vma})")
		subprocess.check_call([str(self.tools.objcopy),
							"-I","binary","-O","srec",
							f"--adjust-vma={self.bl2_bp_vma}","--srec-forceS3",
							str(self.bl2_bp), str(self.bl2_bp_srec)])

	def step_uboot_with_dtbs(self):
		"""Concatenate u-boot-nodtb with U-Boot DTBs into u-boot_<board>.bin."""
		print(f"[build] U-Boot(nodtb)+DTBs -> {self.uboot_withdtb.name}")
		dtbs = [p for p in self.uboot_dtbs if p.exists()]
		if not self.ubnd.exists():
			raise FileNotFoundError(f"u-boot-nodtb missing: {self.ubnd}")
		if not dtbs:
			raise FileNotFoundError(f"U-Boot DTBs missing (checked: {self.uboot_dtbs})")
		cat_files(self.uboot_withdtb, self.ubnd, *dtbs)

	def step_fip_and_srec(self):
		"""Generate FIP image (BL31+U-Boot), then convert to SREC with VMA."""
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
		"""Run the full build pipeline sequentially."""
		self.step_bl2_plus_fdts()
		self.step_bootparameter_and_srec()
		self.step_uboot_with_dtbs()
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
	"""Parse command-line arguments for firmware_build.py."""
	p = argparse.ArgumentParser(description="Build BL2/BL2_BP/U-Boot/FIP artifacts (VMAs from TOML per board/method).")
	p.add_argument("--board", default="rzg2l-sbc")
	p.add_argument("--soc", choices=["g2l", "v2l", "v2h"], default="g2l",
				help="Target SoC family")
	p.add_argument("--method", choices=["qspi","emmc"], default="qspi",
				help="Which flash method's VMA rules to use (default: qspi)")

	p.add_argument("--bl2")
	p.add_argument("--atf-fdts", nargs="+", help="ATF FDT(s) to append to BL2 for bl2_<board>.bin")
	p.add_argument("--uboot-dtbs", nargs="+", help="U-Boot DTB(s) to append to u-boot-nodtb")
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
	"""Entrypoint: parse args, build firmware pipeline."""
	args = parse_args(argv)
	FirmwareBuilder(args).run_all()

if __name__ == "__main__":
	main()
