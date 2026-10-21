#!/bin/bash
# Writes the HFS root (disk-fixed.img from 1 MiB, 16 GiB) to the A40 userdata in TWRP:
# 256 MiB gz chunks via adb push (exec-in is broken on this TWRP), sha1-verified.
if [ "${BOARD:-}" != a40 ]; then
  echo 'A40-only legacy writer. A10 partition layout is unverified; refusing to run.' >&2
  exit 1
fi
A="${ADB:-adb}${SERIAL:+ -s $SERIAL}"
IMG=${1:?usage: flash-userdata.sh ROOT.img [OFFSET_MIB]}
OFF=${2:-1}
DEV=/dev/block/mmcblk0p32
T=$(mktemp -t a40chunk).gz
N=64; C=256
for i in $(seq ${START:-0} $((N-1))); do
  want=$(dd if=$IMG bs=1m skip=$((OFF + i*C)) count=$C 2>/dev/null | shasum | cut -d' ' -f1)
  dd if=$IMG bs=1m skip=$((OFF + i*C)) count=$C 2>/dev/null | gzip -1 > $T
  for try in 1 2 3; do
    $A push $T /tmp/c.gz >/dev/null && \
    got=$($A shell "zcat /tmp/c.gz | dd of=$DEV bs=1048576 seek=$((i*C)) 2>/dev/null; dd if=$DEV bs=1048576 skip=$((i*C)) count=$C 2>/dev/null | sha1sum" | cut -d' ' -f1)
    [ "$got" = "$want" ] && { echo "chunk $i/$((N-1)) OK"; break; }
    echo "chunk $i try $try MISMATCH"
    [ $try = 3 ] && { echo FAILED; exit 1; }
  done
done
$A shell 'rm -f /tmp/c.gz; sync'; echo ALL DONE
