"""Independent synthetic DTB/GPT fixtures; none describe verified A10 hardware."""
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import inspect_dtb
import inspect_gpt
from evidence_io import regular_file


def cells(*values):
    return struct.pack('>' + 'I'*len(values), *values)


def dtb(tree, reservations=()):
    names = bytearray()
    offsets = {}

    def encode(node):
        name, props, children = node
        body = cells(1) + name.encode() + b'\0'
        body += bytes(-len(body) % 4)
        for key, value in props:
            if key not in offsets:
                offsets[key] = len(names)
                names.extend(key.encode() + b'\0')
            body += cells(3, len(value), offsets[key]) + value + bytes(-len(value) % 4)
        for child in children:
            body += encode(child)
        return body + cells(2)

    body = encode(tree) + cells(9)
    reserve = b''.join(struct.pack('>QQ', a, s) for a, s in reservations) + bytes(16)
    so = 40 + len(reserve)
    no = so + len(body)
    return struct.pack('>10I', 0xd00dfeed, no + len(names), so, no, 40, 17, 16, 0,
                       len(names), len(body)) + reserve + body + names


def example_tree():
    return ('', [('#address-cells', cells(2)), ('#size-cells', cells(1)),
                 ('model', b'Synthetic SM-A105G evidence\0')], [
        ('memory@40000000', [('device_type', b'memory\0'), ('reg', cells(0, 0x40000000, 0x1000000))], []),
        ('memory@880000000', [('reg', cells(8, 0x80000000, 0))], []),
        ('reserved-memory', [('#address-cells', cells(2)), ('#size-cells', cells(1)), ('ranges', b'')], [
            ('framebuffer@40800000', [('reg', cells(0, 0x40800000, 0x100000)), ('no-map', b'')], []),
            ('dynamic', [('size', cells(0x20000))], []),
        ]),
        ('cpus', [('#address-cells', cells(2)), ('#size-cells', cells(0))], [
            ('cpu@1', [('compatible', b'arm,cortex-a73\0'), ('reg', cells(0, 1))], []),
        ]),
        ('hsi2c@12340000', [('#address-cells', cells(1)), ('#size-cells', cells(0)),
                            ('compatible', b'samsung,exynos5-hsi2c\0'), ('reg', cells(0, 0x12340000, 0x1000))], [
            ('touchscreen@48', [('compatible', b'sec,sec_ts\0'), ('reg', cells(0x48))], []),
            ('mms_ts@48', [('status', b'okay\0')], []),
        ]),
    ])


def disk_image(sector=512, partitions=None):
    if partitions is None:
        partitions = [('userdata', 8, 16)]
    count, total = 4, 100
    entries = bytearray(count * 128)
    for i, (label, first, last) in enumerate(partitions):
        row = (uuid.UUID(int=2).bytes_le + uuid.UUID(int=i + 10).bytes_le
               + struct.pack('<3Q', first, last, 0) + label.encode('utf-16-le').ljust(72, b'\0'))
        entries[i*128:(i+1)*128] = row
    disk = bytearray(total * sector)
    disk[446 + 4] = 0xee
    disk[510:512] = b'\x55\xaa'
    for current, backup, table in ((1, 99, 2), (99, 1, 98)):
        header = bytearray(struct.pack('<8s4I4Q16sQ3I', b'EFI PART', 0x10000, 92, 0, 0,
                                       current, backup, 3, 97, uuid.UUID(int=1).bytes_le,
                                       table, count, 128, zlib.crc32(entries)))
        struct.pack_into('<I', header, 16, zlib.crc32(header))
        disk[current*sector:current*sector+92] = header
        disk[table*sector:table*sector+len(entries)] = entries
    return disk


def update_header_crc(disk, offset):
    size = struct.unpack_from('<I', disk, offset + 12)[0]
    struct.pack_into('<I', disk, offset + 16, 0)
    struct.pack_into('<I', disk, offset + 16, zlib.crc32(disk[offset:offset+size]))


class DeviceTreeTests(unittest.TestCase):
    def test_memory_reservations_and_bus_addresses(self):
        blob = dtb(example_tree(), [(0x40001000, 0x1000)])
        r = inspect_dtb.inventory(blob)
        self.assertFalse(r['hardware_verified'])
        self.assertEqual(r['memory'][0]['reg'], [{'address': 0x40000000, 'size': 0x1000000}])
        self.assertEqual(r['memory'][1]['reg'], [{'address': 0x880000000, 'size': 0}])
        self.assertEqual(r['reservations'], [{'address': 0x40001000, 'size': 0x1000}])
        self.assertTrue(r['reserved_memory'][0]['no_map'])
        self.assertEqual(r['reserved_memory'][1]['requested_size'], 0x20000)
        touch = next(n for n in r['devices'] if n['path'].endswith('/touchscreen@48'))
        self.assertEqual(touch['reg'], [{'address': 0x48, 'size': 0}])
        self.assertEqual(touch['address_space'], '/hsi2c@12340000')
        self.assertTrue(any('no compatible' in s for s in r['issues']))
        self.assertTrue(any('zero-size' in s for s in r['issues']))
        self.assertTrue(any('dynamic reservation' in s for s in r['issues']))

    def test_one_cell_addresses_and_disabled_memory(self):
        tree = ('', [('#address-cells', cells(1)), ('#size-cells', cells(1))], [
            ('memory@1000', [('reg', cells(0x1000, 0x10000)), ('status', b'disabled\0')], [])])
        r = inspect_dtb.inventory(dtb(tree))
        self.assertEqual(r['memory'][0]['status'], 'disabled')
        self.assertFalse(r['memory'][0]['enabled_with_ancestors'])
        self.assertEqual(r['memory'][0]['reg'][0]['address'], 0x1000)

    def test_disabled_bus_and_unrelated_three_cell_bus(self):
        tree = example_tree()
        tree[2][-1][1].append(('status', b'disabled\0'))
        tree[2].append(('pci', [('#address-cells', cells(3)), ('#size-cells', cells(2))], [
            ('irrelevant@0', [('reg', cells(0, 0, 0, 0, 0))], [])]))
        r = inspect_dtb.inventory(dtb(tree))
        touch = next(n for n in r['devices'] if n['path'].endswith('/touchscreen@48'))
        self.assertEqual(touch['status'], 'okay')
        self.assertFalse(touch['enabled_with_ancestors'])

    def test_overlay_is_not_hardware_evidence(self):
        for child in ('fragment@0', '__fixups__', '__local_fixups__'):
            with self.subTest(child=child), self.assertRaisesRegex(ValueError, 'overlay'):
                inspect_dtb.inventory(dtb(('', [], [(child, [], [])])))

    def test_malformed_headers_and_reservation_maps(self):
        original = dtb(example_tree())
        cases = [(0, 0), (4, len(original)-1), (8, 41), (12, len(original)+4),
                 (16, 0), (16, 48), (20, 16), (32, 0xffffffff), (36, 0xffffffff)]
        for offset, value in cases:
            b = bytearray(original)
            struct.pack_into('>I', b, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect_dtb.parse(b)
        for b in (b'', original[:40], original + b'extra'):
            with self.assertRaises(ValueError):
                inspect_dtb.parse(b)

    def test_invalid_properties_nodes_and_depth(self):
        for tree in [('', [('x', b'a'), ('x', b'b')], []),
                     ('', [], [('same', [], []), ('same', [], [])]),
                     ('bad-root', [], []), ('', [], [('bad/name', [], [])])]:
            with self.assertRaises(ValueError):
                inspect_dtb.parse(dtb(tree))
        tree = ('leaf', [], [])
        for i in range(128):
            tree = (f'n{i}', [], [tree])
        with self.assertRaisesRegex(ValueError, 'depth'):
            inspect_dtb.parse(dtb(('', [], [tree])))
        b = bytearray(dtb(example_tree()))
        so = struct.unpack_from('>I', b, 8)[0]
        struct.pack_into('>I', b, so + 12, 0xffffffff)  # first property's length
        with self.assertRaises(ValueError):
            inspect_dtb.parse(b)

    def test_memory_tuple_and_overflow_errors(self):
        for value in (cells(0, 1), cells(0xffffffff, 0xfffffff0, 0x1000)):
            tree = ('', [('#address-cells', cells(2)), ('#size-cells', cells(1))], [
                ('memory@1', [('reg', value)], [])])
            with self.assertRaises(ValueError):
                inspect_dtb.inventory(dtb(tree))


class GPTTests(unittest.TestCase):
    def test_both_sector_sizes_and_partition_discovery(self):
        for sector in (512, 4096):
            r = inspect_gpt.inspect(io.BytesIO(disk_image(sector)), sector, 'userdata')
            self.assertTrue(r['primary_and_backup_verified'])
            self.assertFalse(r['hardware_verified'])
            p = r['selected_partition']
            self.assertEqual((p['gpt_slot'], p['first_lba'], p['last_lba']), (1, 8, 16))
            self.assertEqual((p['offset_bytes'], p['size_bytes']), (8*sector, 9*sector))
            self.assertTrue(p['start_aligned_4k'])

    def test_missing_duplicate_labels_and_overlapping_partitions(self):
        cases = [([('boot', 8, 16)], 'match exactly once'),
                 ([('userdata', 8, 16), ('userdata', 24, 32)], 'match exactly once'),
                 ([('userdata', 8, 16), ('other', 16, 24)], 'overlapping'),
                 ([('userdata', 2, 16)], 'usable'), ([('userdata', 8, 98)], 'usable')]
        for entries, error in cases:
            with self.subTest(entries=entries), self.assertRaisesRegex(ValueError, error):
                inspect_gpt.inspect(io.BytesIO(disk_image(partitions=entries)), 512, 'userdata')

    def test_primary_backup_and_entry_crcs(self):
        for offset in (512 + 48, 2*512 + 127, 99*512 + 48, 98*512 + 127):
            disk = disk_image()
            disk[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'CRC'):
                inspect_gpt.inspect(io.BytesIO(disk), 512)

    def test_consistent_crcs_do_not_hide_inconsistent_disk_guids(self):
        disk = disk_image()
        disk[99*512 + 56] ^= 1
        update_header_crc(disk, 99*512)
        with self.assertRaisesRegex(ValueError, 'disagree'):
            inspect_gpt.inspect(io.BytesIO(disk), 512)

    def test_duplicate_or_zero_partition_uuids_with_valid_crcs(self):
        for duplicate in (True, False):
            disk = disk_image(partitions=[('userdata', 8, 16), ('other', 24, 32)])
            entries = bytearray(disk[2*512:3*512])
            entries[144:160] = entries[16:32] if duplicate else bytes(16)
            for header, table in ((512, 2*512), (99*512, 98*512)):
                disk[table:table+len(entries)] = entries
                struct.pack_into('<I', disk, header+88, zlib.crc32(entries))
                update_header_crc(disk, header)
            with self.assertRaisesRegex(ValueError, 'partition UUID'):
                inspect_gpt.inspect(io.BytesIO(disk), 512)

    def test_partition_contents_are_not_read(self):
        class RecordedReads(io.BytesIO):
            def read(self, size=-1):
                reads.append((self.tell(), size))
                return super().read(size)
        reads = []
        inspect_gpt.inspect(RecordedReads(disk_image()), 512, 'userdata')
        self.assertEqual(set(reads), {(0, 512), (512, 512), (1024, 512),
                                     (99*512, 512), (98*512, 512)})

    def test_invalid_header_ranges_and_excessive_table(self):
        for offset, fmt, value in ((24, '<Q', 2), (32, '<Q', 98),
                                   (72, '<Q', 3), (80, '<I', 0xffffffff),
                                   (84, '<I', 129)):
            disk = disk_image()
            struct.pack_into(fmt, disk, 512 + offset, value)
            update_header_crc(disk, 512)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect_gpt.inspect(io.BytesIO(disk), 512)

    def test_full_image_and_explicit_sector_size_required(self):
        for data, sector in ((b'', 512), (disk_image()[:-1], 512),
                              (disk_image(), 1024), (disk_image(), 4096)):
            with self.assertRaises(ValueError):
                inspect_gpt.inspect(io.BytesIO(data), sector)

    def test_existing_qemu_disk_builder_produces_matching_guids(self):
        with tempfile.TemporaryDirectory() as d:
            root, disk = Path(d)/'root.img', Path(d)/'disk.img'
            root.write_bytes(b'offline fixture')
            subprocess.run([sys.executable, str(ROOT/'tools/mkdisk.py'), str(root), str(disk)],
                           capture_output=True, check=True)
            with regular_file(disk) as stream:
                r = inspect_gpt.inspect(stream, 512, 'userdata')
            self.assertEqual(r['selected_partition']['offset_bytes'], 1 << 20)


class EvidenceCLITests(unittest.TestCase):
    def test_cli_json_and_input_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            for tool, data, args in [('inspect_dtb.py', dtb(example_tree()), []),
                                     ('inspect_gpt.py', disk_image(), ['--sector-size', '512'])]:
                path = Path(d)/'evidence.bin'
                path.write_bytes(data)
                r = subprocess.run([sys.executable, str(ROOT/'tools'/tool), str(path), *args],
                                   capture_output=True, text=True, check=True,
                                   env=dict(os.environ, PATH=''))
                self.assertFalse(json.loads(r.stdout)['hardware_verified'])
                self.assertEqual(path.read_bytes(), data)

    def test_non_regular_files_rejected_before_read(self):
        for tool, args in [('inspect_dtb.py', []), ('inspect_gpt.py', ['--sector-size', '512'])]:
            r = subprocess.run([sys.executable, str(ROOT/'tools'/tool), '/dev/null', *args],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn('regular file', r.stderr)
        with tempfile.TemporaryDirectory() as d:
            fifo = Path(d)/'fifo'
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, 'regular file'):
                with regular_file(fifo):
                    self.fail('FIFO must not be opened')


if __name__ == '__main__':
    unittest.main()
