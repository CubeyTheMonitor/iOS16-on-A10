"""Exercise the freestanding C validators; fixtures are not phone addresses."""
import json
import os
from pathlib import Path
import random
import shlex
import struct
import sys
import subprocess
import tempfile
import unittest

from test_evidence import cells, dtb, example_tree
from test_host import sample_payload

ROOT = Path(__file__).resolve().parents[1]


def tree(reg=None, extra=(), root_extra=(), ac=2, sc=1):
    if reg is None:
        reg = cells(0, 0x4000000, 0x100000)
    return ('', [('#address-cells', cells(ac)), ('#size-cells', cells(sc)),
                 *root_extra], [('memory@4000000', [('reg', reg)], []), *extra])


def reserved(children, props=()):
    return ('reserved-memory', [('#address-cells', cells(2)), ('#size-cells', cells(1)),
                               ('ranges', b''), *props], children)


class RuntimeMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.binary = str(Path(cls.tmp.name) / 'check')
        # Non-PIE avoids random ASan shadow-address collisions on Linux hosts.
        subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11',
                        '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                        *(['-fno-pie', '-no-pie'] if sys.platform.startswith('linux') else []),
                        str(ROOT / 'tests/loader_check.c'),
                        '-o', cls.binary], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, blob, *args, mode='fdt'):
        path = Path(self.tmp.name) / 'fixture.bin'
        path.write_bytes(blob)
        result = subprocess.run([self.binary, mode, str(path), *map(str, args)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stderr, result.stderr)
        r = json.loads(result.stdout)
        if r['error'] and mode == 'fdt':
            self.assertEqual(r['valid'], 0)
        return r

    def test_banks_zero_banks_and_full_window(self):
        blob = dtb(tree(cells(0, 0x4000000, 0x100000, 8, 0x80000000, 0)))
        r = self.check(blob, 0x4000000, 0x100000)
        self.assertEqual((r['error'], r['banks'], r['zero'], r['window']), (0, 1, 1, 0))
        self.assertEqual(self.check(blob, 0x40ff000, 0x2000)['window'], 8)
        self.assertEqual(self.check(blob, 0x880000000, 1)['window'], 8)
        self.assertEqual(self.check(blob, 0x4000000, 0)['window'], 3)
        self.assertEqual(self.check(blob, 2**64-4, 8)['window'], 6)

    def test_one_cell_and_two_cell_sizes(self):
        for ac, sc, reg in ((1, 1, cells(0x4000000, 0x100000)),
                            (2, 2, cells(0, 0x4000000, 0, 0x100000))):
            self.assertEqual(self.check(dtb(tree(reg, ac=ac, sc=sc)), 0x4000000, 0x1000)['window'], 0)
        self.assertEqual(self.check(dtb(tree(cells(1, 2), ac=3)))['error'], 4)

    def test_adjacent_banks_cannot_form_one_window(self):
        blob = dtb(tree(cells(0, 0x4000000, 0x1000, 0, 0x4001000, 0x1000)))
        self.assertEqual(self.check(blob, 0x4000000, 0x2000)['window'], 8)

    def test_fixed_reserved_initrd_and_protected_buffers(self):
        children = [('fb@4008000', [('reg', cells(0, 0x4008000, 0x1000)),
                                  ('no-map', b''), ('status', b'disabled\0')], [])]
        chosen = ('chosen', [('linux,initrd-start', cells(0, 0x400a000)),
                             ('linux,initrd-end', cells(0, 0x400b000))], [])
        blob = dtb(tree(extra=[reserved(children), chosen]), [(0x400c000, 0x1000)])
        for addr in (0x4008000, 0x400a000, 0x400c000):
            self.assertEqual(self.check(blob, addr, 1)['window'], 9)
        self.assertEqual(self.check(blob, 0x4000000, 0x1000, 0x4001000, 1)['window'], 0)
        self.assertEqual(self.check(blob, 0x4000000, 0x2000, 0x4001000, 1)['window'], 10)
        self.assertEqual(self.check(blob, 0x4000000, 1, 2**64-1, 2)['window'], 6)
        self.assertEqual(self.check(blob)['reserved'], 3)

    def test_unresolved_pools_cannot_be_ignored(self):
        for props in ([('size', cells(0x1000))], [], [('reg', cells(0, 0, 0))]):
            blob = dtb(tree(extra=[reserved([('pool', props, [])])]))
            r = self.check(blob, 0x4000000, 0x1000)
            self.assertEqual((r['error'], r['unresolved'], r['window']), (0, 1, 11))

    def test_actual_shaped_tree_and_disabled_memory(self):
        r = self.check(dtb(example_tree()), 0x40000000, 0x1000)
        self.assertEqual((r['banks'], r['zero'], r['unresolved'], r['window']), (1, 1, 1, 11))
        for root_props, bank_props in (([('status', b'disabled\0')], []),
                                      ([], [('status', b'disabled\0')])):
            t = tree(root_extra=root_props)
            t[2][0][1].extend(bank_props)
            self.assertEqual(self.check(dtb(t))['error'], 7)

    def test_malformed_and_unsupported_maps(self):
        malformed = [
            (tree(cells(0, 0x4000000)), 3),
            (tree(cells(0xffffffff, 0xfffffff0, 0x1000)), 6),
            (tree(cells(0, 0x4000000, 0x2000, 0, 0x4001000, 0x1000)), 3),
            (tree(extra=[('fragment@0', [], [])]), 12),
            (tree(root_extra=[('linux,usable-memory-range', cells(0, 1, 2))]), 4),
            (tree(root_extra=[('#address-cells', cells(2))]), 3),
            (tree(extra=[('chosen', [('linux,initrd-start', cells(0x4000000))], [])]), 3),
            (tree(extra=[('chosen', [('linux,initrd-start', cells(20)), ('linux,initrd-end', cells(10))], [])]), 3),
            (tree(extra=[('reserved-memory', [], [])]), 4),
            (tree(extra=[reserved([('pool', [('reg', cells(0, 1, 2))], [('nested', [], [])])])]), 4),
            (tree(extra=[('reserved-memory', [('ranges', cells(1))], [])]), 4),
            (tree(extra=[reserved([('pool', [('size', cells(0, 0x1000))], [])])]), 3),
        ]
        for t, error in malformed:
            with self.subTest(tree=t):
                self.assertEqual(self.check(dtb(t))['error'], error)

    def test_resource_limits(self):
        self.assertEqual(self.check(dtb(tree(cells(*sum(([0, i*4096, 4096] for i in range(17)), [])))))['error'], 5)
        self.assertEqual(self.check(dtb(tree(), [(i*4096, 1) for i in range(129)]))['error'], 5)
        child = ('leaf', [], [])
        for i in range(32):
            child = (f'n{i}', [], [child])
        self.assertEqual(self.check(dtb(tree(extra=[child])))['error'], 5)

    def test_truncations_and_corrupt_offsets_are_bounded(self):
        blob = dtb(example_tree(), [(0x40001000, 0x1000)])
        for n in list(range(41)) + list(range(41, len(blob), 17)):
            self.assertNotEqual(self.check(blob[:n])['error'], 0)
        for offset, value in ((8, 0xfffffff0), (12, 40), (16, 41), (32, 0xffffffff),
                              (36, 0xffffffff), (20, 16), (0, 0)):
            bad = bytearray(blob)
            struct.pack_into('>I', bad, offset, value)
            self.assertNotEqual(self.check(bad)['error'], 0)
        rng = random.Random(7884)
        for _ in range(64):
            bad = bytearray(blob)
            pos = rng.randrange(len(blob))
            bad[pos] ^= rng.randrange(1, 256)
            self.check(bad)  # Either valid or rejected, never an out-of-bounds read.

    def test_payload_validated_placement(self):
        r = self.check(sample_payload(), mode='payload')
        self.assertEqual(r, dict(error=0, adt=0x4004000, args=0x4008000,
                                 top=0x400c000, entry=0x4000000))

    def test_payload_segments_cannot_overlap(self):
        blob = sample_payload()
        blob.extend(bytes(128))
        struct.pack_into('<I', blob, 12, 2)
        struct.pack_into('<Q', blob, 32, 864)  # ADT beyond both source segments
        struct.pack_into('<4Q', blob, 0x2a8, 0x2000000, 32, 752, 9)
        struct.pack_into('<4Q', blob, 0x2c8, 0x2000100, 32, 800, 9)
        self.assertEqual(self.check(blob, mode='payload')['error'], 0)
        for offset, value in ((0x2c8, 0x2000018), (0x2c8 + 16, 760)):
            bad = bytearray(blob)
            struct.pack_into('<Q', bad, offset, value)
            self.assertEqual(self.check(bad, mode='payload')['error'], 3)

    def test_payload_bounds_overlap_entry_and_command(self):
        for n in (0, 8, 679, 680, 700, 719, 736, 740):
            self.assertNotEqual(self.check(sample_payload()[:n], mode='payload')['error'], 0)
        for offset, value, error in ((8, 2, 1), (12, 129, 1), (56, 1, 2),
                                      (64, 0x8000, 2), (40, 0xffffffff, 2),
                                      (24, 0x200000c, 4), (24, 0x2000001, 4),
                                      (0x2a8+16, 736, 3), (0x2a8+24, 33, 2)):
            bad = sample_payload()
            struct.pack_into('<I' if offset in (8, 12) else '<Q', bad, offset, value)
            self.assertEqual(self.check(bad, mode='payload')['error'], error, (offset, value))
        for count, expected in ((581, 0), (582, 5), (608, 5)):
            bad = sample_payload()
            bad[72:72+count] = b'x' * count
            self.assertEqual(self.check(bad, mode='payload')['error'], expected)
