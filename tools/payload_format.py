"""Validate SWEETXNU v1 file/range arithmetic without touching hardware.

The ADT still needs a physically verified RAM map. These checks prove internal
consistency only; they cannot establish that a claimed bank exists on a phone.
"""
import struct

HEADER_SIZE = 0x2a8
PAGE = 0x4000
U64_END = 1 << 64


def validate(blob):
    if len(blob) < HEADER_SIZE:
        raise ValueError('truncated payload header')
    magic, version, count = struct.unpack_from('<8sII', blob)
    if magic != b'SWEETXNU' or version != 1:
        raise ValueError('expected SWEETXNU v1')
    if not count or count > (len(blob) - HEADER_SIZE) // 32:
        raise ValueError('invalid segment table')
    virt, entry, adt_off, adt_size, end, phys, mem = struct.unpack_from('<7Q', blob, 0x10)
    if not mem or phys % PAGE or mem % PAGE or virt % PAGE or end % PAGE:
        raise ValueError('invalid/alignment of RAM or kernel range')
    if phys + mem > U64_END or virt + mem > U64_END or not virt < end < virt + mem:
        raise ValueError('RAM/kernel range overflows or exceeds declared memory')
    if b'\0' not in blob[0x48:HEADER_SIZE]:
        raise ValueError('unterminated command line')
    table_end = HEADER_SIZE + count * 32
    if not adt_size or adt_size > 0xffffffff or adt_off % 8 or adt_off < table_end:
        raise ValueError('invalid ADT range')
    if adt_off > len(blob) or adt_size > len(blob) - adt_off:
        raise ValueError('ADT exceeds payload')
    # Loader places ADT at kernel_end and then one aligned page of boot_args.
    boot_args = (end - virt + adt_size + PAGE - 1) & ~(PAGE - 1)
    if boot_args + PAGE > mem:
        raise ValueError('ADT/boot_args exceed declared memory')
    destinations, sources = [], [(adt_off, adt_off + adt_size)]
    entry_found = False
    for i in range(count):
        va, size, off, file_size = struct.unpack_from('<4Q', blob, HEADER_SIZE + i * 32)
        if not size or va % 8 or va < virt or va + size > end or file_size > size:
            raise ValueError(f'segment {i}: invalid destination range')
        if off % 8 or off < table_end or off > len(blob) or file_size > len(blob) - off:
            raise ValueError(f'segment {i}: invalid file range')
        destinations.append((va, va + size))
        if file_size:
            sources.append((off, off + file_size))
        entry_found |= va <= entry < va + file_size
    for ranges in (destinations, sources):
        ranges.sort()
        if any(a[1] > b[0] for a, b in zip(ranges, ranges[1:])):
            raise ValueError('overlapping payload ranges')
    if not entry_found or entry % 4:
        raise ValueError('entry is not in file-backed kernel code')
