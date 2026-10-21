"""Offline tests; synthetic addresses are not a proposed phone memory map."""
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'loader'))
import adt
import board
import mkadt
import mkpayload
import pack
from payload_format import validate

spec = importlib.util.spec_from_file_location('qemu_a40', ROOT / 'tools/qemu-a40.py')
qemu_a40 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qemu_a40)


def sample_payload():
    """One odd-length segment in a small synthetic RAM window."""
    b = bytearray(752)
    struct.pack_into('<8sII7Q', b, 0, b'SWEETXNU', 1, 1,
                     0x2000000, 0x2000000, 736, 8, 0x2004000, 0x4000000, 0x10000)
    struct.pack_into('<4Q', b, 0x2a8, 0x2000000, 32, 720, 9)
    b[720:729] = b'123456789'
    b[736:744] = b'ADT-test'
    return b


class PayloadTests(unittest.TestCase):
    def test_valid_odd_size_and_qemu_placement(self):
        b = sample_payload()
        validate(b)
        phys, image, args, entry = qemu_a40.build_image(b)
        self.assertEqual((phys, entry), (0x4000000, 0x4000000))
        self.assertEqual(image[:32], b'123456789' + bytes(23))
        self.assertEqual(image[0x4000:0x4008], b'ADT-test')
        self.assertEqual(args, phys + 0x8000)

    def test_malformed_ranges(self):
        cases = [
            (0x0, '<8s', b'BADMAGIC'), (8, '<I', 2),
            (12, '<I', 0xffffffff), (0x20, '<Q', 737),
            (0x28, '<Q', 1000), (0x30, '<Q', 0x2014000),
            (0x38, '<Q', (1 << 64) - 0x4000),
            (0x40, '<Q', 0x8000),
            (0x18, '<Q', 0x2000100),
            (0x2a8, '<Q', 0x1ffffff),
            (0x2b0, '<Q', 8), (0x2b8, '<Q', 736),
            (0x2b8, '<Q', 744), (0x2c0, '<Q', 33),
        ]
        for off, fmt, value in cases:
            with self.subTest(offset=off, value=value):
                b = sample_payload()
                struct.pack_into(fmt, b, off, value)
                with self.assertRaises(ValueError):
                    validate(b)
        for b in (b'', sample_payload()[:700]):
            with self.assertRaises(ValueError):
                validate(b)

    def test_command_line_must_terminate(self):
        b = sample_payload()
        b[0x48:0x2a8] = b'x' * 608
        with self.assertRaisesRegex(ValueError, 'unterminated'):
            validate(b)

    def test_two_segments_cannot_overlap(self):
        for va, off in ((0x2000008, 800), (0x2000100, 720)):
            b = sample_payload() + bytes(128)
            struct.pack_into('<I', b, 12, 2)
            struct.pack_into('<Q', b, 0x20, 864)
            struct.pack_into('<4Q', b, 0x2c8, va, 32, off, 8)
            # Relocate the first segment away from the now larger table.
            struct.pack_into('<Q', b, 0x2b8, 776)
            if off == 720:
                struct.pack_into('<Q', b, 0x2b8, 800)
                struct.pack_into('<Q', b, 0x2d8, 800)
            with self.assertRaisesRegex(ValueError, 'overlapping'):
                validate(b)

    def test_builder_rejects_long_or_nul_command_line(self):
        # Minimal arm64 Mach-O with __TEXT and LC_UNIXTHREAD, no Apple assets.
        segment = struct.pack('<II16s4Q4I', 0x19, 72, b'__TEXT',
                              0x2000000, 0x4000, 0, 384, 7, 5, 0, 0)
        thread = bytearray(288)
        struct.pack_into('<4I', thread, 0, 5, 288, 6, 68)
        struct.pack_into('<Q', thread, 16 + 32 * 8, 0x2000000)
        macho = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 2, 360, 0, 0) + segment + thread
        tree = mkadt.node('device-tree', children=[mkadt.node('chosen', [
            ('dram-base', struct.pack('<Q', 0x4000000)),
            ('dram-size', struct.pack('<Q', 0x10000))])])
        with tempfile.TemporaryDirectory() as d:
            k, a = Path(d)/'kernel', Path(d)/'tree'
            k.write_bytes(macho)
            a.write_bytes(adt.serialize(tree))
            for cmd in ('x'*582, 'bad\0arg'):
                with self.assertRaises(ValueError):
                    mkpayload.build(k, a, cmd)
            blob, _ = mkpayload.build(k, a, 'x'*581)
            validate(blob)


class BoardAndHeaderTests(unittest.TestCase):
    def test_board_selection(self):
        for name in (None, '', 'a10', 'SM-A105', 'other'):
            with self.assertRaises(ValueError):
                board.require_supported_board(name)
        board.require_supported_board('a40')
        with self.assertRaises(ValueError):
            mkadt.build(board='a10', qemu=True)
        with self.assertRaises(ValueError):
            mkadt.build(board='a40', highmem=True)

    def test_explicit_a40_adt_roundtrip(self):
        with patch.object(mkadt, 'd22ap_product', return_value=None):
            tree = mkadt.build(seed=bytes(64), board='a40', qemu=True)
        parsed, _ = adt.parse(adt.serialize(tree))
        names = {c.name for c in parsed.children}
        self.assertIn('a40-virtio', names)
        self.assertNotIn('a40-touch', names)
        self.assertNotIn('a40-mmc', names)

    def test_rejected_commands_do_not_launch_adb_or_compiler(self):
        # An empty PATH makes accidentally invoking adb/clang detectable.
        env = dict(os.environ, BOARD='a10', PATH='')
        commands = [
            [sys.executable, 'tools/push-sync.py', 'missing.img'],
            [sys.executable, 'tools/pull-phone.py', 'missing.img'],
            ['/bin/bash', 'tools/flash-userdata.sh', 'missing.img'],
            ['/bin/bash', 'loader/build.sh', 'missing.img'],
        ]
        for cmd in commands:
            with self.subTest(cmd=cmd):
                r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('A10', r.stderr)
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d)/'out')
            for script, args in [('tools/mkadt.py', [out]),
                                 ('loader/pack.py', ['absent.o', out, '--like', 'absent.img'])]:
                r = subprocess.run([sys.executable, script, *args, '--board', 'a10'],
                                   cwd=ROOT, capture_output=True, text=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('no validated', r.stderr)
                self.assertFalse(Path(out).exists())

    def test_boot_header_validation_and_field_preservation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'boot.img'
            h = bytearray(1660)
            h[:8] = b'ANDROID!'
            struct.pack_into('<10I', h, 8, 0, 123, 0, 456, 0, 789, 321, 4096, 1, 99)
            struct.pack_into('<I', h, 1644, 1648)
            h[48:52] = b'A40\0'
            path.write_bytes(h)
            f = pack.read_like(path)
            self.assertEqual((f['kernel_addr'], f['ramdisk_addr'], f['page_size']), (123, 456, 4096))
            built = pack.build(b'code', pack.empty_ramdisk(), f)
            self.assertEqual(struct.unpack_from('<I', built, 12)[0], 123)
            self.assertEqual(built[4096:4100], b'code')
            for version, size in ((0, 1632), (1, 1648), (2, 1660)):
                struct.pack_into('<I', h, 40, version)
                struct.pack_into('<I', h, 1644, size)
                path.write_bytes(h[:size])
                pack.read_like(path)
                path.write_bytes(h[:size-1])
                with self.assertRaises(ValueError):
                    pack.read_like(path)
            for page in (0, 1024, 3000, 131072):
                struct.pack_into('<I', h, 36, page)
                path.write_bytes(h)
                with self.assertRaises(ValueError):
                    pack.read_like(path)


if __name__ == '__main__':
    unittest.main()
