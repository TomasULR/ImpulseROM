# EternityROM One UI 8.5 d2s alpha8 release audit

Audit date: 2026-08-02

> **SUPERSEDED — ALPHA8 IS REJECTED.** A later full AArch64 vendor/HAL audit
> found Android 15 graphics-core contamination that the original 32-bit/audio
> gate did not cover. Keep this report as evidence of the gates alpha8 did pass,
> but do not use its earlier offline-approval decision to authorize a flash.

## Candidate identity

```text
file:   EternityROM_v5.5-oneui85-alpha8_@c83e070e-dirty_20260802_d2s-sign.zip
size:   5860324536 bytes
sha256: db666df3b21b89471f78c806b812de84e8b622ed05d96e440a3935e87955f058
source: SM-S721B/EUX S721BXXSCDZF3/S721BOXMCDZF3/S721BXXSCDZF3
arm32:  SM-S711B/EUX S711BXXSGGZF2/S711BOXMGGZF2/S711BXXSGGZF2
target: SM-N975F/BTU N975FXXS9HWHA/N975FOXM9HWH6/N975FXXS9HWH6
sdk:    36
oneui:  80500
```

The Git suffix is `@c83e070e-dirty`, so the artifact is identified by its full
SHA-256, not by the commit alone. The historical `-sign.zip` suffix does not
mean that the outer ZIP has a cryptographic signature.

## Build and package result

- Clean forced build completed in 12 minutes 37 seconds.
- Python unit tests: 90/90 passed.
- Relevant shell scripts pass `bash -n`; `git diff --check` passes.
- ZIP CRC passed for every member.
- The ZIP contains exactly the 33 allowed members, with no duplicate, absolute,
  parent-traversal or backslash paths.
- The updater references only the fixed d2s targets `system`, `vendor`,
  `product`, `odm`, `prism`, `optics`, `boot`, `dtb` and `dtbo` and retains the
  SM-N975F/d2s device guard.
- Every transfer list is version 4, contains only full `new` ranges and covers
  its image from block zero to the declared final block without gaps or
  overlaps. Every Brotli stream independently decodes to EOF.

| Partition | Blocks | Reconstructed bytes | Filesystem check |
| --- | ---: | ---: | --- |
| system | 2,106,241 | 8,627,163,136 | `e2fsck -fn` RC 0 |
| vendor | 193,315 | 791,818,240 | `fsck.erofs` RC 0 |
| product | 217,394 | 890,445,824 | `fsck.erofs` RC 0 |
| odm | 173 | 708,608 | `fsck.erofs` RC 0 |
| prism | 22,082 | 90,447,872 | `e2fsck -fn` RC 0 |
| optics | 1,216 | 4,980,736 | `e2fsck -fn` RC 0 |

Expandable-partition headroom is 810,020,864 bytes for system, 643,555,328
bytes for prism and 26,476,544 bytes for optics. The reconstructed system image
contains real `/dev`, `/proc` and `/sys` directories required by
system-as-root.

## Reconstructed-content gates

All content gates below were repeated against files extracted from the final
ZIP, not only against the pre-package work directory:

- 432/432 packaged APK signatures verify, and the packaged APK path set exactly
  equals the assembled path set;
- four property-context files and 1,831 declarations merge without a conflict;
- 452 vendor ARM32 ELF files have the required API36 runtime entry points;
- all seven historically gated early boot-core files and SamsungCamera match their pinned S721B
  source files;
- target FCM is truthfully 3, all 11 required VINTF instances are satisfied by
  91 declarations, and 21 legacy sysfs rules use accepted Android 16 grammar;
- the complete S711B multilib input gate passes 69/69 checks;
- the packaged `services.jar` preserves both logical DEX units and the
  PackageManager/WindowManager sentinel locations;
- 34 executable/dlopen ELF roots have zero missing libraries, zero namespace
  blocks, zero missing versioned symbols and zero missing strong unversioned
  symbols. Six duplicate-route notices and 14 base-symbol fallbacks are
  deterministic, resolved warnings;
- boot, DTB and DTBO match both the packaged metadata and pinned work-dir files.

Fixed image hashes:

```text
boot  51743dd78d5e93eb680e1772c548b60ba2d65e92c1ae98b5876db6a4ee2b0651
dtb   72d770e85fad3ba349498cd118bc21f30a95e591cc86ada07593c23d17aaff4b
dtbo  e5c0317f3789a5202107125af6ffb323166d53384495adfe34e5d34c2e0adc9f
```

## Audio result

Alpha7 was rejected because the d2s vendor declared HIDL audio 5.0 while the
API36 framework has adapters for HIDL 6.0/7.x and AIDL, not 5.0. Alpha8 adds a
pinned S711B Android 16/VNDK31 HIDL 6.0 wrapper over the unchanged N975F
Exynos9825 hardware HAL and a coherent 32/64-bit spatializer pair.

The packaged audio audit passes 16/16 contract checks:

- 13/13 bridge/spatializer files match the multilib donor;
- 12/12 hardware-facing files match the N975F target firmware;
- VINTF, service descriptors, init identity/restart behavior, SELinux
  hwservice mapping, policy XIncludes and non-optional effect providers close;
- every 32-bit audio HAL and sound-effect library passes recursive dependency
  and exact/strong-symbol validation;
- `audio.primary.exynos9825.so` closes across 48 ELF objects and 315 dependency
  edges with 1,531/1,531 exact versioned and 2,055/2,055 strong unversioned
  symbols.

The two warnings are stock-optional stale entries for absent
`libplaybackrecorder.so` and `libgearvr.so`; neither is an active required
provider. Audio is structurally ready for first boot, but real routes and
microphones are not declared working until the live matrix passes.

Machine-readable packaged reports are retained under:

```text
out/audit-alpha8-db666df3/audio_contract_packaged.json
out/audit-alpha8-db666df3/elf32_closure_packaged.json
```

## Rollback and superseded release decision

Both five-file stock Odin sets and both three-image protected EFS backup sets
were rehashed on 2026-08-02 and match the recorded values. The remaining
no-flash gates need the physical phone: copy/recheck the known-good ROM, dump
and hash installed recovery, enter Recovery and Download Mode read-only, check
battery/cable and obtain approval for the exact alpha8 SHA-256.

The original audit classified alpha8 as offline-approved. That decision is now
withdrawn. The expanded validator audited 333 AArch64 process/dlopen roots and
found six failing roots, all reaching the Android 15 `libui.so` dependency on
absent `android.hardware.graphics.common-V5-ndk.so`. A new build must replace
the five contaminated graphics-core files with a coherent API36
QHD/ultrasonic stack and pass both ABI gates before the phone procedure in
[FLASH_TEST_D2S.md](FLASH_TEST_D2S.md) is allowed. One UI 9 remains out of
scope until the corrected One UI 8.5 build passes the live hardware matrix.

The selected post-alpha8 implementation preserves the five exact S721B DZF3
source files and expands the source-hash gate from seven to twelve
boot/graphics-core files. A reversible reconstructed-filesystem audit of that
choice passed all 333 ELF64 roots; this does not retroactively approve alpha8.
