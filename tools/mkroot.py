#!/usr/bin/env python3
"""Build the A40 iOS 16 root image on macOS, without root.

  mkroot.py OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE_GB]

Same layout as ios-sweet's tools/mkiosroot.sh + sweet-root-tweaks.py, but:
  - the IPSW images are attached with hdiutil (owners on, read only): macOS
    decompresses APFS files transparently while we read them;
  - OUT.img is a sparse raw file holding one case-sensitive journaled HFS+
    volume (newfs_hfs on the attached raw image), as on the phone's
    userdata partition and QEMU's virtio disk;
  - files cannot be chowned without root, so every owner/mode is written to
    /a40fix.manifest ("uid gid mode path"), applied on the first boot by
    /usr/appleinternal/sbin/launchd.a40fix (fixer/a40fix.c, boot-arg
    launchdsuffix=a40fix) running as pid 1 under the iOS kernel.
"""
import os, plistlib, shutil, stat, subprocess, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
FIXER = os.path.join(HERE, '../fixer/launchd.a40fix')


def sh(*a, **kw):
    return subprocess.run(a, check=True, text=True, capture_output=True, **kw).stdout


def attach(img, owners=True, nomount=False, raw=False):
    args = ['hdiutil', 'attach', '-nobrowse']
    if raw:
        args += ['-imagekey', 'diskimage-class=CRawDiskImage']
    if nomount:
        args += ['-nomount']
    else:
        args += ['-owners', 'on' if owners else 'off']
    if not raw:
        args += ['-readonly']
    out = sh(*args, img)
    dev = mnt = None
    for line in out.splitlines():
        parts = line.split('\t')
        if parts[0].strip().startswith('/dev/') and dev is None:
            dev = parts[0].strip()
        if len(parts) >= 3 and parts[-1].strip().startswith('/Volumes/'):
            mnt = parts[-1].strip()
            dev = parts[0].strip()
    return dev, mnt


manifest = {}           # relpath -> [uid, gid, mode]
inodes = {}             # (dev, ino) -> dst path, for hard links


def scan_owners(src, rel_prefix):
    meta = {}
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        r = os.path.normpath(os.path.join(rel_prefix, rel))
        st = os.lstat(dirpath)
        meta[r] = [st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)]
        for name in list(dirnames):
            if os.path.islink(os.path.join(dirpath, name)):
                dirnames.remove(name)
                filenames.append(name)
        for name in filenames:
            st = os.lstat(os.path.join(dirpath, name))
            meta[os.path.normpath(os.path.join(r, name))] = [st.st_uid, st.st_gid,
                0 if stat.S_ISLNK(st.st_mode) else stat.S_IMODE(st.st_mode)]
    return meta


def copy_tree(src, dst, rel_prefix):
    nfiles = nbytes = 0
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        ddir = dst if rel == '.' else os.path.join(dst, rel)
        st = os.lstat(dirpath)
        os.makedirs(ddir, exist_ok=True)
        r = os.path.normpath(os.path.join(rel_prefix, rel))
        manifest[r] = [st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)]
        # symlinked dirs appear in dirnames: handle them as links, do not descend
        for name in list(dirnames):
            s = os.path.join(dirpath, name)
            if os.path.islink(s):
                dirnames.remove(name)
                filenames.append(name)
        for name in filenames:
            s = os.path.join(dirpath, name)
            d = os.path.join(ddir, name)
            st = os.lstat(s)
            rr = os.path.normpath(os.path.join(r, name))
            manifest[rr] = [st.st_uid, st.st_gid, 0 if stat.S_ISLNK(st.st_mode) else stat.S_IMODE(st.st_mode)]
            if os.path.lexists(d):
                os.unlink(d)
            if stat.S_ISLNK(st.st_mode):
                os.symlink(os.readlink(s), d)
                continue
            if not stat.S_ISREG(st.st_mode) or name == '.file':
                continue                # no device nodes / fifos in the root
            key = (st.st_dev, st.st_ino)
            if st.st_nlink > 1 and key in inodes:
                os.link(inodes[key], d)
                continue
            with open(s, 'rb') as fi, open(d, 'wb') as fo:
                shutil.copyfileobj(fi, fo, 1 << 22)
            os.chmod(d, stat.S_IMODE(st.st_mode) & 0o777 | 0o200)
            if st.st_nlink > 1:
                inodes[key] = d
            nfiles += 1
            nbytes += st.st_size
            if nfiles % 5000 == 0:
                print(f'  {rel_prefix}: {nfiles} files, {nbytes >> 20} MiB', flush=True)
    print(f'copied {rel_prefix}: {nfiles} files, {nbytes >> 20} MiB', flush=True)


def main():
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    os_dmg, sys_dmg, app_dmg, out = sys.argv[1:5]
    size_gb = int(sys.argv[5]) if len(sys.argv) > 5 else 16
    if os.path.exists(out):
        sys.exit(f'refusing to overwrite {out}')
    with open(out, 'wb') as f:
        f.truncate(size_gb << 30)
    dev, _ = attach(out, nomount=True, raw=True)
    print('formatting', dev, flush=True)
    sh('newfs_hfs', '-s', '-J', '-v', 'iOSRoot', dev)
    sh('hdiutil', 'detach', dev)
    rdev, root = attach(out, raw=True)
    print('root image mounted at', root, flush=True)
    mounts = []
    try:
        for dmg, prefix in ((os_dmg, '.'), (sys_dmg, 'private/preboot/Cryptexes/OS'),
                            (app_dmg, 'private/preboot/Cryptexes/App')):
            # owners on: real uid/gid/mode, but root-only files are unreadable
            d, m = attach(dmg)
            meta = scan_owners(m, prefix)
            subprocess.run(['hdiutil', 'detach', d], capture_output=True, check=True)
            d, m = attach(dmg, owners=False)
            mounts.append(d)
            print('source', dmg, 'at', m, flush=True)
            copy_tree(m, os.path.join(root, prefix), prefix)
            manifest.update(meta)
        finish(root)
    finally:
        for d in mounts:
            subprocess.run(['hdiutil', 'detach', d], capture_output=True)
        subprocess.run(['sync'])
        subprocess.run(['hdiutil', 'detach', rdev], capture_output=True)
    print('done:', out)


def ensure(root, rel, uid, gid, mode, isdir=True):
    p = os.path.join(root, rel)
    if isdir:
        os.makedirs(p, exist_ok=True)
    manifest[os.path.normpath(rel)] = [uid, gid, mode]


def finish(root):
    # shared cache where dyld looks at ignition level 1 (hard links)
    dsc = 'private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld'
    ensure(root, 'System/Library/Caches/com.apple.dyld', 0, 0, 0o755)
    for f in os.listdir(os.path.join(root, dsc)):
        dst = os.path.join(root, 'System/Library/Caches/com.apple.dyld', f)
        if not os.path.lexists(dst):
            os.link(os.path.join(root, dsc, f), dst)
        manifest['System/Library/Caches/com.apple.dyld/' + f] = manifest.get(dsc + '/' + f, [0, 0, 0o755])
    # cryptex-only files linked at their root path
    for c in ('OS', 'App'):
        base = os.path.join(root, 'private/preboot/Cryptexes', c)
        for dirpath, dirnames, filenames in os.walk(base):
            for name in filenames + [n for n in dirnames if os.path.islink(os.path.join(dirpath, n))]:
                s = os.path.join(dirpath, name)
                rel = os.path.relpath(s, base)
                if rel.startswith('System/Library/Caches/com.apple.dyld/'):
                    continue
                d = os.path.join(root, rel)
                if os.path.lexists(d):
                    continue
                os.makedirs(os.path.dirname(d), exist_ok=True)
                if os.path.islink(s):
                    os.symlink(os.readlink(s), d)
                else:
                    os.link(s, d)
                manifest[os.path.normpath(rel)] = manifest.get(os.path.normpath(os.path.join('private/preboot/Cryptexes', c, rel)), [0, 0, 0])
                print('linked', c + ':/' + rel)
    # logd stores (owner _logd 272)
    db = 'private/var/db'
    ensure(root, db + '/diagnostics', 272, 272, 0o751)
    ensure(root, db + '/uuidtext', 272, 272, 0o755)
    ensure(root, db + '/diagnostics/timesync', 272, 272, 0o755)
    for d in ('diagnostics', 'uuidtext', 'diagnostics/timesync'):
        open(os.path.join(root, db, d, '.migrated'), 'wb').close()
        manifest[f'{db}/{d}/.migrated'] = [272, 272, 0o644]
    # system keybag for the built-in AppleKeyStore (no passcode)
    ensure(root, 'private/var/keybags', 0, 0, 0o700)
    with open(os.path.join(root, 'private/var/keybags/systembag.kb'), 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>\n')
    manifest['private/var/keybags/systembag.kb'] = [0, 0, 0o600]

    run_tweaks(root)

    # the fixer itself
    ensure(root, 'usr/appleinternal/sbin', 0, 0, 0o755)
    shutil.copy(FIXER, os.path.join(root, 'usr/appleinternal/sbin/launchd.a40fix'))
    manifest['usr/appleinternal/sbin/launchd.a40fix'] = [0, 0, 0o755]

    # manifest: every path in the image (unknown ones -> root:wheel, current mode)
    n = 0
    with open(os.path.join(root, 'a40fix.manifest'), 'w', encoding='utf-8', errors='surrogateescape') as f:
        for dirpath, dirnames, filenames in os.walk(root):
            for name in [None] + dirnames + filenames:
                p = dirpath if name is None else os.path.join(dirpath, name)
                if name is None and dirpath != root:
                    continue        # directories are listed by their parent
                rel = os.path.normpath(os.path.relpath(p, root))
                if rel in ('a40fix.manifest', '.journal', '.journal_info_block', '.fseventsd') or \
                        rel.startswith('.fseventsd/') or rel.startswith('.Trashes'):
                    continue
                st = os.lstat(p)
                ent = manifest.get(rel)
                if ent is None:
                    ent = [0, 0, 0 if stat.S_ISLNK(st.st_mode) else stat.S_IMODE(st.st_mode)]
                path = '/' if rel == '.' else '/' + rel
                f.write(f'{ent[0]} {ent[1]} {ent[2]:o} {path}\n')
                n += 1
    print('manifest entries:', n)


def run_tweaks(root):
    """sweet-root-tweaks.py with chown/stat redirected to the manifest."""
    src = open(os.path.join(HERE, 'sweet-root-tweaks.py')).read()
    mod = types.ModuleType('tweaks')
    real_chown, real_stat = os.chown, os.stat

    def rel_of(path):
        return os.path.normpath(os.path.relpath(os.path.abspath(path), root))

    def chown(path, uid, gid, *a, **kw):
        e = manifest.setdefault(rel_of(path), [0, 0, 0])
        if uid != -1:
            e[0] = uid
        if gid != -1:
            e[1] = gid

    class St:
        def __init__(self, st, ent):
            self._st = st
            self.st_uid, self.st_gid = ent[0], ent[1]

        def __getattr__(self, k):
            return getattr(self._st, k)

    def fake_stat(path, *a, **kw):
        st = real_stat(path, *a, **kw)
        ent = manifest.get(rel_of(path))
        return St(st, ent) if ent else st

    os.chown, os.stat = chown, fake_stat
    try:
        exec(compile(src.replace("if __name__ == '__main__':", "if False:"), 'sweet-root-tweaks.py', 'exec'), mod.__dict__)
        argv = sys.argv
        sys.argv = ['sweet-root-tweaks.py', root]
        try:
            mod.main()
        finally:
            sys.argv = argv
    finally:
        os.chown, os.stat = real_chown, real_stat
    # tweaks wrote files with chmod: keep those modes
    for rel, ent in manifest.items():
        if ent[2] == 0:
            p = os.path.join(root, rel)
            if os.path.lexists(p) and not os.path.islink(p):
                ent[2] = stat.S_IMODE(os.lstat(p).st_mode)


if __name__ == '__main__':
    main()
