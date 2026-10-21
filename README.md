this is a fork of the iOS16 on A40

This will be A10 (exynos7884/7885) soon.

# iOS16 on A40

iOS 16.7.16 (iPhone X userland, build 20H392) booting natively on the **Samsung Galaxy A40 (SM-A405FN, Exynos 7904)**: kernel, launchd, SpringBoard, lock screen, touch, buttons, both Cortex-A73 cores.

It is a port of [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) (iOS 16 on the Redmi Note 10 Pro) to the A40's Exynos SoC. Rendering is done on the CPU (there is no GPU driver), so it is **slow**: it is a proof of concept, not a daily driver.

> 🇫🇷 Résumé : iOS 16 démarre sur le Galaxy A40 (écran de verrouillage, tactile, boutons, 2 cœurs A73). Rendu CPU, donc lent. Le guide ci-dessous explique comment le reproduire sans IA. **L'installation efface les données Android** (sauvegarde-les d'abord).

## What works / what doesn't

| Works | Doesn't (yet) |
| --- | --- |
| Boot to lock screen and home screen (iPhone X gestures) | GPU acceleration (Mali-G71: no Metal driver, see below) |
| Touch (Zinitix ZT7548), Power / Vol+ / Vol- | Wallpaper (PosterBoard shows black) |
| 2 × Cortex-A73 (the A53s cannot run iOS: no 16K pages) | Wi-Fi, Bluetooth, cellular, audio, camera, sensors, USB |
| eMMC root (read/write), persistent kernel log | Charging status (fake 100 %), sleep |
| | Some apps freeze (Photos, Settings > About) |

CPU clock: S-Boot leaves the A73s at 1352 MHz. Raising it needs the ACPM voltage interface, not done.

## ⚠️ Before you start

* Phone: **SM-A405FN** with an unlocked bootloader and **TWRP**. Other A40 variants are untested.
* Installing writes the iOS root image over the **userdata** partition: **all Android data is erased**. Back up `boot` and `userdata` from TWRP first (Backup tab, or `adb pull /dev/block/by-name/boot`).
* Going back to Android = flash your `boot` backup and restore/format data in TWRP.
* You need a **Mac** (macOS 13+, Xcode command line tools, Python 3) to build the iOS root image (it uses `hdiutil` / `newfs_hfs`). The root image contains Apple software, so **it is not distributed here**: you build it from Apple's IPSW yourself.

## Quick install (prebuilt boot image)

1. **Build the iOS root image** (≈ 30 min, needs ≈ 40 GB free):
   ```bash
   # 1. Download from Apple's iPhone X (iPhone10,3) 16.7.16 IPSW only the 3 images needed
   #    (remotezip.py is in ios-sweet/tools; or download the full IPSW and unzip these files)
   IPSW=https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-77006/1158E502-D76D-4226-AA06-ED5E30CD1111/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw
   mkdir ipsw
   for f in 087-86698-044.dmg 087-86593-047.dmg 087-86715-047.dmg; do python3 remotezip.py "$IPSW" $f ipsw; done
   # 2. Build the root (raw HFS+ image, owners recorded in /a40fix.manifest)
   python3 tools/mkroot.py ipsw/087-86698-044.dmg ipsw/087-86593-047.dmg ipsw/087-86715-047.dmg root.img 16
   ```
   `087-86698-044.dmg` = OS, `087-86593-047.dmg` = SystemOS cryptex, `087-86715-047.dmg` = AppOS cryptex (check `BuildManifest.plist` if Apple renames them).

2. **Put the phone in TWRP**, connect it, then write the root to userdata (≈ 15 min, every 256 MiB chunk is sha1-verified):
   ```bash
   SERIAL=<your adb serial> tools/flash-userdata.sh root.img 0
   ```

3. **First boot = fixer boot.** The image was built without root on the Mac, so file owners/modes must be applied once on the phone. Still in TWRP:
   ```bash
   adb push prebuilt/boot-ios16-a40-fixer.img /tmp/boot.img
   adb shell dd if=/tmp/boot.img of=/dev/block/by-name/boot
   ```
   Reboot to system: it applies the manifest and halts (the screen stops after the kernel messages; give it 10 minutes). Then hold Power + Vol- and go back to TWRP (Power + Vol+).

4. **Flash the normal boot image** from TWRP and reboot:
   ```bash
   adb push prebuilt/boot-ios16-a40.img /tmp/boot.img
   adb shell dd if=/tmp/boot.img of=/dev/block/by-name/boot
   ```
   The first real boot stays 5–15 min on the Apple logo, then the lock screen appears. Swipe up.

Then in Settings > Accessibility enable **Reduce Transparency** and **Reduce Motion**: it helps a lot without a GPU.

## Build everything

### 1. Kernel (xnu-8796 + ios-sweet + A40)

1. Follow ios-sweet's kernel build (xnu-8796.141.3 with its patches `0001`–`0081`, built with [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build), `KERNEL_CONFIG=DEVELOPMENT MACHINE_CONFIG=SWEET`, KDK 13.5).
2. Apply this repo's patches on top:
   ```bash
   git apply kernel/0000-xcode-iig-kernelContent.patch   # only needed with recent Xcode (iig)
   git apply kernel/0001-a40-port.patch
   ```
3. Rebuild libfirehose_kernel **without LSE atomics** (the A73 is ARMv8.0): `xcodebuild ... ARCHS=arm64 OTHER_CFLAGS='$(inherited) -mcpu=cortex-a73'`, and copy it to `fakeroot/usr/local/lib/kernel/libfirehose_kernel.a`.
4. Build. Output: `build/xnu.obj/DEVELOPMENT_ARM64_SWEET/kernel.development.sweet`. Check that `llvm-objdump -d --mattr=+lse` finds no `cas`/`ldadd`/`swp` instruction.

### 2. Device tree, payload, boot image

```bash
D22AP_ADT=ipsw/d22ap.adt python3 tools/mkadt.py a40.adt     # d22ap.adt: ipsw img4 im4p extract Firmware/all_flash/DeviceTree.d22ap.im4p
python3 tools/mkpayload.py kernel.development.sweet a40.adt loader/payload.bin --cmdline \
  'debug=0xc keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 cpus=2 sweetusb=0 sweetbattery=0 sweetfb_hz=30 sweetfb_noconsole=1'
cd loader && PROG=loader16 BLOB=payload.bin ./build.sh /path/to/your/boot-backup.img   # -> out/boot.img
```
For the fixer boot add `launchdsuffix=a40fix` to the command line (and `cpus=1` is fine).

`build.sh` only needs Xcode's clang. `--like` (your TWRP boot backup) copies the Android boot header fields S-Boot expects.

### 3. Testing without the phone (QEMU)

`tools/qemu-a40.py` boots the same kernel on `qemu-system-aarch64 -M virt,gic-version=2 -cpu cortex-a76` with the same memory map (RAM at 0x880000000, framebuffer at 0xEC000000) and a virtio disk instead of the eMMC (`mkadt.py --qemu`, `mkdisk.py` wraps the root in a GPT with a `userdata` partition). `tools/qrun.sh` dumps the kernel log ring from guest memory. A full boot to the lock screen takes ≈ 40 min under TCG.

## Debugging on the phone

* Kernel panics are drawn on screen.
* The kernel keeps its console in the **last 4 MiB of userdata**; from TWRP:
  ```bash
  S=$(adb shell cat /sys/block/mmcblk0/mmcblk0p32/size); adb shell "dd if=/dev/block/mmcblk0p32 bs=4096 skip=$((S/8-1025)) count=1025" > log.bin
  python3 tools/sweet-log.py log.bin > log.txt
  ```
* Editing files of the iOS root from the Mac: `tools/pull-phone.py phone.img` (copy, verified), attach it with `hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount`, `mount -t hfs -o noowners`, edit, unmount, then `tools/push-sync.py phone.img` writes back only the changed MiBs.

## How it works (short)

See [docs/hardware.md](docs/hardware.md) for addresses and the problems solved. Main points:

* **16K pages**: iOS 16 needs the 16K translation granule; the Cortex-A53s don't have it, the Cortex-A73s do. `loader16` (started by S-Boot on an A53) powers an A73 through the **Exynos PMU** (PSCI `CPU_ON` alone records the entry point but does not power the core) and jumps into XNU there. The second A73 is started by the kernel through a low-memory trampoline (the secure monitor truncates entry addresses above 4 GiB).
* **GIC-400 (GICv2)** support in the sweet interrupt code (sweet has GICv3).
* **eMMC**: polled dw_mmc driver reusing the bootloader's card state (8-bit DDR); the Exynos FIFO is **64-bit wide**.
* **Touch**: polled Samsung I2C (IRQEN must be set for the pending flag) + Zinitix ZT7548 protocol.
* **Root without root on macOS**: the image is built as the normal user; a static `launchd.a40fix` applies `/a40fix.manifest` (owners, modes) on the first boot.

## Why no GPU?

iOS draws everything through Metal and Apple's own GPU driver. Supporting the Mali-G71 would need a Mali kernel driver for XNU, a Metal implementation for Mali and a shader compiler from Apple's AIR to Bifrost: many months of work for a team. Rendering stays on the CPU, like ios-sweet.

## Credits

* [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet): the iOS 16 bring-up this is built on (kernel patches, IOSurface/framebuffer/HID drivers, root tooling; `tools/adt.py`, `mkadt.py`, `mkpayload.py`, `sweet-*.py` are adapted from it).
* Apple's open-source XNU (APSL 2.0), [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build).
* Samsung's A40 kernel sources (device tree, PMU/CMU tables) for the hardware details.

iOS is Apple's software: nothing from Apple's IPSW is in this repository. Use at your own risk.
