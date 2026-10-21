#!/usr/bin/env python3
"""Inventory a single saved, merged Flattened Device Tree (v17) as JSON.

No device access, overlay application, RAM selection, ADT generation or writes.
The reported values describe the input file, not verified hardware ownership.
"""
import argparse
from dataclasses import dataclass, field
import hashlib
import json
import struct

from evidence_io import regular_file

MAX_SIZE = 16 << 20


@dataclass
class Node:
    path: str
    parent: object = None
    props: dict = field(default_factory=dict)


def string_list(value):
    if not value or not value.endswith(b'\0'):
        raise ValueError('invalid FDT string list')
    return value[:-1].decode('utf-8').split('\0')


def scalar(value):
    if len(value) != 4:
        raise ValueError('expected one 32-bit FDT cell')
    return int.from_bytes(value, 'big')


def cell_count(node, key, default):
    value = scalar(node.props[key]) if key in node.props else default
    if value not in (0, 1, 2):
        raise ValueError(f'{node.path}: unsupported {key}={value}')
    return value


def reg_ranges(node, prop='reg'):
    parent = node.parent
    if parent is None:
        raise ValueError('root has no parent address space')
    ac, sc = cell_count(parent, '#address-cells', 2), cell_count(parent, '#size-cells', 1)
    if not ac:
        raise ValueError(f'{node.path}: zero address cells')
    step = 4 * (ac + sc)
    raw = node.props[prop]
    if not raw or len(raw) % step:
        raise ValueError(f'{node.path}: incomplete {prop} tuple')
    result = []
    for off in range(0, len(raw), step):
        start = int.from_bytes(raw[off:off + 4*ac], 'big')
        size = int.from_bytes(raw[off + 4*ac:off + step], 'big')
        if start + size > 1 << 64:
            raise ValueError(f'{node.path}: address range overflows')
        result.append({'address': start, 'size': size})
    return result


def parse(blob):
    if len(blob) < 40 or len(blob) > MAX_SIZE:
        raise ValueError('DTB is truncated or exceeds the 16 MiB limit')
    magic, total, so, names, ro, version, compatible, _, ns, ss = struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or version != 17 or compatible not in (16, 17):
        raise ValueError('expected one raw FDT v17 blob')
    if total != len(blob) or so % 4 or ro % 8 or ss % 4 or ss < 12:
        raise ValueError('invalid FDT size or block alignment; concatenated blobs are not accepted')
    blocks = [(0, 40), (so, so + ss), (names, names + ns)]
    if any(a < 0 or b > total or a > b for a, b in blocks):
        raise ValueError('FDT block exceeds file')
    reservations, pos = [], ro
    while True:
        if pos < 40 or pos + 16 > total or any(pos < b and pos + 16 > a for a, b in blocks):
            raise ValueError('invalid or unterminated reservation map')
        address, size = struct.unpack_from('>QQ', blob, pos)
        pos += 16
        if not address and not size:
            break
        if not size or address + size > 1 << 64:
            raise ValueError('invalid FDT reservation')
        reservations.append({'address': address, 'size': size})
    blocks.append((ro, pos))
    blocks.sort()
    if any(a[1] > b[0] for a, b in zip(blocks, blocks[1:])):
        raise ValueError('overlapping FDT blocks')
    nodes, stack, paths = [], [], set()
    pos, end = so, so + ss
    while pos + 4 <= end:
        token = scalar(blob[pos:pos + 4])
        pos += 4
        if token == 1:
            nul = blob.find(b'\0', pos, end)
            if nul < 0 or nul - pos > 1024:
                raise ValueError('invalid node name')
            name = blob[pos:nul].decode('ascii')
            pos = (nul + 4) & ~3
            if '/' in name or (not stack and (nodes or name)) or (stack and not name):
                raise ValueError('invalid root or node name')
            path = (stack[-1].path.rstrip('/') + '/' + name) if stack else '/'
            if path in paths or len(stack) >= 128 or len(nodes) >= 65536:
                raise ValueError('duplicate node or excessive tree size/depth')
            node = Node(path, stack[-1] if stack else None)
            nodes.append(node)
            paths.add(path)
            stack.append(node)
        elif token == 2:
            if not stack:
                raise ValueError('unbalanced END_NODE')
            stack.pop()
        elif token == 3:
            if not stack or pos + 8 > end:
                raise ValueError('property outside node or truncated property')
            size, nameoff = struct.unpack_from('>II', blob, pos)
            pos += 8
            nul = blob.find(b'\0', names + nameoff, names + ns) if nameoff < ns else -1
            if nul < 0 or pos + size > end or ((pos + size + 3) & ~3) > end:
                raise ValueError('invalid property bounds or string offset')
            key = blob[names + nameoff:nul].decode('ascii')
            if not key or key in stack[-1].props:
                raise ValueError('empty or duplicate property')
            stack[-1].props[key] = blob[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack or not nodes or any(blob[pos:end]):
                raise ValueError('incomplete tree or data after FDT_END')
            return nodes, reservations
        else:
            raise ValueError(f'unknown FDT token {token}')
    raise ValueError('missing FDT_END')


def inventory(blob):
    nodes, reservations = parse(blob)
    if any(n.path.startswith('/fragment@') or n.path in ('/__fixups__', '/__local_fixups__') for n in nodes):
        raise ValueError('overlay is not a merged hardware tree; apply the correct overlays externally first')
    root = nodes[0]
    report = dict(schema_version=1, sha256=hashlib.sha256(blob).hexdigest(),
                  hardware_verified=False, model=string_list(root.props['model']) if 'model' in root.props else [],
                  compatible=string_list(root.props['compatible']) if 'compatible' in root.props else [],
                  memory=[], reservations=reservations, reserved_memory=[], devices=[], issues=[])
    for n in nodes[1:]:
        props = n.props
        status = string_list(props['status'])[0] if 'status' in props else 'okay'
        comp = string_list(props['compatible']) if 'compatible' in props else []
        is_memory = n.parent.path == '/' and (props.get('device_type') == b'memory\0' or n.path.startswith('/memory@'))
        is_reserved = n.parent.path == '/reserved-memory'
        interesting = ('gic', 'dw-mshc', 'decon', 'dsim', 'framebuffer', 'sec_ts', 'mms', 'zinitix', 'i2c', 'cortex-')
        is_device = any(key in ' '.join(comp + [n.path.rsplit('/', 1)[-1]]).lower() for key in interesting)
        if not (is_memory or is_reserved or is_device):
            continue
        enabled = status in ('okay', 'ok')
        parent = n.parent
        while parent is not None:
            if 'status' in parent.props:
                enabled &= string_list(parent.props['status'])[0] in ('okay', 'ok')
            parent = parent.parent
        item = dict(path=n.path, status=status, enabled_with_ancestors=bool(enabled), compatible=comp)
        if 'reg' in props:
            item['reg'] = reg_ranges(n)
            # Bus-relative addresses are deliberately not translated to MMIO.
            item['address_space'] = n.parent.path
        if is_memory:
            if 'reg' not in item:
                raise ValueError(f'{n.path}: memory has no reg')
            report['memory'].append(item)
            if any(r['size'] == 0 for r in item['reg']):
                report['issues'].append(f'{n.path}: zero-size bank is not evidence of usable RAM')
        if is_reserved:
            item['dynamic'] = 'reg' not in props and 'size' in props
            item['no_map'] = 'no-map' in props
            if item['dynamic']:
                raw = props['size']
                if len(raw) != 4 * cell_count(n.parent, '#size-cells', 1):
                    raise ValueError(f'{n.path}: invalid dynamic reservation size')
                item['requested_size'] = int.from_bytes(raw, 'big')
                report['issues'].append(f'{n.path}: dynamic reservation has no resolved physical address')
            if n.parent.props.get('ranges'):
                report['issues'].append(f'{n.path}: non-identity reserved-memory address translation')
            report['reserved_memory'].append(item)
        if is_device:
            if 'width' in props or 'height' in props or 'stride' in props:
                item['geometry'] = {key: scalar(props[key]) for key in ('width', 'height', 'stride') if key in props}
            if 'format' in props:
                item['format'] = string_list(props['format'])
            report['devices'].append(item)
            if not comp and ('mms' in n.path or 'touchscreen' in n.path):
                report['issues'].append(f'{n.path}: touchscreen-like node has no compatible; controller is unresolved')
    if not report['memory']:
        report['issues'].append('no root memory bank was found')
    report['issues'].append('no RAM window, physical scanout or boot profile is authorized by this inventory')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dtb', help='one raw merged DTB saved as a regular file')
    args = ap.parse_args()
    try:
        with regular_file(args.dtb) as stream:
            report = inventory(stream.read(MAX_SIZE + 1))
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
