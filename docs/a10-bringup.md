# Experimental SM-A105G bring-up target

There is now A10-specific implementation code: a loader profile, an XNU display
patch, and an Apple device-tree generator. It is a first single-core RAM-disk
target. It is not yet a complete iOS port or a flashable image. No physical test
has taken place and no XNU kernel has been fully compiled in this Linux workspace.

## Implemented path

- `include/exynos_profile.h`: explicit loader board selection. The A10 candidate
  is 720×1520, 2880 bytes per row, ARGB8888/BGRA bytes at `0xec000000`, with
  DECON trigger `0x14860070 = 0x1281`. These values have A10-specific public
  evidence; equality with some A40 values is not the justification for reuse.
  Actual bootloader scanout, stride and format remain unmeasured on this phone.
- `loader/loader16.c`: A10 model and framebuffer-reservation guards, no A53
  witness startup, profile-relative diagnostic bands, and a target-core
  `ID_AA64MMFR0_EL1.TGran16 == 1` check before advertising the A73 as alive or
  entering XNU. Entry must be EL1 or EL2; other levels halt.
  `a73_mmfr0` and `a73_feature_error` (1 = granule, 2 = EL) remain ELF diagnostic symbols.
  The shared SMC/PMUCAL startup sequence has source evidence, not an A10 test.
  The A10 path stops on a failed PSCI request rather than attempting PMU startup.
- `loader/fbtext.h`: clipped fills, checked glyph coordinates and wrapping log
  rows. The A40's taller geometry cannot cause writes below the A10 buffer.
- `kernel/0002-a10-display-bringup.patch`: 720×1520/2880 display constants,
  native display size by default, and one CPU maximum when `EXYNOS_BOARD=a10`
  is passed to the XNU make invocation. Assembly diagnostics now use panel
  height and stride, replacing the A40-only rows 2200/2300 and stride 4320.
  A new `/exynos-platform` marker suppresses unrelated Qualcomm input backends
  even when the RAM-disk target has no eMMC node. A40 remains the default.
- `tools/mkadt_a10.py`: retains the upstream iPhone X userland/platform matching,
  but supplies A10 hardware identity, one A73, native display canvas and explicit
  RAM placement. It omits the A40 Zinitix input nodes and storage by default.
  `--emmc` explicitly selects the existing shared dw_mmc implementation through
  its legacy `/a40-mmc` binding. This has not been tested on A10; no numeric
  partition is selected. The initial target uses `rd=md0` instead.

The loader still validates the complete proposed RAM window against its incoming
FDT. It rejects unresolved reservations, overlaps and wrong-board trees before
framebuffer, SMC or PMU operations. The static firmware tree's four unresolved
pools still block a handoff. The source target does not bypass that condition.
A usable RAM allocation and ownership policy still have to be established.

## Build the loader object

```bash
BOARD=a10 CLANG=/path/to/clang ./loader/compile.sh loader16
```

This produces `loader/out/a10/loader16.o` and assembly, without a boot image.
The compiler needs an ARM64 ELF backend; `CLANG` can name a wrapper. The current
workspace uses Zig 0.17.0 / Clang 22.1.8 as described in
[the memory-validator build notes](loader-memory-validation.md).
A40 can still be compiled with `BOARD=a40`; explicit `OUT_DIR` is also supported.

`loader/build.sh` and `loader/pack.py` continue to refuse A10 image packaging.
Their inherited boot-header/image-size assumptions have not been replaced.
Compile-only A10 support does not make their A40 image recipe appropriate.

## Build a matching kernel and ADT

Use XNU `xnu-8796.141.3`, upstream ios-sweet patches `0001`–`0081`, then this
repository's `0000` if needed for Xcode, `0001-a40-port.patch` and finally
`0002-a10-display-bringup.patch`. The new patch is applied **on top of** the
shared A40 implementation, retaining its ARMv8.0/no-LSE and GICv2 work.
Pass `EXYNOS_BOARD=a10` to the actual make invocation along with the existing
`KERNEL_CONFIG=DEVELOPMENT MACHINE_CONFIG=SWEET` settings. It appends
`-DSWEET_A10=1` to `MACHINE_FLAGS_ARM64_SWEET` for C, C++ and assembly alike.
The KDK/Xcode support libraries and no-LSE libfirehose build are still required.

Generate the ADT with explicitly supplied candidate RAM values:

```bash
python3 tools/mkadt_a10.py a10.adt --ram-base "$A10_RAM_BASE" --ram-size "$A10_RAM_SIZE"
```

No example phone RAM address is supplied. Base must be aligned to 32 MiB for
XNU's initial block mapping; size must be nonzero and 16 KiB aligned. These
checks do not establish physical availability. The output is marked experimental
and existing files are not overwritten. `D22AP_ADT` can provide the upstream
userland `/product` properties; Apple assets are not included in this repository.

Use `tools/mkpayload.py` with the matching A10 kernel, that ADT, and a RAM-disk
root to produce a development payload. Initial boot arguments should include
`cpus=1 rd=md0 sweetfb_native=1 sweetusb=0 sweetbattery=0`, plus the existing
userland/debug arguments needed by the chosen root. A RAM disk consumes the
validated window too; a full iOS filesystem may exceed the available contiguous
RAM. Neither an Apple root image nor an A10 payload/kernel binary was produced
here. Boot-image packaging, live memory validation and actual execution remain
separate unfinished steps.

## Evidence and validation

Public framebuffer evidence: uniLoader commit
[`a459fb4c777ad9e1f3a433b14266423916f24e60`](https://github.com/ivoszbg/uniLoader/blob/a459fb4c777ad9e1f3a433b14266423916f24e60/board/samsung/board-a10.c)
and its [A10 defconfig](https://github.com/ivoszbg/uniLoader/blob/a459fb4c777ad9e1f3a433b14266423916f24e60/configs/a10_defconfig).
Only hardware constants were used; its GPL implementation was not copied.
The firmware framebuffer carve-out and SEC incell controller evidence are
recorded in [the A105GDXS8CVL5 report](firmware/a105gdxs8cvl5.md).

Validation in this workspace:

- 51 Python tests, including C sanitizer checks for board/model guards,
  exact framebuffer reservation bounds, and both renderers on host RAM.
- A10 and A40 loader objects cross-compile and pass the existing flat-object
  checks: `_head` at zero, ARM64 Image header and no relocations.
- The new patch applies and reverses cleanly against relevant source files
  from Apple XNU commit `1b191cb58250d0705d8a51287127505aa4bc0789`, upstream
  ios-sweet commit `425b25102b6a9ee4b68fb2b9ca5d6a086b8a4116` patches and
  this repository's A40 patch. This was a selected-file source check, not a
  full patched-XNU build.
- The patched XNU primary and secondary framebuffer assembly blocks compile
  for both profiles. The A10 header preprocesses to 720×1520, stride 2880 and
  one CPU. Full XNU linking and instruction auditing remain unperformed.

The SEC event decoder is present, but the HSI2C transport/controller setup and
its XNU HID connection still need implementation. Storage takeover, clocks,
panel handoff, CPU entry/cache state and boot-header packaging need testing.
No commands in these checks contact a phone or flash a partition.
