# Runtime memory validation groundwork

The later [A10 source target](a10-bringup.md) adds an explicit compile-only
A10 profile. The validation described here still runs before its hardware path.

The loader now reads the incoming raw FDT v17 in `x0`, rather than discarding
it. It validates the **entire** RAM window described by the SWEETXNU payload,
including space XNU could allocate later. It does not select RAM addresses,
change the Apple device tree, probe RAM, or enable an A10 boot profile.

This is a strict preflight change to an experimental loader. Existing A40
setups may now halt if their tree is missing, unsupported, or contains pools
whose final addresses cannot be established. Previously built images are
unchanged. No phone has run this version.

## Validation order

Before `fill`, `kick`, SMC/PMU operations, or payload-directed copies,
`loader16.c` performs these checks:

1. Parse a bounded FDT (maximum 16 MiB, 32 nesting levels, 16 nonzero banks,
   128 fixed reservations). Validate block bounds, reserve-map termination,
   tokens, relevant duplicate properties, tuple widths and integer overflow.
   Only root memory nodes describe physical RAM; disabled banks are excluded.
   One- and two-cell addresses/sizes are supported. Overlay fragments and
   `linux,usable-memory[-range]` restrictions are rejected rather than ignored.
2. Record reserve-map entries, fixed `/reserved-memory` children and the
   `/chosen` initrd span. Require explicit identity mapping (empty `ranges`)
   on `/reserved-memory`. Preserve disabled/reusable fixed reservations
   conservatively. Missing or zero-sized reserved tuples and dynamic pools
   remain unresolved; unsupported nested reservation layouts are rejected.
3. Check the Image's payload bounds and SWEETXNU v1 layout: segment table,
   file-backed entry, source/destination overlap, BSS extents, command-line
   capacity, Apple-tree placement, and the boot-arguments page.
4. Require the complete proposed physical RAM window to fit **one** positive
   bank and overlap neither fixed reservations nor the loaded Image and FDT.
   The loaded Image includes the loader code, embedded stack, globals,
   secondary trampoline, payload source and optional ramdisk. Do not join
   adjacent banks or silently subtract holes. Any unresolved pool blocks
   acceptance even if the proposed window avoids the known fixed carve-outs.
5. Require the model string selected at compilation: A40 by default or A10
   for `BOARD=a10`. The A10 target also requires the entire pixel span inside a
   fixed reservation (`0x301` on failure). A tree cannot switch a binary into
   the other board profile. The existing
   `BOARD=a40` / `--board a40` packaging guards remain in place.

`fdt_memory.h` and `payload_check.h` are allocation-free and use no libc or
peripheral operations. Runtime destinations use validated offsets from the
payload's physical base. The memory reader cannot prove that a physical pointer
is mapped: the boot protocol must supply an accessible FDT, and the loader
Image header must accurately describe its accessible loaded extent. This is
bounds validation, not authentication of those inputs. It does not validate
all later A40 peripheral operations, CPU feature state, firmware scratch space
omitted from the tree, or the Apple tree's compiled-in A40 assumptions.

## Silent diagnostics

Failures before display initialization save an error and halt with `wfe`.
They do not try to draw using an unverified A40 framebuffer. A fault before
that point records ESR and FAR and also halts silently.

`loader_diagnostics` remains an ELF symbol. Its fields, in order, are seven
64-bit words (`signature`, `fdt_pa`, `map_pa`, `image_pa`, `image_size`, `esr`,
`far`), then two 32-bit words (`stage`, `error`). Signature is
`0x4c4d454d00000001`. `map_pa` points to the `struct fm_map` from
`fdt_memory.h`. Locate these from the matching ELF symbol offsets plus the
actual load base; no fixed phone address is assigned. They require a working
external debug/memory-read method and are not automatically visible over USB.

| Stage | Last completed step |
| --- | --- |
| 1 | Entered C and began FDT validation |
| 2 | FDT parsed |
| 3 | Payload layout validated |
| 4 | Whole RAM window accepted |
| 5 | Selected board gate accepted; display path may begin |

Error `1..12` uses `enum fm_error`; `11` means unresolved reservations.
`0x100 + enum pc_error` indicates a payload failure, `0x200` an Image extent
failure, `0x300` the board gate, `0x301` a missing framebuffer reservation, and `0x400` an early exception. A failed parse
leaves `map.valid == 0`; partial inventory data must not authorize a handoff.

## Offline evidence and checks

Run `bash tools/check-host.sh`. The suite includes 46 Python tests, including
12 tests using a C adapter to execute the exact runtime parser and payload
checker under ASan/UBSan. Cases include malformed/truncated trees and payloads,
fixed and dynamic reservations, ignored zero-sized RAM placeholders, disabled
memory, 64-bit overflow, capacity limits, source and destination overlap,
loader/FDT protection, full-window bounds, and deterministic malformed input
mutations. The fixtures are synthetic, not established phone addresses.
Existing portable memory/SEC tests and syntax/patch/whitespace checks also run.

For a compile-only ARM64 check with an ELF-capable Clang:

```bash
CLANG=/path/to/clang ./loader/compile.sh loader16
```

This creates assembly and `loader/out/loader16.o` only. It reuses the same
flattening step as `build.sh` and runs `pack.elf_text` to reject relocations,
unexpected allocated sections, a misplaced `_head`, or a missing ARM64 Image
header. It does **not** produce `boot.img`, download a kernel, or access a device.
`OUT_DIR` can select another output directory. `CLANG` can name an executable
wrapper if the compiler uses a different target spelling.

In this workspace, Zig 0.17.0's Clang 22.1.8 compiled the object with Cortex-A73
code generation. Its wrapper translated `aarch64-none-elf` to
`aarch64-freestanding-none` and `cortex-a73` to `cortex_a73`, and suppressed
Zig's internally generated unused `-c` warning during `-S`. The flat object
passed the no-relocation/header checks (56,784 bytes). This is a loader object
check, not an XNU build, instruction-set audit of linked XNU libraries, guest
boot or physical execution test.

The same C reader was also run read-only against the offline merged
[A105GDXS8CVL5 firmware tree](firmware/a105gdxs8cvl5.md), SHA-256
`66a0bf617b3d8f3db48bd7d30674be6a579038dd3cb4ad9d7d2a0fa6dcb79f47`.
It parsed two positive RAM banks, two zero-sized placeholders, 11 fixed
reservations and four unresolved pools. A sample candidate window
`0x90000000 + 0x10000000` was **rejected** with `FM_UNRESOLVED`; those numbers
are a negative test input, not an A10 allocation or recommendation. This
static firmware tree is not the live S-Boot handoff. Runtime fixups may resolve
pools, but that must be observed rather than assumed.

Further work can proceed on public-source display, storage and touch code
while the replacement display is pending. An actual A10 profile still needs
consistent RAM/ADT/XNU mapping, a verified display handoff and CPU state, and
physical testing. No firmware was flashed and no A10 boot is claimed.
