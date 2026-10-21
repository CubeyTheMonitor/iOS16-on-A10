# SM-A105G: evidence preparation without the display

Working target: **SM-A105G**, based on the user's report of Download Mode's
product name. The agent has not inspected the phone or its bootloader directly.
The replacement display is not available yet. Neither the model name nor a
software build identifies the physical RAM layout, panel or touch controller.

The `a105g-hardware-evidence` branch adds offline inspection of saved files.
It does not add an A10 boot image, enable A10 MMIO, flash a partition, or access
a phone. The A40-only build and writer guards remain in place.

Update: the user subsequently supplied a THL-labelled A105GDXS8CVL5 package.
[The firmware analysis](firmware/a105gdxs8cvl5.md) confirms its SEA board
description and SEC incell kernel configuration, records hashes and provenance
limits, and adds an Android DT table unpacker. The source-only uncertainty below
is preserved for context; actual handset RAM, panel and input remain unverified.

## Regional source finding

The pinned Eureka commit is still
`8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48` in
`Chatur27/Eureka-Kernel-Exynos7885-Q-R`. Its
[`arch/arm64/boot/dts/Makefile`][makefile] builds EUR, KOR, SEA and SWA A10
overlays. It does not explicitly map the `SM-A105G` product string to one of
them, so no regional overlay has been selected for the phone.

There is a source inconsistency worth preserving rather than guessing around:

| Source | Description |
| --- | --- |
| [A10 common overlay][common] | Enabled `hsi2c_5/touchscreen@48`, compatible `sec,sec_ts`, with SEC firmware name and 720×1520 coordinates. |
| [SWA overlay][swa] | Explicitly enables `hsi2c_5/touchscreen@48`. |
| [SEA overlay][sea] | Adds/enables `i2c_4/mms_ts@48`, but this stanza supplies neither a `compatible` nor a `reg` property. It includes the same common SEC definition. |
| [A10 stock config][config] | Enables `CONFIG_TOUCHSCREEN_SEC_INCELL_TS`; disables the listed Melfas MMS438/MSS100 drivers. Eureka's enforcing/permissive configs agree. |

The SEA stanza could be stale board-source material. Its presence is not proof
of a working Melfas driver or a Melfas controller in this device. Conversely,
the common SEC definition is not physical proof for every SM-A105G unit. The
previous offline SEC decoder remains a candidate building block, not a selected
or running device driver. Resolve this using the merged firmware/live tree and,
when accessible, the bound Linux input/I2C driver and controller identity.

## Inspect a saved device tree

```bash
python3 tools/inspect_dtb.py saved-merged.dtb > dtb-report.json
```

Input must be **one raw merged FDT v17 file**. An Android DTBO table, overlay,
concatenated DTBs, compressed firmware archive and Apple ADT are different
formats and are rejected. Firmware container extraction and correct overlay
application happen externally; this tool does not select an overlay by model
name. A firmware tree is still not a live S-Boot handoff snapshot.

The report includes source SHA-256, reported model/compatibility, root memory
bank tuples, FDT reservation-map entries, fixed/dynamic reserved-memory nodes,
and selected CPU, interrupt, display, eMMC, I2C and touch descriptions. It
retains zero-length banks, unresolved dynamic reservations and incomplete
touchscreen nodes as issues. A child's `status` is accompanied by the enabled
state of its ancestors; an enabled child under a disabled bus is not reported
as effectively enabled.

Register addresses are explicitly associated with their parent bus. The tool
does not translate arbitrary bus `ranges`, assume I2C addresses are MMIO,
identify the active scanout, or calculate a safe XNU RAM window. It supports
one/two-cell address fields and up to two size cells in the nodes it inventories.
Unrelated PCI-style three-cell buses are not interpreted.

The report omits arbitrary properties such as boot arguments and serial numbers.
`hardware_verified` remains false. It is an inventory of a file, not a hardware
profile accepted by the loader.

## Inspect GPT metadata in a saved raw disk image

```bash
python3 tools/inspect_gpt.py saved-emmc.img --sector-size 512 --partition userdata > gpt-report.json
```

The `512` in this example is an explicit example parameter, **not an established
SM-A105G sector size**. Supply the logical sector size recorded with the image;
512 and 4096 are supported. The tool requires a complete sector-aligned raw
disk image, including the backup GPT at its physical last LBA. A userdata-only
image, truncated GPT dump or Android sparse image cannot establish that layout.
Do not create or copy a large phone image merely to run this tool; use a saved
image if one is already available.

It checks the protective MBR, both header CRCs, both entry-array CRCs, matching
disk identities/table contents, usable bounds, partition overlap and unique
partition UUIDs. `--partition` requires exactly one matching label. The report
provides label, UUID, byte offset/length and 4 KiB start alignment. `gpt_slot`
is the position in that image's entry table, not a selected Android block path.
The tool never assumes `mmcblk0p32`, emits a flashing command, or repairs GPTs.
It reads metadata with bounded reads rather than loading partition data.

Both inspectors open regular saved files read-only. Block/character devices,
directories and FIFOs are rejected. There is no ADB, Odin, Heimdall or network
operation in either tool. Keep reports outside Git unless intentionally sharing
them; they can include firmware paths and disk/partition UUIDs.

## Emulator fix and validation

The new GPT validator exposed a separate bug in `tools/mkdisk.py`: its two
header-generation calls created different disk GUIDs. The builder now creates
one disk GUID and uses it in both headers. A test builds a small synthetic QEMU
disk and verifies both GPT copies and label lookup. This changes the QEMU image
builder only; its chosen layout is not transferred to the A10.

Run `bash tools/check-host.sh`. The suite now covers 27 Python tests, the existing
portable C memory/SEC decoder tests under ASan/UBSan, and the existing syntax,
patch-format and whitespace checks. New cases exercise malformed DTBs,
reservation/tuple bounds, overlays, disabled buses, both GPT sector sizes,
CRC damage, disagreeing primary/backup identities, overlapping/duplicate
partitions, read-only CLI behavior and non-regular-file rejection.

No real SM-A105G firmware, merged tree or disk image was supplied for this work.
No target ARM/XNU build, DTS compilation with `dtc`, QEMU guest boot or physical
test is claimed. The parser tests use independent synthetic binary fixtures.

The next useful input is original SM-A105G firmware evidence (exact build/CSC
and saved boot/device-tree data, if already available). After the display is
available, confirm board revision, selected panel and controller against the
running hardware. Any boot experiment still needs a verified memory window,
ARMv8.0 target build and a separate physical test plan; these tools do not make
the inherited A40 images suitable for the A10.

[makefile]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/Makefile
[common]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/exynos7884B-a10_common.dtsi
[sea]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/exynos7884B-a10_sea_open_00.dts
[swa]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/exynos7884B-a10_swa_open_00.dts
[config]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/configs/a10_00_stock_defconfig
