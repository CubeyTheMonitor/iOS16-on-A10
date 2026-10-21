#!/usr/bin/env python3
"""Build an experimental SM-A105G ADT with explicitly supplied RAM placement.

No RAM address is inferred from A40, selected from firmware, or certified here.
The loader checks the proposed window against its actual incoming FDT.
Apply kernel/0002-a10-display-bringup.patch and compile XNU with SWEET_A10=1.
"""
import argparse
from pathlib import Path

import mkadt

PAGE = 0x4000
BLOCK = 0x2000000
FB_ADDRESS, FB_RESERVED = 0xec000000, 0x1400000
WIDTH, HEIGHT, STRIDE = 720, 1520, 2880


def set_prop(node, name, value):
    node.props = [(k, f, value if k == name else v) for k, f, v in node.props]
    if not any(k == name for k, _, _ in node.props):
        node.props.append((name, 0, value))


def child(node, name):
    return next(n for n in node.children if n.name == name)


def build(phys_base, mem_size, *, seed=None, emmc=False):
    if (not isinstance(phys_base, int) or not isinstance(mem_size, int) or
            phys_base <= 0 or phys_base % BLOCK or mem_size < PAGE or
            mem_size % PAGE or phys_base + mem_size >= 1 << 64):
        raise ValueError('RAM base must be nonzero/32 MiB aligned, size nonzero/16 KiB aligned, without 64-bit wrap')
    if phys_base < FB_ADDRESS + FB_RESERVED and FB_ADDRESS < phys_base + mem_size:
        raise ValueError('proposed RAM overlaps the A10 framebuffer reservation')
    root = mkadt.build(seed=seed, board='a40')
    set_prop(root, 'compatible', root.prop('compatible').replace(b'samsung,a40\0', b'samsung,a10\0'))
    set_prop(root, 'hardware-model', mkadt.cstr('SM-A105G'))
    chosen = child(root, 'chosen')
    for name, value in (
        ('dram-base', mkadt.u64(phys_base)), ('dram-size', mkadt.u64(mem_size)),
        ('firmware-version', mkadt.cstr('a10-loader-experimental')),
        ('system-firmware-version', mkadt.cstr('a10-loader-experimental')),
        ('display-scale', mkadt.u32(2)), ('unique-chip-id', mkadt.u64(0x4131300000000001)),
        ('a10-experimental', mkadt.u32(1)),
    ):
        set_prop(chosen, name, value)
    cpus = child(root, 'cpus')
    cpus.children = cpus.children[:1]  # Only the first A73, MPIDR 0.
    fbcon = child(root, 'sweet-fbcon')
    for name, value in (('reg', mkadt.u64(FB_ADDRESS, FB_RESERVED)),
                        ('width', mkadt.u32(WIDTH)), ('height', mkadt.u32(HEIGHT)),
                        ('stride', mkadt.u32(STRIDE))):
        set_prop(fbcon, name, value)
    display = child(child(root, 'arm-io'), 'disp0')
    set_prop(display, 'canvas-width', mkadt.u32(WIDTH))
    set_prop(display, 'canvas-height', mkadt.u32(HEIGHT))
    # Suppress the A40 Zinitix path. The SEC/HSI2C driver is not ready.
    # A platform marker lets the matching kernel also suppress Qualcomm input
    # without exposing a storage controller for the initial RAM-disk target.
    root.children = [n for n in root.children if n.name not in ('a40-touch', 'a40-keys', 'a40-mmc')]
    root.children.append(mkadt.node('exynos-platform', [
        ('compatible', mkadt.cstr('samsung,exynos7884b')),
        ('board', mkadt.cstr('SM-A105G')),
    ]))
    if emmc:
        # Legacy node name selects the shared dw_mmc backend. No partition ID.
        root.children.append(mkadt.node('a40-mmc', [
            ('compatible', mkadt.cstr('samsung,exynos-dw-mshc')),
            ('reg', mkadt.u64(0x13500000, 0x2000)),
        ]))
    try:
        product = child(root, 'product')
    except StopIteration:
        pass
    else:
        set_prop(product, 'artwork-scale-factor', mkadt.u32(2))
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out')
    parser.add_argument('--ram-base', type=lambda s: int(s, 0), required=True)
    parser.add_argument('--ram-size', type=lambda s: int(s, 0), required=True)
    parser.add_argument('--emmc', action='store_true', help='enable shared, physically untested dw_mmc backend; default is RAM-disk only')
    args = parser.parse_args()
    try:
        blob = mkadt.adt.serialize(build(args.ram_base, args.ram_size, emmc=args.emmc))
        with Path(args.out).open('xb') as out:
            out.write(blob)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f'{args.out}: {len(blob)} bytes; experimental A10 ADT, RAM placement unverified')


if __name__ == '__main__':
    main()
