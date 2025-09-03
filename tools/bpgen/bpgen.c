/*
* bpgen.c — Unified Boot Parameter Generator for Renesas RZ SoCs
*
* Overview:
*   This tool generates the boot parameter binary required by
*   the Boot ROM on RZ devices. The boot parameter tells the ROM how to
*   load BL2: where it is located, how large it is, and where it
*   should be copied in memory.
*
* Supported SoCs:
*   - G2L, V2L:
*       * Format: MBR-like sector (512 bytes)
*       * Fields:
*           [0..3]   : BL2 size (4-byte aligned)
*           [4..509] : Padding (0xFF)
*           [510]    : 0x55
*           [511]    : 0xAA
*       * Always exactly 1 sector.
*
*   - V2H:
*       * Format: structured 512-byte record
*       * Fields:
*           size     : BL2 size (4-byte aligned)
*           load     : Load offset (depends on boot mode)
*           dest     : Destination address (argument)
*           sign     : 0xAA55FFFF
*       * Records are repeated depending on boot mode:
*           spi/mmc/scif = 1 record
*           esd          = 7 records (redundancy)
*       * Optional --copies N can override the default.
*
* Usage:
*   For G2L/V2L:
*       bpgen --soc {g2l|v2l} --image bl2.bin -o bl2_bp.bin
*
*   For V2H:
*       bpgen --soc v2h --image bl2.bin --mode {spi|mmc|scif|esd} \
*             --dest 0xADDR -o bl2_bp.bin [--copies N]
*
* Notes:
*   - The binary format must match the SoC’s ROM parser exactly.
*   - A single binary cannot be shared across G2L/V2L and V2H, but this
*     unified tool generates the correct one depending on --soc.
*
* Copyright (C) 2025 Renesas Electronics Corp.
*/

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <errno.h>

/* Common */
#define BP_SECTOR_SIZE				512U
#define BP_WORD_ALIGN				4U

/* G2L / V2L (MBR-like) */
#define BP_G2L_PADDING_VALUE		0xFF
#define BP_G2L_PADDING_SIZE			506U	/* 512 - 4(size) - 2(signature) */
#define BP_G2L_SIG_LOW				0x55
#define BP_G2L_SIG_HIGH				0xAA

/* V2H */
#define BP_V2H_SIGNATURE			0xAA55FFFFu
#define BP_V2H_COPIES_DEFAULT		1U
#define BP_V2H_COPIES_ESD			7U

/* V2H load offsets by boot mode */
#define BP_V2H_LOAD_SPI				0x00000200u
#define BP_V2H_LOAD_MMC 			0x00000400u
#define BP_V2H_LOAD_SCIF			0x00000200u
#define BP_V2H_LOAD_ESD				0x00001000u

/* ------------------------------ Types -------------------------------- */
typedef enum {
	SOC_G2L,
	SOC_V2L,
	SOC_V2H
} soc_t;

typedef enum {
	BP_MODE_SPI,
	BP_MODE_MMC,
	BP_MODE_SCIF,
	BP_MODE_ESD
} bp_mode_t;

/* V2H boot-parameter sector layout (exactly 512 bytes) */
typedef struct __attribute__((packed)) {
	uint32_t size;				/* aligned size of BL2 */
	uint32_t pad1[3];
	uint32_t load;				/* boot loader load offset (per boot mode) */
	uint32_t pad2[3];
	uint32_t dest;				/* destination address for loader */
	uint32_t pad3[3];
	uint32_t pad4[115];
	uint32_t sign;				/* AA55FFFF */
} v2h_bp_t;

typedef struct {
	const char *image_path;		/* input file (BL2) */
	const char *out_path;		/* output boot-parameter file */
	soc_t		soc;			/* target SoC family */
	bp_mode_t	mode;			/* V2H boot mode (ignored for G2L/V2L) */
	uint32_t	dest_addr;		/* V2H destination address (ignored for G2L/V2L) */
	int			copies_set;		/* whether copies override was provided */
	uint32_t	copies;			/* V2H copy count (optional override) */
} bp_args_t;


/* ---------------------------- Functions implementation ---------------------------- */
/* Print usage/help text */
static void print_usage(const char *prog) {
	fprintf(stderr,
		"Usage:\n"
		"  %s --soc {g2l|v2l} --image bl2.bin -o bl2_bp.bin\n"
		"  %s --soc v2h --image bl2.bin --mode {spi|mmc|scif|esd} --dest 0xADDR -o bl2_bp.bin [--copies N]\n"
		"\n"
		"Options:\n"
		"  --soc     Target SoC family (g2l, v2l, v2h)\n"
		"  --image     Input loader binary (BL2)\n"
		"  -o        Output boot-parameter file\n"
		"  --mode    V2H boot mode (spi, mmc, scif, esd) — required for v2h\n"
		"  --dest    V2H destination address (hex, e.g., 0x08103000) — required for v2h\n"
		"  --copies  V2H copy count override (default: 1; esd: 7)\n",
		prog, prog);
}

/* Get file size; returns -1 on error */
static off_t file_size(const char *path) {
	struct stat st;
	if (stat(path, &st) != 0) return -1;
	return st.st_size;
}

/* Parse --soc string into enum */
static int parse_soc(const char *s, soc_t *out_soc) {
	if (!s || !out_soc) return -1;
	if (strcmp(s, "g2l") == 0) { *out_soc = SOC_G2L; return 0; }
	if (strcmp(s, "v2l") == 0) { *out_soc = SOC_V2L; return 0; }
	if (strcmp(s, "v2h") == 0) { *out_soc = SOC_V2H; return 0; }
	return -1;
}

/* Parse --mode string into enum */
static int parse_mode(const char *s, bp_mode_t *out_mode) {
	if (!s || !out_mode) return -1;
	if (strcmp(s, "spi")  == 0) { *out_mode = BP_MODE_SPI;  return 0; }
	if (strcmp(s, "mmc")  == 0) { *out_mode = BP_MODE_MMC;  return 0; }
	if (strcmp(s, "scif") == 0) { *out_mode = BP_MODE_SCIF; return 0; }
	if (strcmp(s, "esd")  == 0) { *out_mode = BP_MODE_ESD;  return 0; }
	return -1;
}

/* Compute 4-byte aligned value */
static uint32_t align4(uint32_t v) {
	return (v + (BP_WORD_ALIGN - 1U)) & ~(BP_WORD_ALIGN - 1U);
}

/* Select V2H load offset and default copy count from boot mode */
static void v2h_select_load_and_copies(bp_mode_t mode, uint32_t *load_off, uint32_t *copies_out) {
	switch (mode) {
		case BP_MODE_SPI:  *load_off = BP_V2H_LOAD_SPI;  *copies_out = BP_V2H_COPIES_DEFAULT; break;
		case BP_MODE_MMC:  *load_off = BP_V2H_LOAD_MMC;  *copies_out = BP_V2H_COPIES_DEFAULT; break;
		case BP_MODE_SCIF: *load_off = BP_V2H_LOAD_SCIF; *copies_out = BP_V2H_COPIES_DEFAULT; break;
		case BP_MODE_ESD:  *load_off = BP_V2H_LOAD_ESD;  *copies_out = BP_V2H_COPIES_ESD;     break;
		default:           *load_off = 0;                *copies_out = BP_V2H_COPIES_DEFAULT; break;
	}
}

/* Write G2L/V2L boot-parameter sector (512 bytes)
* Layout:
*   [0..3]   : aligned size (4 bytes, little-endian)
*   [4..509] : 0xFF padding (506 bytes)
*   [510]    : 0x55
*   [511]    : 0xAA
*/
static int write_bp_g2l_v2l(const char *image_path, const char *out_path) {
	off_t sz = file_size(image_path);
	if (sz <= 0) {
		fprintf(stderr, "Error: cannot stat IPL file '%s': %s\n", image_path, strerror(errno));
		return -1;
	}

	uint32_t aligned = align4((uint32_t)sz);

	FILE *fp = fopen(out_path, "wb");
	if (!fp) {
		fprintf(stderr, "Error: cannot open '%s' for write: %s\n", out_path, strerror(errno));
		return -1;
	}

	/* write 4-byte aligned size */
	if (fwrite(&aligned, 1, 4, fp) != 4) {
		fprintf(stderr, "Error: write failed (size)\n");
		fclose(fp);
		return -1;
	}

	/* pad 506 bytes with 0xFF */
	for (uint32_t i = 0; i < BP_G2L_PADDING_SIZE; i++) {
		if (fputc(BP_G2L_PADDING_VALUE, fp) == EOF) {
			fprintf(stderr, "Error: write failed (padding)\n");
			fclose(fp);
			return -1;
		}
	}

	/* trailing signature 0x55 0xAA */
	if (fputc(BP_G2L_SIG_LOW, fp) == EOF || fputc(BP_G2L_SIG_HIGH, fp) == EOF) {
		fprintf(stderr, "Error: write failed (signature)\n");
		fclose(fp);
		return -1;
	}

	/* final size check for safety */
	long end_pos = ftell(fp);
	if (end_pos != (long)BP_SECTOR_SIZE) {
		fprintf(stderr, "Error: output not 512 bytes (got %ld)\n", end_pos);
		fclose(fp);
		return -1;
	}

	fclose(fp);
	return 0;
}

/* Write V2H boot-parameter sector(s) (one or more copies)
* Each sector (512B) has:
*   - size (aligned to 4B)
*   - load (per mode)
*   - dest (provided via --dest)
*   - signature AA55FFFF
* The sector is repeated 'copies' times (esd typically 7).
*/
static int write_bp_v2h(const char *image_path, const char *out_path,
						bp_mode_t mode, uint32_t dest_addr,
						int copies_set, uint32_t copies_override) {
	off_t sz = file_size(image_path);
	if (sz <= 0) {
		fprintf(stderr, "Error: cannot stat IPL file '%s': %s\n", image_path, strerror(errno));
		return -1;
	}

	uint32_t aligned = align4((uint32_t)sz);

	uint32_t load_off = 0, copies = 1;
	v2h_select_load_and_copies(mode, &load_off, &copies);

	if (copies_set) {
		if (copies_override == 0) {
			fprintf(stderr, "Error: --copies must be >= 1\n");
			return -1;
		}
		copies = copies_override;
	}

	FILE *fp = fopen(out_path, "wb");
	if (!fp) {
		fprintf(stderr, "Error: cannot open '%s' for write: %s\n", out_path, strerror(errno));
		return -1;
	}

	v2h_bp_t bp;
	memset(&bp, 0xFF, sizeof(bp));
	bp.size = aligned;
	bp.load = load_off;
	bp.dest = dest_addr;
	bp.sign = BP_V2H_SIGNATURE;

	for (uint32_t i = 0; i < copies; i++) {
		if (fwrite(&bp, 1, sizeof(bp), fp) != sizeof(bp)) {
			fprintf(stderr, "Error: write failed at copy %u\n", i);
			fclose(fp);
			return -1;
		}
	}

	/* sanity: each record is exactly 512 bytes */
	if (sizeof(bp) != BP_SECTOR_SIZE) {
		fprintf(stderr, "Error: v2h sector struct is not 512 bytes (is %zu)\n", sizeof(bp));
		fclose(fp);
		return -1;
	}

	fclose(fp);
	return 0;
}

/* Parse CLI arguments into bp_args_t
* Returns 0 on success, -1 on error.
*/
static int parse_args(int argc, char **argv, bp_args_t *args) {
	memset(args, 0, sizeof(*args));
	args->out_path = "bl2_bp.bin"; /* default output name */

	const char *soc_s = NULL, *mode_s = NULL, *dest_s = NULL, *copies_s = NULL;

	for (int i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--soc") == 0 && i + 1 < argc) {
			soc_s = argv[++i];
		} else if (strcmp(argv[i], "--image") == 0 && i + 1 < argc) {
			args->image_path = argv[++i];
		} else if (strcmp(argv[i], "-o") == 0 && i + 1 < argc) {
			args->out_path = argv[++i];
		} else if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
			mode_s = argv[++i];
		} else if (strcmp(argv[i], "--dest") == 0 && i + 1 < argc) {
			dest_s = argv[++i];
		} else if (strcmp(argv[i], "--copies") == 0 && i + 1 < argc) {
			copies_s = argv[++i];
		} else {
			fprintf(stderr, "Error: unknown or incomplete option '%s'\n", argv[i]);
			return -1;
		}
	}

	if (!soc_s || !args->image_path) {
		fprintf(stderr, "Error: --soc and --image are required\n");
		return -1;
	}
	if (parse_soc(soc_s, &args->soc) != 0) {
		fprintf(stderr, "Error: invalid --soc (use g2l, v2l, or v2h)\n");
		return -1;
	}

	if (args->soc == SOC_V2H) {
		if (!mode_s || !dest_s) {
			fprintf(stderr, "Error: --mode and --dest are required for --soc v2h\n");
			return -1;
		}
		if (parse_mode(mode_s, &args->mode) != 0) {
			fprintf(stderr, "Error: invalid --mode (use spi, mmc, scif, esd)\n");
			return -1;
		}
		char *endp = NULL;
		unsigned long val = strtoul(dest_s, &endp, 0);
		if (endp == dest_s || *endp != '\0') {
			fprintf(stderr, "Error: invalid --dest (use hex/dec, e.g., 0x44000000)\n");
			return -1;
		}
		args->dest_addr = (uint32_t)val;

		if (copies_s) {
			args->copies_set = 1;
			char *endq = NULL;
			unsigned long cval = strtoul(copies_s, &endq, 0);
			if (endq == copies_s || *endq != '\0' || cval == 0UL) {
				fprintf(stderr, "Error: invalid --copies (must be >= 1)\n");
				return -1;
			}
			args->copies = (uint32_t)cval;
		}
	}

	return 0;
}

/* ------------------------------- main -------------------------------- */
int main(int argc, char **argv) {
	bp_args_t args;
	if (argc <= 1) {
		print_usage(argv[0]);
		return 1;
	}
	if (parse_args(argc, argv, &args) != 0) {
		print_usage(argv[0]);
		return 1;
	}

	int rc = -1;
	switch (args.soc) {
		case SOC_G2L:
		case SOC_V2L:
			rc = write_bp_g2l_v2l(args.image_path, args.out_path);
			break;
		case SOC_V2H:
			rc = write_bp_v2h(args.image_path, args.out_path,
							args.mode, args.dest_addr,
							args.copies_set, args.copies);
			break;
		default:
			fprintf(stderr, "Internal error: unknown SoC\n");
			rc = -1;
			break;
	}

	if (rc == 0) {
		fprintf(stdout, "OK: wrote %s\n", args.out_path);
		return 0;
	}
	return 2;
}
