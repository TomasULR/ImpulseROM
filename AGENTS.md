# Codex Handoff

This workspace is a first bring-up branch for a Galaxy Note10+ `d2s`
EternityROM port using an S24 FE One UI 8.5 source firmware.

## Current Branch

- Base repo: `Ocin4ever/EternityROM`
- Base branch: `fifteen`
- Working branch: `bringup/oneui85-d2s`
- Target device: `d2s / SM-N975F`
- Source profile: `unica/configs/essi85.sh`
- Target config: `target/d2s/config.sh`

## Important Rules

- Do not expand scope to `d1`, `d2x`, or `d2xks` until `d2s` boots and
  passes the test matrix.
- Keep the existing `platform/exynos9825` compatibility layer as the
  baseline. The first goal is a booting alpha, not a cleanup rewrite.
- Keep SELinux enforcing. If boot needs permissive mode, treat that as a bug
  to root-cause with logs.
- Proprietary Samsung blobs are local-build inputs. Do not commit newly
  extracted firmware blobs unless the project explicitly decides to handle
  redistribution.

## Build Notes

This sparse checkout contains the source files changed for the bring-up, not
the full prebuilt blob tree. For an actual build, expand the checkout and init
submodules:

```bash
git sparse-checkout disable
git submodule update --init --recursive
source buildenv.sh d2s
m --force
```

The build is expected to run in a Linux/WSL environment with the dependencies
listed by `scripts/utils/build_utils.sh`. Firmware extraction requires mount
or FUSE access and may request sudo.

On the Kubuntu workstation, keep the active checkout on ext4. The archived
workspace under `/run/media` is NTFS and cannot preserve all tracked symlinks
and executable bits. A pinned Ubuntu 24.04 build container is available:

```bash
./scripts/build_in_container.sh --tools-only
./scripts/build_in_container.sh --force
```

The container runs as UID/GID 1000, matching the workstation user. It is
privileged only because firmware extraction mounts read-only partition images.

For the first WSL alpha build, keep apktool parallelism conservative:

```bash
source buildenv.sh d2s
APKTOOL_PARALLEL_JOBS=1 APKTOOL_THREAD_COUNT=2 TERM=dumb ./scripts/make_rom.sh
```

Higher parallelism caused WSL service instability and can corrupt long-running
APK/JAR rebuild sessions.

## New Bring-Up Behavior

`target/d2s/config.sh` now points at `TARGET_SINGLE_SYSTEM_IMAGE="essi85"`.
The `essi85` profile seeds S24 FE One UI 8.5 values. After firmware extraction,
`scripts/internal/update_source_metadata.sh` refreshes build-critical source
metadata in `out/config.sh` from the extracted firmware tree.

The refresh script writes an audit file:

```text
out/source_metadata_essi85.txt
```

Check that file before debugging framework/vendor problems.

## First Alpha Build Notes

- `scripts/apktool.sh` now supports Android 16 dex header/API mapping and
  restores unchanged original `classes*.dex` files from a decode cache. This
  avoids reassembling very large Samsung dex files that exceed smali limits.
- The KnoxPatch module is now ENABLED. Its ICD/SAK bypasses land and are
  verified in the built code, but they do **not** fix Samsung Health, which
  still returns `KnoxInitResult(mCode=-4112)` /
  `OOBE_ERROR_KNOX_ROOTING_DEVICE`. See `docs/FIXES_IMPULSE.md` section 3 for
  what was ruled out and why the `SamsungPropsHooks` pair (the mechanism that
  would actually fix it) is deliberately left off.
  Two of its patches stay off as `*.patch.disabled`:
  `framework.jar/0001-Introduce-SamsungPropsHooks.patch` (forces
  `classes3.dex` reassembly and blocks the build) and
  `knoxsdk.jar/0001-Introduce-SamsungPropsHooks.patch`, which calls
  `Lcom/ocin4ever/spoof/SamsungPropsHooks;` — a class only the framework.jar
  patch supplies. Enabling knoxsdk without framework.jar raises
  `NoClassDefFoundError` on every Knox EDM query, so the two move together.
- `scripts/internal/build_flashable_zip.sh` was fixed to write OTA
  `post-sdk-level=36` and to emit the final named ZIP directly in `out/`.
- Recovery device asserts now accept `ro.boot.em.model`, `ro.product.model`,
  or `ro.product.device=d2s` to avoid false aborts in TWRP builds that do not
  expose Samsung's boot model property.
- The cleanup step now extracts `scripts/cleanup.sh` to `/tmp/cleanup.sh`,
  runs it through a non-fatal `ifelse`, and validates every
  `package_extract_file()` source against the generated ZIP at build time.
- The generated ZIP is build-verified only. Device boot/HAL status is unknown
  until it is flashed on an actual `SM-N975F`.

## Rebrand: Impulse ROM

This tree is now branded **Impulse ROM** (`v1.0-oneui85-alpha1`). Upstream
attribution to EternityROM / Ocin4ever, Salvo Giangreco and ExtremeXT is kept
deliberately — GPLv3 requires it, and on XDA it is what separates a legitimate
fork from a rip. Do not strip copyright headers.

Builds now sign with `security/impulse_platform.{pk8,x509.pem}` (RSA 4096 /
SHA-256), which makes `ROM_IS_OFFICIAL` true. **The private key is gitignored
and exists only on this machine — back it up offline.** Without it no future
build can sign an in-place update for devices already running Impulse.

Note the flashable ZIP itself is still unsigned; `PRIVATE_KEY_PATH` and
`PUBLIC_KEY_PATH` in `build_flashable_zip.sh` are computed but never used.
Distribute a SHA-256 (and ideally a detached GPG signature) alongside releases.

## Read Next

- `docs/FIXES_IMPULSE.md` — diagnosed defects, evidence and applied fixes
- `docs/INSTALL.md` — clean-install guide for end users
- `docs/XDA_RELEASE_GUIDE.md` — release checklist and GPL obligations
- `docs/BLOG_POST_CZ.md` — Czech blog copy (do not publish untested)
- `docs/ROM_RESEARCH.md`
- `docs/TEST_MATRIX_D2S.md`
