#!/usr/bin/env python3
"""Make the phone's userdata match NEW: compare sha1 per 256 MiB, then per MiB, and write differing MiBs."""
import subprocess, sys, os, hashlib
from board import require_supported_board
require_supported_board(os.environ.get('BOARD'))
A = [os.environ.get('ADB', 'adb')] + (['-s', os.environ['SERIAL']] if os.environ.get('SERIAL') else [])
new = sys.argv[1]
MB = 1 << 20; C = 256
DEV = '/dev/block/mmcblk0p32'
def sh(c): return subprocess.run(A + ['shell', c], capture_output=True, text=True).stdout
tmp = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'a40blk.bin')
n = 0
with open(new, 'rb') as b:
    for ch in range(os.path.getsize(new) // (C * MB)):
        b.seek(ch * C * MB); data = b.read(C * MB)
        if sh(f'dd if={DEV} bs=1048576 skip={ch*C} count={C} 2>/dev/null | sha1sum').split()[0] == hashlib.sha1(data).hexdigest():
            continue
        remote = sh(f'for i in $(seq {ch*C} {ch*C+C-1}); do dd if={DEV} bs=1048576 skip=$i count=1 2>/dev/null | sha1sum; done').split('\n')
        for k in range(C):
            blk = data[k * MB:(k + 1) * MB]
            if remote[k].split()[0] == hashlib.sha1(blk).hexdigest():
                continue
            i = ch * C + k
            open(tmp, 'wb').write(blk)
            subprocess.run(A + ['push', tmp, '/tmp/blk.bin'], capture_output=True, check=True)
            got = sh(f'dd if=/tmp/blk.bin of={DEV} bs=1048576 seek={i} 2>/dev/null; dd if={DEV} bs=1048576 skip={i} count=1 2>/dev/null | sha1sum').split()[0]
            if got != hashlib.sha1(blk).hexdigest():
                sys.exit(f'MiB {i} FAILED')
            n += 1
        print(f'chunk {ch} synced', flush=True)
sh('rm -f /tmp/blk.bin; sync')
print('ALL DONE, MiB written:', n)
