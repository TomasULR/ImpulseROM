# Proprietary files

This document distinguishes three categories of content involved in building
Impulse ROM, so it's unambiguous what is actually Impulse/GPL source versus
what is a proprietary input the build consumes but never redistributes:

1. **GPL/open-source code controlled by this project** — everything tracked
   in this git repository (scripts, patches, device configs, build logic,
   documentation). This is the "corresponding source" this repository exists
   to publish.
2. **External open-source dependencies** — the `external/*` git submodules
   (`android-tools`, `apktool`, `erofs-utils`, `img2sdat`, `omcdecoder`,
   `samloader`, `signapk`, `smali`), each pinned to an exact upstream commit
   in `.gitmodules`/the submodule index and licensed under their own
   respective (non-GPLv3) licenses — see the "Licensing" section of the main
   `README.md`.
3. **Proprietary Samsung firmware/software**, used only as a local build
   input and never committed to this repository or redistributed by it.

None of the proprietary files below are ever committed. `out/` (the build
working directory, where all extracted/downloaded proprietary content lands)
is excluded by `.gitignore` and was confirmed, as part of this audit, to
contain no tracked or staged files in either working checkout.

## Proprietary inputs this build requires

| Input | Source identifier used by the build | How it's obtained |
| --- | --- | --- |
| Galaxy S24 FE One UI 8.5 source firmware | `SM-S721B/EUX/351273090276500` (`unica/configs/essi85.sh`, `SOURCE_FIRMWARE`) | Downloaded via `external/samloader` from Samsung's FUS servers, using this project's build scripts (`scripts/download_fw.sh`, `scripts/extract_fw.sh`) |
| Galaxy S24 FE (arm32/multilib donor) firmware | `SM-S711B/EUX/355195301615976` (`unica/configs/essi85.sh`, `MULTILIB_FIRMWARE`) | Same mechanism; supplies 32-bit HAL objects the arm64-only S24 FE source lacks, validated by `scripts/internal/validate_multilib_firmware.py` before use |
| Galaxy Note10+ target stock firmware | `SM-N975F/BTU/358780109886445` (`target/d2s/config.sh`, `TARGET_FIRMWARE`) | Same mechanism; supplies the vendor/kernel-compatible base for the target device |
| Other supported-device donor/target firmware (`d1`, `d1xks`, `d2x`, `d2xks`, and the other `SM-*` donors in `scripts/internal/update_prebuilt_blobs.sh`) | Various `<model>/<CSC>/<IMEI-or-serial>` strings, all pre-existing in upstream EternityROM | Same mechanism |
| Samsung Notes app | Pinned version/SHA-256 in `unica/mods/preload/essi85/customize.sh` | Downloaded from the Galaxy Store at build time, signature-verified with `apksigner` before installation as a system app |
| Samsung Camera app | Whatever `SamsungCamera.apk` ships in the extracted source/target firmware | Carried through from the extracted firmware tree; **not rebuilt or modified by Impulse** — see the camera note below |
| ExtremeKRNL kernel package (`boot.img`/`dtb.img`/`dtbo.img`) | `ExtremeKRNL-Nexus-d2s` release, pinned to tag/checksum in `platform/exynos9825/patches/extremekrnl/customize.sh` | Downloaded from `https://github.com/Ocin4ever/ExtremeKernel/releases`; see `docs/kernel-source.md` |
| KernelSU-Next manager APK | Pinned release/checksum in the same `customize.sh` | Downloaded from `https://github.com/KernelSU-Next/KernelSU-Next/releases` |

### On the `<model>/<CSC>/<IMEI-or-serial>` identifiers

`scripts/utils/firmware_utils.sh` documents that Samsung's firmware update
service (FUS) only checks that a supplied IMEI/serial matches the target
model — not that it belongs to any particular device or person — and
explicitly supports partial (TAC-only) IMEIs for this reason. Every such
identifier found anywhere in this codebase during this audit (in
`unica/configs/*.sh`, `target/*/config.sh`, and
`scripts/internal/update_prebuilt_blobs.sh`) was traced to a value that
**already exists, unchanged, in upstream EternityROM's public repository
history** — Impulse has not introduced a new one. They are firmware-locator
values, not credentials, but if the project ever wants to remove ambiguity
entirely, replacing full 15-digit values with documented 8-digit TACs (which
`firmware_utils.sh` already accepts) would be a reasonable low-cost
hardening for a future change, separate from this publication.

## Directories that must never be published

These currently live outside both git checkouts and must stay there:

- `/mnt/Bobo/DEV/oneui85-donors/` — appears (by filename) to be genuine
  Samsung retail firmware.
- `/mnt/Bobo/DEV/d2s-rollback-20260718/` — confirmed genuine Samsung stock
  firmware (`AP_`/`BL_`/`CP_`/`CSC_`/`HOME_CSC_` `.tar.md5` files) kept as an
  Odin flash-back fallback.
- `/mnt/Bobo/DEV/efs-backup-20260705/` and any other EFS-family backup —
  raw per-device partition images; never publish these under any
  circumstance.
- `out/audit-20260919/` (and any sibling `out/audit-*`/`out/logs/*`
  directory) inside the working checkout — private diagnostic material
  (device logs, an extracted system image, extracted proprietary APKs, a
  Python virtualenv). Already excluded by `.gitignore` via the blanket `out/`
  rule; treat that as a safety net, not a substitute for not adding it to any
  publish/share step by hand.

## Camera app note

Impulse Alpha 1's distributed Samsung Camera APK has a confirmed signature
defect (Android SDK 37 `apksigner` rejects it — the signed `MANIFEST.MF`
references resource entries that are missing from the APK). **This is a
proprietary-binary integrity problem, not a source-publication problem, and
it must not be worked around by committing a Camera APK (fixed, stock, or
otherwise) into this repository.** Track and fix it as a build-input/build-gate
issue (see `scripts/internal/validate_multilib_firmware.py` and the project's
own camera build-gate work) — the resolution belongs in how the build
acquires or verifies its Camera input, never in the GPL source tree.
