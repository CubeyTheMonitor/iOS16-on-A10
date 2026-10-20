#!/bin/bash
# Compile un programme bare-metal (payload.c par défaut) et produit boot.img pour le Galaxy A40.
# Usage : [PROG=loader] [BLOB=noyau.macho] [RAMDISK=disque.img] build.sh [boot-sauvegarde.img]
#   boot-sauvegarde.img : sauvegarde de la partition boot (recommandé, adresses et os_version)
#   PROG=loader sans BLOB : embarque le faux noyau de test (testkernel.c)
# Seul le clang de Xcode est nécessaire : pas de linker, le code « tiny » n'a aucune relocation.
set -euo pipefail
cd "$(dirname "$0")"
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

clang -target aarch64-none-elf -mcmodel=tiny -fno-pic -ffreestanding -fno-builtin \
	-fno-stack-protector -fno-common -mgeneral-regs-only -mstrict-align -mcpu=cortex-a73 -O2 -Wall \
	-Wno-unused-function -S $PROG.c -o out/$PROG.s

# Données (police, variables) rangées dans .text : un seul bloc, adressé par adr.
sed -E -e 's/^[[:space:]]*\.section[[:space:]]+\.(rodata|data|bss)[^,]*(,.*)?$/	.text/' \
	-e 's/^[[:space:]]*\.(data|bss)[[:space:]]*$/	.text/' \
	-e '/^[[:space:]]*\.local[[:space:]]/d' \
	-e 's/^[[:space:]]*\.comm[[:space:]]+([^,]+),([0-9]+),([0-9]+)$/	.text\n	.balign \3\n\1:\n	.zero \2/' out/$PROG.s > out/$PROG-flat.s
clang -target aarch64-none-elf -c out/$PROG-flat.s -o out/$PROG.o

python3 pack.py out/$PROG.o out/boot.img ${1:+--like "$1"} ${BLOB:+--blob "$BLOB"} ${RAMDISK:+--ramdisk "$RAMDISK"}
