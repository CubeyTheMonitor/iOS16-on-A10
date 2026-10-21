import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from test_evidence import ROOT, dtb
sys.path.insert(0, str(ROOT / 'tools'))
import unpack_dt_table


def table(blobs, padding=0):
    payload = bytearray()
    rows = []
    for index, blob in enumerate(blobs):
        start = 32 + 32 * len(blobs) + len(payload)
        rows.append(struct.pack('>8I', len(blob), start, index, 0, 0, 255, 0, 0))
        payload += blob + bytes(-len(blob) % 4)
    total = 32 + 32 * len(blobs) + len(payload)
    return bytearray(struct.pack('>8I', 0xd7b7ab1e, total, 32, 32, len(blobs), 32, 2048, 0)
                     + b''.join(rows) + payload + bytes(padding))


class DTTableTests(unittest.TestCase):
    def test_padded_base_and_overlay_entries(self):
        base = dtb(('', [('compatible', b'synthetic,board\0')], []))
        overlay = dtb(('', [], [('fragment@0', [], [])]))
        data = table([base, overlay], padding=4096)
        report, blobs = unpack_dt_table.unpack(data)
        self.assertEqual(blobs, [base, overlay])
        self.assertEqual(report['trailing_bytes'], 4096)
        self.assertFalse(report['hardware_verified'])
        self.assertEqual([e['kind'] for e in report['entries']], ['base_or_merged', 'overlay'])
        self.assertEqual([e['custom'] for e in report['entries']], [[0, 255, 0, 0]]*2)

    def test_malformed_container_headers(self):
        original = table([dtb(('', [], []))])
        for offset, value in ((0, 0), (4, len(original)+1), (8, 64), (12, 16),
                              (16, 0), (16, 4097), (20, 31), (20, len(original)),
                              (24, 1023), (28, 1)):
            data = original.copy()
            struct.pack_into('>I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                unpack_dt_table.unpack(data)

    def test_entry_bounds_and_invalid_fdt(self):
        original = table([dtb(('', [], []))], padding=2048)
        declared = struct.unpack_from('>I', original, 4)[0]
        for offset, value in ((32, 39), (32, 0xffffffff), (36, 32),
                              (36, 65), (36, declared)):
            data = original.copy()
            struct.pack_into('>I', data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                unpack_dt_table.unpack(data)
        data = original.copy()
        data[64] ^= 1
        with self.assertRaises(ValueError):
            unpack_dt_table.unpack(data)

    def test_exact_aliases_preserve_each_selector(self):
        blob = dtb(('', [], []))
        data = table([blob, blob])
        start = struct.unpack_from('>I', data, 36)[0]
        struct.pack_into('>I', data, 68, start)
        report, blobs = unpack_dt_table.unpack(data)
        self.assertEqual(blobs, [blob, blob])
        self.assertEqual([e['id'] for e in report['entries']], [0, 1])

    def test_valid_nested_fdt_cannot_hide_partial_overlap(self):
        inner = dtb(('', [], []))
        outer = dtb(('', [('nested', inner)], []))
        data = table([outer, inner])
        outer_start = struct.unpack_from('>I', data, 36)[0]
        struct.pack_into('>I', data, 68, outer_start + outer.find(b'\xd0\x0d\xfe\xed', 4))
        with self.assertRaisesRegex(ValueError, 'overlap'):
            unpack_dt_table.unpack(data)

    def test_cli_export_never_overwrites_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root/'dt.img', root/'export'
            blob = dtb(('', [], []))
            data = table([blob])
            source.write_bytes(data)
            command = [sys.executable, str(ROOT/'tools/unpack_dt_table.py'), str(source), '--out-dir', str(output)]
            r = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(r.stdout)['entries'][0]['size'], len(blob))
            self.assertEqual((output/'entry-0000.dtb').read_bytes(), blob)
            before = (output/'manifest.json').read_bytes()
            r = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertEqual((output/'manifest.json').read_bytes(), before)
            self.assertEqual(source.read_bytes(), data)

    def test_raw_dtb_and_device_input_are_rejected(self):
        with self.assertRaises(ValueError):
            unpack_dt_table.unpack(dtb(('', [], [])))
        r = subprocess.run([sys.executable, str(ROOT/'tools/unpack_dt_table.py'), '/dev/null'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn('regular file', r.stderr)


if __name__ == '__main__':
    unittest.main()
