#!/bin/bash
# Compile and validate a flat ARM64 object only. No boot image or device access.
# CLANG may name a wrapper executable (e.g. for a cross toolchain).
set -euo pipefail
cd "$(dirname "$0")"
if [ "$#" -gt 1 ]; then
    echo 'Usage: [CLANG=clang] [OUT_DIR=out] ./compile.sh [loader16]' >&2
    exit 1
fi
prog=${1:-loader16}
case "$prog" in
    ''|*[!a-zA-Z0-9_]*) echo 'Expected a local C program name without a suffix.' >&2; exit 1 ;;
esac
out_dir=${OUT_DIR:-out}
mkdir -p "$out_dir"
"${CLANG:-clang}" -target aarch64-none-elf -mcmodel=tiny -fno-pic -ffreestanding -fno-builtin \
    -fno-stack-protector -fno-common -fno-unwind-tables -fno-asynchronous-unwind-tables \
    -mgeneral-regs-only -mstrict-align -mcpu=cortex-a73 -g0 -O2 -Wall -Wextra -Werror \
    -Wno-unused-function -S "$prog.c" -o "$out_dir/$prog.s"

# Keep code, constants and zero-initialized storage together for ADR addressing.
sed -E -e 's/^[[:space:]]*\.section[[:space:]]+\.(rodata|data|bss)[^,]*(,.*)?$/\t.text/' \
    -e 's/^[[:space:]]*\.(data|bss)[[:space:]]*$/\t.text/' \
    -e '/^[[:space:]]*\.local[[:space:]]/d' \
    -e 's/^[[:space:]]*\.comm[[:space:]]+([^,]+),([0-9]+),([0-9]+)$/\t.text\n\t.balign \3\n\1:\n\t.zero \2/' \
    "$out_dir/$prog.s" > "$out_dir/$prog-flat.s"
"${CLANG:-clang}" -target aarch64-none-elf -mcpu=cortex-a73 -g0 -c "$out_dir/$prog-flat.s" -o "$out_dir/$prog.o"
python3 - "$out_dir/$prog.o" <<'PY'
import sys
from pack import elf_text
blob = elf_text(sys.argv[1])
print(f'Validated ARM64 flat object: {sys.argv[1]} ({len(blob)} bytes, no relocations)')
PY
