# One UI 8.5 d2s Bring-Up Research

## Source And Target

- Source OS: Samsung Galaxy S24 FE `SM-S721B/EUX`.
- Current FOTA result on 2026-07-05: Android `16`, latest
  `S721BXXSCDZF3/S721BOXMCDZF3/S721BXXSCDZF3`.
- Target device: Galaxy Note10+ `d2s / SM-N975F`.
- Current target firmware source: `SM-N975F/BTU/358780109886445`.
- Current target FOTA result on 2026-07-05: Android `12`, latest
  `N975FXXS9HWHA/N975FOXM9HWH6/N975FXXS9HWH6`.

The port is not a clean Android build. It is a Samsung firmware port that keeps
the old Note10+ vendor/kernel contract while replacing the source OS with a
newer S24 FE One UI build.

## Repository Facts

- `Ocin4ever/EternityROM` default branch is `fifteen`.
- `sixteen` currently points to the same commit as `fifteen`.
- EternityROM v5.x already supports `d2s`, uses UN1CA, and already rebased to
  S24 FE for v5.3.
- `target/d2s/config.sh` keeps the legacy Note10+ layout:
  `TARGET_SUPER_PARTITION_SIZE=0`, `TARGET_OS_FILE_SYSTEM="erofs"`,
  `TARGET_VNDK_VERSION=31`, and `TARGET_HAS_SYSTEM_EXT=false`.
- `ExtremeXT/android_kernel_samsung_exynos9820` branch `llvm1` is the useful
  kernel branch for `d2s`; it has explicit Exynos 9825, old TZDEV, DTB/DTBO,
  and boot image handling.

## Implemented In This Branch

- Added `unica/configs/essi85.sh` as the One UI 8.5 S24 FE source profile.
- Switched `target/d2s/config.sh` to `TARGET_SINGLE_SYSTEM_IMAGE="essi85"`.
- Added `scripts/internal/update_source_metadata.sh`.
- Hooked metadata refresh into `scripts/make_rom.sh` after firmware extraction
  and before workdir creation.
- Added this research file, `CLAUDE.md`, and the d2s test matrix.

## First WSL Alpha Build Result

Built locally on 2026-07-05 from:

- Source: `SM-S721B/EUX`
  `S721BXXSCDZF3/S721BOXMCDZF3/S721BXXSCDZF3`
- Target: `SM-N975F/BTU`
  `N975FXXS9HWHA/N975FOXM9HWH6/N975FXXS9HWH6`
- Kernel artifacts: `boot.img`, `dtb.img`, and `dtbo.img` from the
  `extremekrnl` contract in the d2s workdir.

Final local artifact:

```text
out/EternityROM_v5.5-oneui85-alpha2_@c83e070_20260705_d2s-sign.zip
SHA256: b2bfd6b41d5ab34fcf7d0ce124f3121ec6bbb375962c109a11cc5025a83d91a8
```

Offline verification passed with `unzip -t`. The ZIP contains legacy
non-super block OTA payloads for `system`, `vendor`, `product`, `odm`,
`prism`, and `optics`, plus `boot.img`, `dtb.img`, and `dtbo.img`. This does
not prove the ROM boots; it only proves the package was built and is readable.

## Metadata Refresh Contract

`essi85.sh` contains seed values so `buildenv.sh` can generate `out/config.sh`
before firmware exists locally. After source firmware extraction,
`update_source_metadata.sh` refreshes:

- `SOURCE_CODENAME`
- `SOURCE_API_LEVEL`
- `SOURCE_PRODUCT_FIRST_API_LEVEL`
- `SOURCE_VNDK_VERSION`
- `SOURCE_HAS_SYSTEM_EXT`
- `SOURCE_SUPER_GROUP_NAME`
- selected source feature flags that can be detected from extracted floating
  features or partition files

The script intentionally does not invent values it cannot find. Remaining
feature flags stay seeded from EternityROM's S24 FE profile and must be audited
against the extracted One UI 8.5 firmware.

## Bring-Up Risk Areas

Build-time compromises in the first alpha:

- Framework-level KnoxPatch `SamsungPropsHooks` is disabled because Android 16
  `framework.jar/classes3.dex` reassembly fails on Samsung's very large dex
  type table. Other KnoxPatch pieces remain enabled.
- Platform signature spoofing is skipped when the Android 16
  `InstallPackageHelper.smali` path does not match the Android 15-era patch.
- Some product-feature smali edits are warning-only when the expected Samsung
  implementation class moved or disappeared: `PowerManagerUtil`,
  `EngmodeService$EngmodeTimeThread`, and `SemMdnieManagerService`.
- `scripts/apktool.sh` intentionally restores unchanged dex files when the
  smali tree hash is unchanged. This is a build reliability workaround, not a
runtime feature.
- Keep `APKTOOL_PARALLEL_JOBS=1 APKTOOL_THREAD_COUNT=2` in WSL until the
  build machine proves stable under higher load.
- The recovery installer assert accepts `ro.boot.em.model`, `ro.product.model`,
  or `ro.product.device=d2s` because some TWRP builds omit Samsung's
  `ro.boot.em.model` property.
- The first flashable ZIP wrote all partitions but aborted at cleanup because
  `cleanup.sh` was staged as `scripts/cleanup.sh` and referenced as
  `cleanup.sh`. Alpha2 fixes this by extracting the real ZIP path to `/tmp`,
  making cleanup non-fatal, and validating all `package_extract_file()` sources
  against the ZIP contents during the build.

- VINTF and service-manager mismatches between Android 16 framework and
  Android 12-era Exynos 9825 vendor.
- SELinux denials around vendor HALs, camera, Bluetooth, radio, and TrustZone.
- SamsungCamera regressions: UW `0.5x`, tele, HDR10+, 4K, portrait, and lens
  switching were already sensitive in EternityROM v5.x.
- Graphics stack: Mali/EGL/Vulkan policy must stay conservative because v5.x
  already changed EGL versions to fix camera flicker and portrait problems.
- HFR must stay forced to 60 Hz for Note10+.
- Heavy Galaxy AI services may need trimming if they cause RAM pressure,
  thermal throttling, or persistent crashes.

## Kernel Notes

Use `ExtremeXT/android_kernel_samsung_exynos9820` branch `llvm1` for `d2s`.
The `platform/exynos9825/patches/extremekrnl` module expects a flashable kernel
zip exposing:

```text
files/boot.img
files/dtb.img
files/dtbo.img
```

Do not change that artifact contract during initial bring-up.

## First Alpha Definition

The first alpha is successful only when it:

- boots to setup or launcher on `SM-N975F`;
- keeps SELinux enforcing;
- has working display, touch, storage, Wi-Fi, RIL, audio, and charging;
- produces useful logs for all remaining feature failures;
- does not require modifying unrelated Note10 targets.

## Source Links

- Samsung One UI 8.5 notice:
  `https://www.samsung.com/hk_en/support/newsalert/129598/`
- EternityROM README:
  `https://github.com/Ocin4ever/EternityROM/blob/fifteen/README.md`
- EternityROM changelog:
  `https://github.com/Ocin4ever/EternityROM/blob/fifteen/CHANGELOG.md`
- S24 FE source profile used as seed:
  `https://github.com/Ocin4ever/EternityROM/blob/fifteen/unica/configs/essi.sh`
- d2s target profile:
  `https://github.com/Ocin4ever/EternityROM/blob/fifteen/target/d2s/config.sh`
- ExtremeXT kernel llvm1 README:
  `https://github.com/ExtremeXT/android_kernel_samsung_exynos9820/blob/llvm1/README.md`
