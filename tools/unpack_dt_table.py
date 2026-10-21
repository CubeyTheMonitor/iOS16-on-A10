#!/usr/bin/env python3
"""Inspect/export FDT blobs from an uncompressed Android DT table v0 file.

Used for Samsung dt.img and dtbo.img after external LZ4 decompression. All
entries are preserved; no board selection, overlay application or flashing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from evidence_io import regular_file
from inspect_dtb import parse

MAX_SIZE = 128 << 20


def unpack(data):
    if not 32 <= len(data) <= MAX_SIZE:
        raise ValueError('DT table is truncated or exceeds 128 MiB')
    magic, total, header_size, entry_size, count, offset, page, version = struct.unpack_from('>8I', data)
    if magic != 0xd7b7ab1e or version != 0 or header_size != 32 or entry_size != 32:
        raise ValueError('expected uncompressed Android DT table v0 with 32-byte headers/entries')
    if not 32 <= total <= len(data) or not 0 < count <= 4096:
        raise ValueError('invalid DT table size or entry count')
    if offset < header_size or offset % 4 or offset + count * entry_size > total:
        raise ValueError('DT entry table exceeds declared container')
    if page < 512 or page > 65536 or page & (page - 1):
        raise ValueError('invalid DT container page size')
    metadata_end = offset + count * entry_size
    entries, blobs, spans = [], [], set()
    for index in range(count):
        size, start, ident, revision, *custom = struct.unpack_from('>8I', data, offset + index * entry_size)
        if size < 40 or start % 4 or start < metadata_end or start + size > total:
            raise ValueError(f'entry {index}: invalid DTB range')
        blob = data[start:start + size]
        nodes, _ = parse(blob)
        kind = 'overlay' if any(n.path.startswith('/fragment@') or n.path in
                                ('/__fixups__', '/__local_fixups__') for n in nodes) else 'base_or_merged'
        entries.append(dict(index=index, offset=start, size=size, id=ident,
                            revision=revision, custom=custom, kind=kind,
                            filename=f'entry-{index:04d}.dtb', sha256=hashlib.sha256(blob).hexdigest()))
        blobs.append(blob)
        spans.add((start, start + size))
    # Exact aliases are allowed; partial overlaps are malformed.
    ordered = sorted(spans)
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('DTB entry ranges partially overlap')
    manifest = dict(schema_version=1, hardware_verified=False,
                    sha256=hashlib.sha256(data).hexdigest(), file_size=len(data),
                    declared_size=total, trailing_bytes=len(data) - total,
                    table_version=version, container_page_size=page, entries=entries)
    return manifest, blobs


def export(directory, manifest, blobs):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    for entry, blob in zip(manifest['entries'], blobs):
        with (directory / entry['filename']).open('xb') as output:
            output.write(blob)
    with (directory / 'manifest.json').open('x') as output:
        json.dump(manifest, output, indent=2)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('image', help='one saved, uncompressed DT table image')
    ap.add_argument('--out-dir', help='new directory for all DTBs and a hash manifest; never overwrite')
    args = ap.parse_args()
    try:
        with regular_file(args.image) as stream:
            manifest, blobs = unpack(stream.read(MAX_SIZE + 1))
        if args.out_dir:
            export(args.out_dir, manifest, blobs)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
