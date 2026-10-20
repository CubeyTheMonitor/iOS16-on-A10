#!/usr/bin/env python3
"""Wrap the HFS+ root image in a GPT disk for QEMU (virtio): one partition
'userdata' at 1 MiB holding the image plus 8 MiB slack at its end for the
kernel's persistent log (sweet_ufs writes the last 4 MiB of userdata).
Sparse aware: only data extents of the root image are copied.

  mkdisk.py ROOT.img DISK.img
"""
import os, struct, sys, uuid, zlib

root, out = sys.argv[1:3]
SEC = 512
start = 2048
rsize = os.path.getsize(root)
part_secs = (rsize + (8 << 20)) // SEC
end = start + part_secs - 1
total = end + 1 + 34 + 2048
with open(out, 'wb') as f:
    f.truncate(total * SEC)

def entry():
    name = 'userdata'.encode('utf-16-le').ljust(72, b'\0')
    return (uuid.UUID('EBD0A0A2-B9E5-4433-87C0-68B6B72699C7').bytes_le + uuid.uuid4().bytes_le +
            struct.pack('<QQQ', start, end, 0) + name)

ents = entry().ljust(128, b'\0') + b'\0' * 128 * 127
ecrc = zlib.crc32(ents)
def hdr(my, alt, ent_lba):
    h = struct.pack('<8sIIIIQQQQ16sQIII', b'EFI PART', 0x10000, 92, 0, 0, my, alt, 34,
                    total - 34, uuid.uuid4().bytes_le, ent_lba, 128, 128, ecrc)
    h = h[:16] + struct.pack('<I', zlib.crc32(h)) + h[20:]
    return h.ljust(SEC, b'\0')
mbr = bytearray(SEC)
mbr[446:462] = struct.pack('<BBBBBBBBII', 0, 0, 2, 0, 0xEE, 0xff, 0xff, 0xff, 1, min(total - 1, 0xffffffff))
mbr[510:512] = b'\x55\xaa'
with open(out, 'r+b') as f:
    f.write(mbr); f.write(hdr(1, total - 1, 2)); f.write(ents)
    f.seek((total - 33) * SEC); f.write(ents); f.write(hdr(total - 1, 1, total - 33))
    with open(root, 'rb') as r:
        fd = r.fileno(); pos = 0; n = 0
        while True:
            try:
                d = os.lseek(fd, pos, os.SEEK_DATA)
            except OSError:
                break
            h = os.lseek(fd, d, os.SEEK_HOLE)
            r.seek(d); f.seek(start * SEC + d)
            left = h - d
            while left:
                b = r.read(min(left, 1 << 24)); f.write(b); left -= len(b); n += len(b)
            pos = h
print(f'{out}: userdata LBA {start}-{end}, copied {n >> 20} MiB')
