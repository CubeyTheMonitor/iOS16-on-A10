# User-supplied SM-A105G firmware: A105GDXS8CVL5

Inspected 2026-10-21. The user supplied an `sf09.click` download link whose
response filename is `SAMFW.COM_SM-A105G_THL_A105GDXS8CVL5_fac.zip`.
The ZIP declares 3,601,198,414 bytes. The expiring download URL and all firmware
binaries are kept outside this Git repository.

[Machine-readable evidence and component SHA-256 hashes](a105gdxs8cvl5-evidence.json)
record exactly which files and properties were inspected. This report describes
that package, not a firmware readback from the user's handset.

## Package and extraction

| Component | Observed package label |
| --- | --- |
| AP | `A105GDXS8CVL5`, CL21848546, QB60494482, `OS11` |
| BL | `A105GDXS8CVL5`, CL21848546, QB60494482 |
| CP | `A105GDXS8CVL1` |
| CSC / HOME_CSC | `OLM_A105GOLM8CVG2` |
| Download filename region | `THL` |

HTTP range requests read the ZIP directory and the useful beginning of the AP
TAR, stopping before the large system partition. The AP supplied
`boot.img.lz4`, `recovery.img.lz4`, **`dt.img.lz4`** and `dtbo.img.lz4`.
LZ4 frame decompression succeeded; SHA-256 hashes of compressed and decompressed
components are recorded. The complete AP/CSC ZIP entries and their appended MD5
trailers were not read, so their final ZIP CRCs/MD5s were **not verified**.

The small BL ZIP entry was read completely and passed ZIP CRC checking. Its
appended MD5 matches the bytes before the checksum line, including Samsung's
additional TAR metadata (hashing only `original_tar_file_size` bytes would use
the wrong checksum boundary). This is an integrity check, not verification
against a trusted Samsung signing key. No Samsung-origin authentication is
claimed for this third-party download.

## Concrete firmware findings

| Area | Observed fact | Port consequence |
| --- | --- | --- |
| Boot image | Android boot header v1; page size 2048; header encodes Android 11.0.0 and patch 2022-12 | Useful stock packaging reference. Header load fields are not proof of S-Boot's runtime placement. |
| Kernel | `Linux 4.4.177-21848546`, built 2022-12-20; embedded IKCONFIG recovered | Provides firmware-specific driver configuration rather than relying only on the older Eureka config. |
| Touch configuration | `CONFIG_TOUCHSCREEN_SEC_INCELL_TS=y`; the listed Melfas and Zinitix drivers are disabled | SEC incell is the implemented touchscreen family in this package's kernel. Physical controller identity still needs the handset. |
| Base/overlay containers | Both are padded 8 MiB Android DT tables v0, each containing one FDT | The new container unpacker can extract them with bounds and FDT validation. They are not directly consumable as raw DTBs. |
| Board overlay | Compatible `samsung,A10 SEA OPEN 00`, `samsung,EXYNOS7884B`; merged model `Samsung A10 SEA OPEN 00 board based on EXYNOS7884B` | Establishes the board description carried by this THL package; does not prove the user's actual board revision. |
| CPU | Six A53 nodes, MPIDRs `0x100..0x103,0x200..0x201`; two A73 nodes, MPIDRs 0/1 | Supports the existing A73 bring-up approach as a source-level candidate. Runtime feature and power checks remain necessary. |
| Display | Both S6D7AT0B and BOE descriptions say 720×1520 and mode 0 (video); DECON `psr_mode=0`, `trig_mode=1` | Do not use A40 1080×2340 geometry or infer which physical panel is present. Active scanout, pixel format and stride remain unknown. |
| Interrupts/eMMC | GIC distributor/CPU interface `0x12301000/0x12302000`; dw_mmc `0x13500000`, CMDQ `0x13508000` | Matches the shared register-family candidates in Eureka. Bootloader/card state is not present in a static DTB. |

The boot header's kernel/tag fields are `0x10008000` / `0x10000100`; the kernel
file size is 29,112,000 bytes. These values are recorded as **header fields**,
not as approved physical addresses for a new loader.

### RAM and carve-outs

Applying the single supplied overlay to the single supplied base with libfdt
1.7.2 succeeded. The packed merged DTB has SHA-256
`66a0bf617b3d8f3db48bd7d30674be6a579038dd3cb4ad9d7d2a0fa6dcb79f47`.
It declares:

| Memory node base | Size in static merged firmware tree |
| --- | --- |
| `0x80000000` | `0x3da00000` |
| `0xc0000000` | `0x40000000` |
| `0x880000000` | **0** |
| `0x900000000` | **0** |

This is further evidence against blindly using the A40 loader's
`0x880000000 + 2 GiB` bank. It is not proof of the handset's final RAM map or
capacity: S-Boot can fix up memory and resolve dynamic reservations before
handoff. No low-memory substitute was selected either.

The framebuffer handover reservation is `0xec000000 + 0x01400000` (20 MiB),
which does not by itself identify the active framebuffer. Dynamic reservations
include a 40 MiB `video_frame` pool plus audio, crypto and video-stream pools.

There are material differences from the pinned Eureka
`exynos7885-rmem.dtsi`: this firmware describes modem memory at
`0xf5400000 + 0x07800000` and CP logging at `0xfcc00000 + 0x02000000`, while
that source file describes `0x08800000` modem bytes and logging at `0xfdc00000`.
The firmware's values are not replacements to hardcode; these differences show
why a live reservation map is required.

### Touch ambiguity narrowed

The merged firmware tree contains a complete, enabled SEC node at
`/hsi2c@13930000/touchscreen@48`, with `sec,sec_ts`, address `0x48`, coordinates
720×1520 and firmware `tsp_sec/s6d7at0b01_a10.fw`. It also retains the incomplete
`/i2c@13870000/mms_ts@48` node seen in the SEA source: that node has neither
`compatible` nor `reg`.

Combined with this kernel's embedded configuration, the incomplete Melfas-like
stanza does not justify selecting a Melfas driver. The SEC decoder remains
relevant to this firmware. This still does not establish an actual running
input device or authorize SEC initialization on an uninspected phone.

### Partition metadata

The CSC contains a file named `A10_SWA_OPEN.pit` with 37 declared records,
despite the SEA board model in its device-tree overlay. A PIT filename is not a
board-selection rule. Its partition labels include BOOT, RECOVERY, DTB, DTBO,
VBMETA and USERDATA. The flash filename for DTB is `dt.img`.

USERDATA's **PIT identifier** is 32. That is not an established Linux
`mmcblk0p32` path, a GPT slot, a proven block offset or a partition size. No live
GPT was supplied, and the PIT's USERDATA extent is not a fixed capacity. The
existing GPT inspector and the rule against guessing partition numbers remain
unchanged. No PIT was applied to any device.

## Reproducing the DT container inspection

After obtaining/decompressing the AP's two images locally, use:

```bash
python3 tools/unpack_dt_table.py dt.img --out-dir firmware-evidence/base
python3 tools/unpack_dt_table.py dtbo.img --out-dir firmware-evidence/overlay
```

Each command inventories **all** entries and can export them into a new
directory, with a hash manifest. Existing directories are refused. The parser
supports the observed uncompressed v0 layout, checks declared ranges and FDT
structure, preserves ID/revision/custom selector fields as data, and accepts
partition padding outside the declared table size. It never chooses a board
entry or applies an overlay automatically.

The base can be inventoried with `inspect_dtb.py`; that tool deliberately
rejects an overlay as standalone hardware evidence. This investigation used
`pylibfdt 1.7.2.post2` to apply the supplied overlay offline and then inspected
the resulting merged file. Optional `lz4 4.4.5` and pylibfdt were installed
outside the repository; they are not required by the host test suite or the
container unpacker. Raw firmware, raw FDTs and the URL are not committed.

## Checks and remaining boundary

`bash tools/check-host.sh` passes: **34 Python tests**, the existing C
ASan/UBSan tests, Python/shell/C syntax checks and patch/whitespace checks. Seven
new tests cover valid base/overlay containers, padding, malformed headers,
out-of-bounds entries, invalid FDTs, exact aliases, partial overlaps, read-only
source handling and refusal to overwrite exports. The new unpacker also parsed
both real 8 MiB firmware containers successfully.

No A10 loader/kernel profile was enabled, no A40 memory address or partition
index was assigned to this phone, and no firmware was flashed or executed.
This package narrows the software target considerably, but booting still needs
live S-Boot memory/reservation evidence, actual display handover information,
an ARM/XNU target build and physical testing. The absence of a display is not
evidence of a successful or failed kernel handoff.
