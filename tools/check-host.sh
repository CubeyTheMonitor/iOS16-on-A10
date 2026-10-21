#!/bin/bash
# Offline only: no adb, block devices, downloaded firmware, or QEMU invocation.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m compileall -q tools loader tests
python3 -W ignore::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
for script in loader/*.sh tools/*.sh; do
    bash -n "$script"
done
test_bin=$(mktemp /tmp/a10-host-check.XXXXXX)
trap 'rm -f "$test_bin"' EXIT
for profile_flag in -DPORT_BOARD_A10=1 -DPORT_BOARD_A40=1; do
    "${CC:-cc}" -std=gnu11 -ffreestanding -fno-builtin -fsyntax-only \
        -Wall -Wextra -Werror -Wno-unused-function "$profile_flag" loader/loader16.c
done
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -pedantic -g \
    -fsanitize=address,undefined -fno-omit-frame-pointer tests/test_portable.c -o "$test_bin"
"$test_bin"
for patch in kernel/*.patch; do
    git apply --numstat "$patch" >/dev/null
done
git diff --check
git diff --cached --check
