#!/bin/bash
# Compile un programme bare-metal (payload.c par défaut) et produit boot.img pour le Galaxy A40.
# Usage : [PROG=loader] [BLOB=noyau.macho] [RAMDISK=disque.img] build.sh [boot-sauvegarde.img]
#   boot-sauvegarde.img : sauvegarde de la partition boot (recommandé, adresses et os_version)
#   PROG=loader sans BLOB : embarque le faux noyau de test (testkernel.c)
# Seul le clang de Xcode est nécessaire : pas de linker, le code « tiny » n'a aucune relocation.
set -euo pipefail
cd "$(dirname "$0")"
if [ "${BOARD:-}" != a40 ]; then
    echo 'Set BOARD=a40 to build the inherited A40 loader. A10 has no validated hardware profile.' >&2
    exit 1
fi
if [ "$#" -ne 1 ]; then
    echo 'Usage: BOARD=a40 PROG=loader16 BLOB=payload.bin ./build.sh A40-boot-backup.img' >&2
    exit 1
fi
mkdir -p out
PROG=${PROG:-payload}

if [ "$PROG" = loader ] && [ -z "${BLOB:-}" ]; then
	clang -target arm64-apple-ios12.0 -isysroot "$(xcrun --sdk iphoneos --show-sdk-path)" \
		-ffreestanding -fno-builtin -fno-stack-protector -mgeneral-regs-only -mstrict-align -mcpu=cortex-a53 \
		-O2 -Wall -Wno-unused-function -c testkernel.c -o out/testkernel.o
	ld -arch arm64 -static -e _kstart -image_base 0xfffffff007004000 \
		-platform_version ios 12.0 12.0 -o out/testkernel.macho out/testkernel.o
	BLOB=out/testkernel.macho
fi

OUT_DIR=out ./compile.sh "$PROG"

python3 pack.py out/$PROG.o out/boot.img --board "$BOARD" --like "$1" ${BLOB:+--blob "$BLOB"} ${RAMDISK:+--ramdisk "$RAMDISK"}
