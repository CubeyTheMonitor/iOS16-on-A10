"""Test the experimental A10 artifacts; synthetic RAM is not a phone map."""
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_host import ROOT, adt, mkadt
import mkadt_a10


class A10TargetTests(unittest.TestCase):
    def make_tree(self, **kwargs):
        with patch.object(mkadt, 'd22ap_product', return_value=None):
            root = mkadt_a10.build(0x4000000, 0x2000000, seed=bytes(64), **kwargs)
        return adt.parse(adt.serialize(root))[0]

    def test_ramdisk_target_has_one_a73_and_no_peripheral_input(self):
        root = self.make_tree()
        self.assertIn(b'samsung,a10\0', root.prop('compatible'))
        self.assertIn(b'D22AP\0', root.prop('compatible'))
        self.assertNotIn(b'samsung,a40\0', root.prop('compatible'))
        names = {c.name for c in root.children}
        self.assertTrue({'a40-touch', 'a40-keys', 'a40-mmc', 'sweet-ufs'}.isdisjoint(names))
        self.assertIn('exynos-platform', names)
        cpu = mkadt_a10.child(root, 'cpus').children
        self.assertEqual(len(cpu), 1)
        self.assertEqual(cpu[0].prop('reg'), bytes(4))
        chosen = mkadt_a10.child(root, 'chosen')
        self.assertEqual(struct.unpack('<Q', chosen.prop('dram-base'))[0], 0x4000000)
        self.assertEqual(struct.unpack('<Q', chosen.prop('dram-size'))[0], 0x2000000)
        fb = mkadt_a10.child(root, 'sweet-fbcon')
        self.assertEqual(struct.unpack('<I', fb.prop('width'))[0], 720)
        self.assertEqual(struct.unpack('<I', fb.prop('height'))[0], 1520)
        self.assertEqual(struct.unpack('<I', fb.prop('stride'))[0], 2880)
        display = mkadt_a10.child(mkadt_a10.child(root, 'arm-io'), 'disp0')
        self.assertEqual(display.prop('canvas-width'), fb.prop('width'))
        self.assertEqual(display.prop('canvas-height'), fb.prop('height'))
        self.assertEqual(fb.prop('trigger'), struct.pack('<QI', 0x14860070, 0x1281))

    def test_emmc_is_explicit_and_a40_builder_is_unchanged(self):
        root = self.make_tree(emmc=True)
        mmc = mkadt_a10.child(root, 'a40-mmc')
        self.assertEqual(struct.unpack('<QQ', mmc.prop('reg')), (0x13500000, 0x2000))
        with patch.object(mkadt, 'd22ap_product', return_value=None):
            a40 = mkadt.build(board='a40')
        fb = mkadt_a10.child(a40, 'sweet-fbcon')
        self.assertEqual(struct.unpack('<I', fb.prop('width'))[0], 1080)
        self.assertEqual(struct.unpack('<Q', mkadt_a10.child(a40, 'chosen').prop('dram-base'))[0], 0x880000000)

    def test_ram_must_be_explicit_aligned_and_avoid_framebuffer(self):
        for base, size in ((0, 0x4000), (1, 0x4000), (0x4000000, 0),
                           (0x4000000, 1), (0xec000000, 0x2000000),
                           (2**64-0x2000000, 0x4000000)):
            with self.subTest(base=base, size=size), self.assertRaises(ValueError):
                mkadt_a10.build(base, size)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'test.adt'
            result = subprocess.run([sys.executable, str(ROOT/'tools/mkadt_a10.py'), str(out)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(out.exists())
            out.write_bytes(b'preserve existing file')
            result = subprocess.run([sys.executable, str(ROOT/'tools/mkadt_a10.py'), str(out),
                                     '--ram-base', '0x4000000', '--ram-size', '0x2000000'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(out.read_bytes(), b'preserve existing file')

    def test_board_model_and_framebuffer_gate(self):
        self.run_c_sanitizers('test_board_profile.c', 'board guard passed')

    def test_renderers_under_sanitizers(self):
        self.run_c_sanitizers('test_display.c')

    def run_c_sanitizers(self, source, message=None):
        with tempfile.TemporaryDirectory() as d:
            for board in ('a10', 'a40'):
                binary = str(Path(d)/board)
                args = [*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-Wall', '-Wextra',
                        '-Werror', '-Wno-unused-function', '-g', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer']
                if sys.platform.startswith('linux'):
                    args += ['-fno-pie', '-no-pie']
                if board == 'a10':
                    args += ['-DPORT_BOARD_A10=1']
                subprocess.run([*args, str(ROOT/'tests'/source), '-o', binary], check=True, capture_output=True)
                result = subprocess.run([binary], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(result.stderr)
                self.assertIn(message or ('720x1520' if board == 'a10' else '1080x2340'), result.stdout)
