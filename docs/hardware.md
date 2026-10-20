# Galaxy A40 (Exynos 7904) hardware notes

Everything the port relies on, with the reason for each non-obvious choice. Sources: Samsung's A40 kernel (`exynos7885.dtsi`, `exynos7904-a40_common.dtsi`, `drivers/soc/samsung/cal-if/exynos7885/*`), measurements on the phone.

## Boot

* S-Boot loads `boot.img` (Android header v1) and enters the image at **EL1**, MMU off, on a **Cortex-A53** (MPIDR 0x100). Load address varies (0x80xxxxxx).
* RAM: 0x80000000 (≈1 GB), 0xC0000000 (1 GB, 0xE0000000–0xEFFFFFFF reserved), **0x880000000 (2 GB)**. XNU only uses the 2 GB bank, so the loader stays intact in low memory.
* CPUs: 6 × A53 (MPIDR 0x100–0x103, 0x200–0x201), **2 × A73 (MPIDR 0x0, 0x1)**. iOS 16 needs the 16K granule: A73 only.
* PSCI v0.1 through `smc` (`PSCI_VERSION` returns -1): `CPU_ON` 0xC4000003, `CPU_OFF` 0x84000002.
  * `CPU_ON` returns 0 but **does not power the core**. Like Samsung's PMUCAL, write the PMU:
    `CLUSTER0_SHORTSTOP` (0x10900820) = 0xFFFFFFFF, `CLUSTER0_CPUSEQUENCER_OPTION` (0x11C82488) bit4 = 1 / bit0 = 0, `CLUSTER0_CPUn_CONFIGURATION` (0x11C82000 + n·0x80) |= 0xF. Status at +4 (0xF = on).
  * The entry point must be **below 4 GiB** (higher addresses never start): the kernel uses a trampoline left by the loader (`a40sec=` boot-arg).
* CPU clock: PLL_CPUCL0 at 0x10900140 (26 MHz × M / (P × 2^S)), S-Boot leaves 1352 MHz. Higher steps (1698, 2192 MHz) need ACPM voltage changes.

## Interrupts and timer

* GIC-400 (GICv2): GICD 0x12301000, GICC 0x12302000, non-secure view (only Group 1, `GICC_CTLR` bit0). In QEMU (no security extensions) Group 1 also needs `GICC_CTLR` bits 1 and 2 (AckCtl); ITARGETSR reads 0 on a one-CPU GIC.
* Virtual timer PPI, INTID 27; CNTFRQ 26 MHz.

## Display

* Framebuffer 0xEC000000, 1080 × 2340, stride 4320, BGRA, left on by S-Boot.
* DECON in manual-trigger mode: write 0x1281 to **0x14860070** after each update.
* iOS sees an iPhone X panel (1125 × 2436 @3x); the centred 1080 × 2340 part is shown. Lower render sizes (828 × 1792 @2x) get stuck at @3x: the scale comes from the D22 identity.

## Storage (eMMC)

* dw_mmc at 0x13500000 (verid 0x270a), card left by S-Boot in 8-bit DDR, RCA 1.
* **HCON reports a 64-bit FIFO**: FIFO count and data port are 64-bit, reading 32-bit stalls after 256 bytes (HTO).
* Polled PIO, CMD17/18/24/25 with auto-stop, IDMAC off. `userdata` = mmcblk0p32 (GPT read in 512-byte sectors).

## Input

* Keys: GPA1 at 0x11CB0060, active low: power = bit 7, vol+ = bit 5, vol- = bit 6.
* Touch: Zinitix ZT7548 (chip code 0xE548) at address 0x20 on i2c_4 (s3c2440-type controller, 0x13870000).
  * Pins gpp4-0/1 function 2 (TOP pinctrl 0x139B0000 + 0xA0); power `tsp_avdd` = gpg2-1 (+0x160); attention line gpa0-0 (0x11CB0040), active low.
  * Clock: CMU_PERI 0x10010000, gate 0x2048 (bits 20/21), Q-channel 0x3028 (already on).
  * **IICCON bit 5 (IRQEN) must be set** or the pending flag never rises, even when polling.
  * Power-on: 0xC000 = 1, 0xC004, 0xC002 = 1, wait, 0xC001 = 1; then SWRESET 0x0000, TOUCH_MODE 0x0010 = 0, read point info at 0x0080 (4 + 5 × 6 bytes), clear with 0x0003.

## CPU features

* A73 = ARMv8.0: **no LSE atomics, no PAN**. The kernel is built `-mcpu=cortex-a73`, the commpage `casa` is replaced by an LDAXR/STXR loop, libfirehose_kernel is rebuilt. The iOS 16 arm64 (non-arm64e) shared cache has no LSE.
* QEMU's cortex-a76 has PAN: SCTLR_EL1.SPAN is set so exceptions don't set PSTATE.PAN (RES1 on the A73, harmless).
