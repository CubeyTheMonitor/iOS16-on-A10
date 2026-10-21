# Galaxy A10 (SM-A105 / Exynos 7884B) port investigation

Status: source comparison and offline groundwork only. No phone was accessed,
no partition was written, and no A10 boot is established. There is no A10 boot
image in this change. The XNU patch and prebuilt images remain A40 artifacts.

Follow-up: the user's working device is SM-A105G according to Download Mode,
with a replacement display pending. See [SM-A105G evidence preparation](sm-a105g-next-steps.md)
for regional-source ambiguity and offline DTB/GPT inspection. In particular,
the common SEC touchscreen definition below must not be treated as physical
confirmation for every regional variant.

## Reproducible source baseline

Inspected on 2026-10-21:

| Source | Revision |
| --- | --- |
| [CubeyTheMonitor/iOS16-on-A10](https://github.com/CubeyTheMonitor/iOS16-on-A10/tree/3e3508f6045d4d3d5f175c53ea201e55038c8f06) | `main`, `3e3508f6045d4d3d5f175c53ea201e55038c8f06` |
| [tlfares/iOS16-on-A40](https://github.com/tlfares/iOS16-on-A40/tree/43261beae00b46b64ecceef20a075c916f78b8b1) | `main`, `43261beae00b46b64ecceef20a075c916f78b8b1` |
| [Chatur27/Eureka-Kernel-Exynos7885-Q-R](https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/tree/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48) | `Eureka-QQ-Clang`, `8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48` |

At these revisions, `git diff` between the two iOS repositories changes only
four introductory README lines. Loader, XNU patches, ADT generator, tools and
prebuilt images are identical. The fork name is not evidence of an A10 port.

Eureka here means the pinned Q/R repository above. Its shared base DTS plus
board overlays are a register/protocol reference, not a dump of a particular
SM-A105's running firmware. EUR revisions 0–4 and 5–255 select different
overlays; other regional overlays also exist. Resolve the exact device, board
revision, panel, bootloader and installed firmware before selecting a profile.

## Comparison and reuse decisions

| Component | Inherited A40 implementation | Eureka A10 evidence | Reuse / required change |
| --- | --- | --- | --- |
| Loader / CPU | Ignores incoming FDT; uses upper bank `0x880000000 + 2 GiB`; starts A73 MPIDR 0 through SMC and PMU; low secondary trampoline | Shared DTS describes A73 MPIDRs 0/1, A53 MPIDRs `0x100..103,0x200..201`, SMC CPU_ON `0xc4000003`; PMUCAL sequences match register offsets | Reuse payload ABI, exception scaffolding and CPU-family approach. Discover usable RAM and reservations from actual boot data; verify EL, granule, SMC and power sequencing. Do not infer upper RAM from A40. |
| XNU | ARMv8.0/no-LSE changes, GICv2 handling, A40 block/key/touch backends, compiled framebuffer mappings | A10 shares the CPU/GIC family and has matching key pins; Linux config uses 4K pages | Reuse no-LSE build/commpage work and GICv2 algorithms after CPU feature checks. A Linux 4K build says nothing about an iOS 16K handoff. Replace board-specific MMIO, early display writes, CPU handoff assumptions and touch backend. |
| Apple device tree | A40 RAM/1080×2340 display, `/a40-mmc`, `/a40-touch`, A73 CPUs, synthetic D22 identity | A10 uses the common Exynos base plus regional/revision overlays | Reuse ADT serialization and required iOS identity properties. Derive hardware properties from a verified A10 profile, not a text rename. Keep iOS product identity distinct from hardware identity. |
| Framebuffer | `0xec000000`, BGRA, stride 4320; DECON software kick `0x14860070 = 0x1281`; drawing rows as high as 2300 | A10 LCD and BOE LCD definitions are 720×1520, video mode, different timings; common DECON block at `0x14860000` | Reuse CPU rendering/scaling architecture. Verify actual scanout address, stride, format, buffer size, panel selection and refresh state. The fixed diagnostic rows exceed A10 height. Do not transplant the A40 trigger value. |
| eMMC | Polled dw_mmc, bootloader card state, HCON FIFO-width detection, GPT name lookup; host scripts hardcode `mmcblk0p32` | `dwmmc_0` at `0x13500000`, separate CMDQ resource, 8-bit slot, FIFO depth `0x40`, HS200/HS400 capabilities | Strongest driver reuse candidate: PIO transfers, timeouts, FIFO handling, 512-byte GPT translation. Verify live controller/card state, RCA, clocks, mode, capacity, cache and security before takeover. Discover partition by GPT label/UUID and bounds; no A10 partition index is assigned. |
| Touchscreen | Zinitix ZT7548, address `0x20`, legacy I2C4 `0x13870000`, vendor registers such as `0xc000` | `sec,sec_ts` at `0x48` on HSI2C5 `0x13930000`; SEC **incell** driver selected | Reuse HID event delivery and scheduling patterns. Implement HSI2C transactions and SEC initialization/event handling separately. Replacing the Zinitix address or I2C base cannot work. |

## Loader and memory constraints

The [shared base DTS][soc] declares low memory nodes at `0x80000000` and
`0xc0000000`, but declares **zero size** for `memory@880000000` and
`memory@900000000`. Boot firmware can fix up those nodes. Thus the static tree
does not prove either the existence or absence of upper RAM on a particular
phone, and certainly does not justify copying the A40's 2 GiB upper bank.
The [reserved-memory definitions][rmem] include framebuffer handover,
modem/GNSS, debug, audio and other carve-outs. None may be handed to XNU as
general RAM. Low RAM also contains the loader, its stack, payload, trampoline
and boot firmware data; allocating XNU there needs explicit non-overlap checks.

The [PMUCAL CPU table][pmu] contains the A40 loader's cluster-0 shortstop at
`0x10900820`, sequencer option at `0x11c82488`, and CPU configuration/status at
`0x11c82000/+4` and `0x11c82080/+4`. This is a source-level match, not proof that
the A10 firmware needs or permits the same sequence. Verify A73
`ID_AA64MMFR0_EL1.TGran16`, EL/MMU/cache state, MPIDRs, SMC results and CPU alive
signals. The A40 report of truncated PSCI entry addresses above 4 GiB is also
firmware-specific until measured on A10. Start with one A73; add SMP after a
single-core handoff is demonstrated. The A53 witness startup in the current
loader is inherited diagnostic code, not an A10 requirement.

`--like` preserves boot-header fields but cannot relocate compiled MMIO,
prove RAM is usable, identify a board, or validate payload destination ranges
against physical hardware. The packer's remaining low-memory image-size bound
is inherited A40 logic and is deliberately not presented as an A10 limit.

## XNU and device-tree work still needed

`kernel/0001-a40-port.patch` embeds the A40 platform in many places:

* `SweetCPU.cpp`: A73 topology, PMU writes and `a40sec=` trampoline.
* `pe_fiq.c` / `sleh.c`: GICv2 CPU-interface access, IAR/EOIR and SGI routing.
* `SWEET.h`, `start.s`, `arm_vm_init.c`, `sweet_early.c`: compiled framebuffer
  addresses, 32 MiB early mapping blocks, DECON access and hardcoded screen rows.
* `SweetFramebuffer.cpp`, `SweetHID.cpp`, `pe_serial.c`: geometry, canvas
  scaling, touch coordinates and optional display trigger.
* `a40_blk.c`, `sweet_ufs.c`, `a40_keys.c`, `a40_touch.c`: board peripherals.

Changing only ADT `reg` and display dimensions cannot fix these compiled early
accesses. Future board selection must cover both C and assembly, align early
mapping bases correctly and avoid drawing outside the verified framebuffer.
Retain Cortex-A73 code generation and the exclusive-loop commpage changes;
audit libfirehose and linked code for LSE instructions with an ARM disassembler.
These are reusable CPU constraints, not evidence of working A10 XNU.

The ADT generator also retains historical `qcom,kryo470`/`xiaomi,sweet`
compatibility strings for its upstream platform matching. Audit the matching
path before introducing A10 identity, rather than renaming those strings
without changing the corresponding drivers. Do not expose `/a40-touch` for an
A10: its presence starts the wrong hardware sequence.

## Display handover

The [A10 LCD][lcd] and [BOE LCD][boe] definitions agree on 720×1520 and video
mode but differ in porch values and panel selection (`lcdtype` matching for
BOE). They also use I2C4 at `0x13870000` for an LM3632 display component at
`0x11`; that bus is not the A10 touchscreen bus.

The shared reserved-memory source names an `0xec000000` framebuffer handover
region, so that address is a candidate supported by source, not an address
validated on the target. Establish the active DECON/DPP scanout, reservation,
stride and pixel format from actual handover data. Packed 32-bit pixels would
imply 2880 bytes/row, but source resolution alone does not establish that stride.

There is an additional source/runtime discrepancy: Eureka's [A40 LCD DTS][a40lcd]
also says video mode, while this port's A40 hardware notes describe manual
trigger operation. This makes the A40 trigger recipe especially unsuitable as
an inferred A10 setting. Use the actual A10 bootloader state. Normal CPU
framebuffer rendering can be reused after those facts are known; panel power,
backlight and display restart sequences remain panel-specific.

## Storage and partition discovery

The [A10 common board overlay][a10] enables `dwmmc_0` with an 8-bit slot,
FIFO depth `0x40`, CMD23 and HS400/enhanced-strobe capabilities. The base DTS
also describes CMDQ MMIO at `0x13508000`; the current XNU driver handles PIO,
not Linux's full command-queue/power/clock machinery. The Linux
[dw_mmc driver][mmc] selects 16/32/64-bit FIFO access from HCON. Reusing the
existing HCON-based selection is better than hardcoding the A40's observed
64-bit FIFO, but the current XNU code still needs an explicit rejection path
for unsupported widths and robust takeover-state validation.

The current XNU implementation inherits controller timing/state, tries RCAs
1 then 2, and assumes the eMMC cache is disabled in its flush path. A DTS
capability such as HS400 does not prove the mode S-Boot leaves active. Check
CTYPE/UHS/clock/queue state, card status and EXT_CSD/cache behavior rather than
blindly selecting HS400, changing timings or assuming writes are durable.

The kernel already finds `userdata` through GPT names and translates its
512-byte sectors to 4 KiB blocks. Preserve that approach, then add CRC,
capacity, integer-overflow, unique-name/UUID and boundary validation before any
A10 write support. The legacy host scripts and README log command use the
A40's `mmcblk0p32`; they are not A10 partition evidence. On an actual device,
collect by-name symlink targets, sizes, logical sector size and GPT metadata
read-only, and cross-check model/serial and partition identity. Leave persistent
kernel logging and filesystem writes disabled during initial bring-up.

## Touchscreen implementation boundary

The [A10 overlay][a10] specifies SEC address `0x48`, attention `gpa0-0`,
720×1520 coordinates, and firmware name `tsp_sec/s6d7at0b01_a10.fw`.
The fixed `tsp_ldo_en` supply is 3.3 V on `gpg2-1`, marked boot-on.
The [pinctrl source][pins] selects HSI2C5 on `gpc2-2/3`; the base DTS gives
the controller at `0x13930000`, clock gates and USI selection references.
Attention and supply pins happen to match the A40 family, but the transport
and controller protocol differ completely.

The A10 config selects `CONFIG_TOUCHSCREEN_SEC_INCELL_TS=y`, not
`CONFIG_TOUCHSCREEN_SEC_TS` or the A40 Zinitix option. Consult
[`sec_incell_ts/sec_ts.h`][sec-h] and [`sec_ts.c`][sec-c], plus
[`i2c-exynos5.c`][hsi2c] for the HSI2C FIFO, transfer status, timing, reset and
USI behavior. Linux's probe may run firmware update/calibration logic; do not
carry that into initial XNU input bring-up without an explicit design.

SEC uses 8-byte events: command `0x60` reads one and `0x61` reads the remainder;
the low six bits of byte 7 report queued events. Coordinate packets use a
2-bit event class, 4-bit contact ID, 2-bit action and packed 12-bit X/Y. The
new `include/sec_ts_event.h` implements only this coordinate wire decoder,
without compiler bitfields, power changes, bus access or firmware operations.
It validates slots and press/move coordinates, permits stale release
coordinates, and leaves output untouched for ignored/invalid input. It is
tested offline and **is not connected to the kernel**. A real driver still
needs bounded queue draining, status/reset handling, touch-type policy,
release-all on reset/loss, transport error recovery and HID integration.

## Changes made on `a10-portability-safety`

* `mkadt.py`, `pack.py` and `build.sh` require explicit A40 selection. A10 and
  unspecified profiles fail before building output. `pack.py` requires a stock
  header template and checks header length, version-size consistency and page
  size. The unused `--highmem` option now fails instead of silently doing nothing.
* Legacy phone-copy/write tools require `BOARD=a40`. Their hardcoded A40
  partition paths are preserved as legacy behavior, not generalized for A10.
* `payload_format.py` checks file bounds, segment/ADT overlaps, entry location,
  aligned ranges, declared memory arithmetic and space for ADT/boot_args.
  Payload generation, QEMU image construction and packaging of recognized
  SWEETXNU blobs use it. These checks validate internal consistency, not actual
  RAM ownership. The loader still trusts the supplied hardware map.
* `mkpayload.py` rejects embedded NULs and overlong command lines rather than
  silently truncating them, reserving space for the loader trampoline argument.
  The loader also bounds command-line termination inside its 608-byte buffer.
* The loader's copy and zero helpers now transfer exact byte lengths and zero
  BSS starting at the actual file end. The previous rounded-up copy could read
  and write past a short source; rounding the BSS boundary could leave bytes
  nonzero. The actual helpers are host-tested with memory sanitizers.
* The SEC packet decoder is a future driver building block only. No A10 MMIO
  constants, RAM bank sizes, partition numbers or untested initialization
  sequences were enabled. No prebuilt image or XNU patch was changed.

## Verification and next physical evidence

Run `bash tools/check-host.sh`. On this workspace it passes with Python 3.12.14,
GCC 14.2.0 and Git 2.52.0:

* Nine Python tests covering profile rejection before device/tool access,
  Android v0/v1/v2 headers, synthetic ADT/Mach-O/payload construction,
  malformed/overlapping/overflowing ranges, command-line boundaries and QEMU
  image placement without launching QEMU.
* Portable C tests under AddressSanitizer and UBSan, with warnings as errors:
  exact copy tails, unaligned BSS zeroing, heap-boundary reads and SEC event
  parsing (including all 256 first-byte values and malformed inputs).
* Python compilation, shell syntax checks, host C syntax-only checking of
  `loader16.c`, Git whitespace checking, and parsing both existing XNU patch
  files with `git apply --numstat`.

The host C syntax check does not assemble ARM instructions. No `clang`, Xcode /
`xcrun`, ARM cross compiler, `dtc`, ShellCheck or `qemu-system-aarch64` is
installed. The complete patched XNU tree, ios-sweet prerequisite patches, KDK
and Apple userland inputs are not in this repository. Therefore no full loader
ARM build, XNU build, patch-application check against XNU, DTS compile or guest
boot was performed. Patch parsing is only a patch-format check.

The next hardware work requires a read-only evidence bundle from the exact
SM-A105: model/revision/firmware, original boot header, live FDT including
overlays and reserved memory, CPU features and handoff state, active display
scanout, eMMC controller/card state plus GPT, and touchscreen identity/events.
Use that to define one conservative verified RAM window and a display profile,
then bring up one A73 with storage writes and touch initialization disabled.
Demonstrate early XNU execution on the phone before adding eMMC reads, SEC
input, SMP or persistent storage. A QEMU success cannot establish any of these
physical handoffs. Flashing and physical boot testing were outside this change.

[soc]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/exynos7885.dts
[rmem]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/exynos7885-rmem.dtsi
[a10]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/exynos7884B-a10_common.dtsi
[pmu]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/drivers/soc/samsung/cal-if/exynos7885/pmucal_cpu_exynos7885.h
[lcd]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/display-lcd_a10_common.dtsi
[boe]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/display-lcd_a10_boe_common.dtsi
[a40lcd]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/display-lcd_a40_common.dtsi
[mmc]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/drivers/mmc/host/dw_mmc.c
[pins]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/arch/arm64/boot/dts/exynos/dtbo/exynos7885-pinctrl.dtsi
[sec-h]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/drivers/input/touchscreen/sec_incell_ts/sec_ts.h
[sec-c]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/drivers/input/touchscreen/sec_incell_ts/sec_ts.c
[hsi2c]: https://github.com/Chatur27/Eureka-Kernel-Exynos7885-Q-R/blob/8dbbbae2f8f0ee79230ed37fafbcfd76002f2e48/drivers/i2c/busses/i2c-exynos5.c
