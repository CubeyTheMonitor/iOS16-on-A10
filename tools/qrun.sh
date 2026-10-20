#!/bin/bash
# qrun.sh OUTDIR SECS 'cmdline'  -> boots out/disk.img in QEMU, dumps kernel log ring to OUTDIR/ring.txt
K=${KERNEL:?set KERNEL=path/to/kernel.development.sweet}
python3 "$(dirname "$0")"/mkpayload.py $K ${ADT:-out/qa40.adt} out/pq.bin --cmdline "$3" >/dev/null
VA=$(xcrun llvm-nm $K | awk '/ _sweet_log_total$/{print $1}')
PA=$(printf '0x%x' $((0x$VA - 0xfffffe0006000000 + 0x880000000)))
mkdir -p $1
python3 "$(dirname "$0")"/qemu-a40.py out/pq.bin $1 --disk out/disk.img --secs $2 --hmp "pmemsave $PA 0x400008 \"$PWD/$1/ring.bin\"" >/dev/null 2>&1
python3 - "$1" <<'P'
import struct,sys
d=open(sys.argv[1]+'/ring.bin','rb').read()
tot=struct.unpack('<Q',d[:8])[0]; r=d[8:]; S=len(r)
t=r[:tot] if tot<=S else r[tot%S:]+r[:tot%S]
open(sys.argv[1]+'/ring.txt','wb').write(t)
print('log bytes',tot)
P
