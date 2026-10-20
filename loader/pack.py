#!/usr/bin/env python3
"""Extrait le payload de l'objet ELF et l'emballe en boot.img (en-tête Android v1) pour S-Boot.

Usage : pack.py payload.o boot.img [--like boot-sauvegarde.img] [--blob noyau.macho]

--like recopie adresses, nom de carte, cmdline et os_version d'un boot.img existant
(ta sauvegarde TWRP de PixelExperience). Sans lui, valeurs du BoardConfig du A40.
--blob ajoute un fichier (le noyau pour le loader) après le code, aligné sur 16 Ko ;
son offset et sa taille vont dans les champs 0x20 et 0x28 de l'en-tête Image.
"""
import argparse, gzip, hashlib, struct, sys

HDR_SIZE = 1648


def elf_text(path):
    data = open(path, 'rb').read()
    if data[:4] != b'\x7fELF' or data[4] != 2 or data[18] != 183:
        sys.exit('pas un ELF aarch64 64 bits')
    shoff, = struct.unpack_from('<Q', data, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 0x3A)
    secs = [struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shentsize) for i in range(shnum)]
    names = secs[shstrndx]
    name = lambda s: data[names[4] + s[0]:data.index(b'\0', names[4] + s[0])].decode()

    text = None
    for s in secs:
        n, typ = name(s), s[1]
        if typ in (4, 9):  # SHT_RELA / SHT_REL
            sys.exit(f'relocation restante ({n}) : le payload ne serait pas position-indépendant')
        if n == '.text':
            text = s
        elif typ == 1 and s[2] & 2 and s[5]:  # SHT_PROGBITS alloué hors .text
            sys.exit(f'section allouée inattendue : {n}')
    if text is None:
        sys.exit('pas de .text')
    blob = bytearray(data[text[4]:text[4] + text[5]])

    # _head doit être au tout début.
    for s in secs:
        if s[1] == 2:  # SHT_SYMTAB
            strtab = secs[s[6]]
            for off in range(s[4], s[4] + s[5], 24):
                st_name, _, _, _, st_value, _ = struct.unpack_from('<IBBHQQ', data, off)
                sym = data[strtab[4] + st_name:data.index(b'\0', strtab[4] + st_name)]
                if sym == b'_head' and st_value != 0:
                    sys.exit('_head n\'est pas à l\'offset 0')
    if blob[0x38:0x3C] != b'ARM\x64':
        sys.exit('en-tête Image arm64 absent')
    struct.pack_into('<Q', blob, 16, len(blob))
    return bytes(blob)


def empty_ramdisk():
    name = b'TRAILER!!!\0'
    hdr = b'070701' + b''.join(b'%08X' % v for v in
                               (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0))
    cpio = hdr + name
    cpio += b'\0' * (-len(cpio) % 4)
    cpio += b'\0' * (-len(cpio) % 512)
    return gzip.compress(cpio, mtime=0)


def defaults():
    base = 0x10000000
    return dict(kernel_addr=base + 0x8000, ramdisk_addr=base + 0x01000000,
                second_addr=base + 0x00F00000, tags_addr=base + 0x100, page_size=2048,
                os_version=0, name=b'SRPSA16C004RU', cmdline=b'', extra_cmdline=b'')


def read_like(path):
    h = open(path, 'rb').read(HDR_SIZE)
    if h[:8] != b'ANDROID!':
        sys.exit(f'{path} : pas un boot.img Android')
    (_, kaddr, _, raddr, _, saddr, taddr, page, ver, osv) = struct.unpack_from('<10I', h, 8)
    if ver > 2:
        sys.exit(f'{path} : en-tête v{ver}, attendu v0 à v2')
    strip = lambda b: b.split(b'\0', 1)[0]
    return dict(kernel_addr=kaddr, ramdisk_addr=raddr, second_addr=saddr, tags_addr=taddr,
                page_size=page, os_version=osv, name=strip(h[48:64]),
                cmdline=strip(h[64:576]), extra_cmdline=strip(h[608:1632]))


def build(kernel, ramdisk, f):
    page = f['page_size']
    sha = hashlib.sha1()
    for blob in (kernel, ramdisk, b'', b''):  # noyau, ramdisk, second, recovery_dtbo
        sha.update(blob)
        sha.update(struct.pack('<I', len(blob)))
    hdr = b'ANDROID!' + struct.pack('<10I', len(kernel), f['kernel_addr'], len(ramdisk),
                                    f['ramdisk_addr'], 0, f['second_addr'], f['tags_addr'],
                                    page, 1, f['os_version'])
    hdr += f['name'].ljust(16, b'\0') + f['cmdline'].ljust(512, b'\0')
    hdr += sha.digest().ljust(32, b'\0') + f['extra_cmdline'].ljust(1024, b'\0')
    hdr += struct.pack('<IQI', 0, 0, HDR_SIZE)
    assert len(hdr) == HDR_SIZE
    pad = lambda b: b + b'\0' * (-len(b) % page)
    return pad(hdr) + pad(kernel) + pad(ramdisk) + b'SEANDROIDENFORCE'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('elf')
    ap.add_argument('out')
    ap.add_argument('--like')
    ap.add_argument('--blob')
    ap.add_argument('--ramdisk', help='image disque ajoutée après le blob (offset en 0x30, taille u32 en 0x3C)')
    a = ap.parse_args()
    kernel = elf_text(a.elf)
    if a.blob:
        blob = open(a.blob, 'rb').read()
        off = (len(kernel) + 0x3FFF) & ~0x3FFF
        kernel = bytearray(kernel.ljust(off, b'\0') + blob)
        struct.pack_into('<Q', kernel, 0x10, len(kernel))
        struct.pack_into('<QQ', kernel, 0x20, off, len(blob))
        kernel = bytes(kernel)
    if a.ramdisk:
        if not a.blob:
            sys.exit('--ramdisk exige --blob')
        rd = open(a.ramdisk, 'rb').read()
        off = (len(kernel) + 0x3FFF) & ~0x3FFF
        kernel = bytearray(kernel.ljust(off, b'\0') + rd)
        struct.pack_into('<Q', kernel, 0x10, len(kernel))
        struct.pack_into('<Q', kernel, 0x30, off)
        struct.pack_into('<I', kernel, 0x3C, len(rd))
        kernel = bytes(kernel)
        # chargé vers 0x80100000 ; doit finir sous le journal de panique (0x8FFFC000)
        if 0x80200000 + len(kernel) > 0x8FFFC000:
            sys.exit('image trop grosse : dépasserait 0x8FFFC000 une fois chargée')
    fields = read_like(a.like) if a.like else defaults()
    img = build(kernel, empty_ramdisk(), fields)
    open(a.out, 'wb').write(img)
    print(f'payload {len(kernel)} octets, {a.out} {len(img)} octets, '
          f'kernel_addr 0x{fields["kernel_addr"]:08x}, page {fields["page_size"]}, '
          f'os_version 0x{fields["os_version"]:08x}'
          + ('' if a.like else ' (valeurs par défaut, sans --like)'))


if __name__ == '__main__':
    main()
