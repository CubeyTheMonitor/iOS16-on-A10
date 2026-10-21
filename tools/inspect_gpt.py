#!/usr/bin/env python3
"""Validate primary/backup GPTs in a saved full raw disk image, read-only.

The logical sector size must be supplied from evidence, not guessed from A40.
No block-device access, partition writes, flashing or repair is implemented.
"""
import argparse
import json
import struct
import uuid
import zlib

from evidence_io import regular_file

MAX_TABLE = 16 << 20


def read_at(stream, offset, size):
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError('truncated GPT metadata')
    return data


def read_table(stream, sector_size, sectors, location):
    block = read_at(stream, location * sector_size, sector_size)
    fields = struct.unpack_from('<8s4I4Q16sQ3I', block)
    magic, version, size, crc, reserved, current, backup, first, last, guid, entries_lba, count, entry_size, entries_crc = fields
    if magic != b'EFI PART' or version != 0x10000 or not 92 <= size <= sector_size or reserved:
        raise ValueError('invalid GPT header signature, revision or size')
    header = bytearray(block[:size])
    struct.pack_into('<I', header, 16, 0)
    if zlib.crc32(header) != crc:
        raise ValueError('GPT header CRC mismatch')
    if current != location or backup != (sectors - 1 if location == 1 else 1):
        raise ValueError('GPT header locations do not match disk size')
    if not 2 <= first <= last < sectors - 1 or guid == bytes(16):
        raise ValueError('invalid GPT usable range or disk GUID')
    if not count or entry_size < 128 or entry_size & (entry_size - 1) or count * entry_size > MAX_TABLE:
        raise ValueError('invalid or excessive GPT entry table')
    table_sectors = (count * entry_size + sector_size - 1) // sector_size
    if location == 1:
        valid = 2 <= entries_lba and entries_lba + table_sectors <= first
    else:
        valid = last < entries_lba and entries_lba + table_sectors <= location
    if not valid:
        raise ValueError('GPT entry table overlaps headers or usable sectors')
    entries = read_at(stream, entries_lba * sector_size, count * entry_size)
    if zlib.crc32(entries) != entries_crc:
        raise ValueError('GPT entry-array CRC mismatch')
    return dict(first=first, last=last, guid=guid, count=count, entry_size=entry_size, entries=entries)


def inspect(stream, sector_size, partition=None):
    if sector_size not in (512, 4096):
        raise ValueError('logical sector size must be explicitly 512 or 4096')
    size = stream.seek(0, 2)
    if size % sector_size or size < 6 * sector_size:
        raise ValueError('expected a complete raw disk image with sector-aligned size')
    sectors = size // sector_size
    mbr = read_at(stream, 0, 512)
    if mbr[510:512] != b'\x55\xaa' or not any(mbr[446 + 16*i + 4] == 0xee for i in range(4)):
        raise ValueError('missing protective GPT MBR')
    primary = read_table(stream, sector_size, sectors, 1)
    backup = read_table(stream, sector_size, sectors, sectors - 1)
    if primary != backup:
        raise ValueError('primary and backup GPT metadata disagree')
    partitions, guids = [], set()
    for index in range(primary['count']):
        off = index * primary['entry_size']
        row = primary['entries'][off:off + primary['entry_size']]
        if row[:16] == bytes(16):
            continue
        guid = str(uuid.UUID(bytes_le=row[16:32]))
        if row[16:32] == bytes(16) or guid in guids:
            raise ValueError('zero or duplicate partition UUID')
        guids.add(guid)
        first, last, attributes = struct.unpack_from('<3Q', row, 32)
        if not primary['first'] <= first <= last <= primary['last']:
            raise ValueError('partition exceeds GPT usable range')
        label = row[56:128].decode('utf-16-le').split('\0', 1)[0]
        partitions.append(dict(gpt_slot=index + 1, label=label, uuid=guid,
                               type_uuid=str(uuid.UUID(bytes_le=row[:16])),
                               first_lba=first, last_lba=last, attributes=attributes,
                               offset_bytes=first * sector_size,
                               size_bytes=(last - first + 1) * sector_size,
                               start_aligned_4k=(first * sector_size) % 4096 == 0))
    ordered = sorted(partitions, key=lambda p: p['first_lba'])
    if any(a['last_lba'] >= b['first_lba'] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('overlapping GPT partitions')
    selected = None
    if partition is not None:
        matches = [p for p in partitions if p['label'] == partition]
        if len(matches) != 1:
            raise ValueError(f'partition label {partition!r} must match exactly once; found {len(matches)}')
        selected = matches[0]
    return dict(schema_version=1, hardware_verified=False, disk_size_bytes=size,
                logical_sector_size=sector_size, disk_uuid=str(uuid.UUID(bytes_le=primary['guid'])),
                primary_and_backup_verified=True, partitions=partitions, selected_partition=selected)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image', help='saved full raw disk image, not a partition image or Android sparse image')
    ap.add_argument('--sector-size', required=True, type=int, choices=(512, 4096))
    ap.add_argument('--partition', default='userdata', help='exact unique GPT label to inspect')
    args = ap.parse_args()
    try:
        with regular_file(args.image) as stream:
            report = inspect(stream, args.sector_size, args.partition)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
