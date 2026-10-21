#!/usr/bin/env python3
"""Pull the first 16 GiB of the A40 userdata (iOS root) into a sparse file, 256 MiB
chunks (adb exec-out stalls on long streams), each sha1-verified against the phone."""
import subprocess, sys, zlib, os, hashlib
from board import require_supported_board
require_supported_board(os.environ.get('BOARD'))
A = [os.environ.get('ADB', 'adb')] + (['-s', os.environ['SERIAL']] if os.environ.get('SERIAL') else [])
out = sys.argv[1]
start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
MB = 1 << 20; C = 256; N = 16 * 1024 // C
zero = bytes(MB)
if not os.path.exists(out):
    open(out, 'wb').truncate(16 << 30)
with open(out, 'r+b') as f:
    for i in range(start, N):
        cmd = f'dd if=/dev/block/mmcblk0p32 bs=1048576 skip={i*C} count={C} 2>/dev/null'
        for t in range(5):
            want = subprocess.run(A + ['shell', cmd + ' | sha1sum'], capture_output=True, text=True, timeout=300).stdout.split()[0]
            try:
                raw = subprocess.run(A + ['exec-out', cmd + ' | gzip -1'], capture_output=True, timeout=300).stdout
                data = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
            except Exception as e:
                print(f'chunk {i} try {t}: {e}', flush=True); continue
            if len(data) == C * MB and hashlib.sha1(data).hexdigest() == want:
                for k in range(C):
                    blk = data[k * MB:(k + 1) * MB]
                    if blk != zero:
                        f.seek((i * C + k) * MB); f.write(blk)
                print(f'chunk {i}/{N - 1} OK', flush=True); break
            print(f'chunk {i} try {t}: mismatch ({len(data)} bytes)', flush=True)
        else:
            sys.exit(f'chunk {i} FAILED')
print('ALL DONE')
