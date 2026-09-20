# Building Impulse ROM

This documents what's needed to reproduce an Impulse ROM build for the
Galaxy Note10+ Exynos (`d2s` / `SM-N975F`). It covers the currently-supported
device only; other targets inherited from upstream EternityROM follow the
same mechanism with a different `target/<codename>/config.sh`.

## Host environment

- Linux, or WSL2 on Windows (the project's own bring-up was done on both;
  see `CLAUDE.md`/`AGENTS.md` for WSL-specific notes such as limiting
  `apktool` to a single thread on constrained CI/VM environments).
- A container-based build is also available and is the recommended
  reproducible path — see "Container build" below.

## Dependencies (native/host build)

Checked automatically by `scripts/utils/build_utils.sh`; install whatever is
missing for your distribution:

```text
awk basename bc brotli cat clang cmake cp curl cut dd dirname du zip zstd
file getfattr git go grep head java ln lz4 make md5sum mkdir mount mv
pcre2test perl protoc python3 rm sed sha1sum sort stat tail tar touch tr
truncate umount unzip wc whoami xargs xxd 7z
```

Firmware extraction additionally needs mount/FUSE access and may require
`sudo`.

## Container build (recommended)

`docker/Dockerfile` (Ubuntu 24.04, pinned by digest) plus
`scripts/build_in_container.sh` provide a reproducible build environment with
the full toolchain pre-installed. Refuses to run as root on the host side.

```bash
scripts/build_in_container.sh --tools-only   # build the builder image only
scripts/build_in_container.sh --shell        # interactive shell in the image
scripts/build_in_container.sh                # full ROM build (default mode)
```

## Repository / submodule initialization

The `bringup/oneui85-d2s` branch is currently checked out **sparse** in at
least one known local copy of this repository (only the files touched by the
d2s bring-up are present). A sparse, uninitialized-submodule checkout **is
not sufficient to build** — before building, expand it:

```bash
git sparse-checkout disable
git submodule update --init --recursive
```

Confirm with `git sparse-checkout list` (should print nothing / be disabled)
and `git submodule status` (no leading `-` on any submodule) before
proceeding. Building from a still-sparse checkout will fail in confusing
ways rather than a clear error, since large parts of `platform/`, `unica/`,
and `external/` simply won't exist on disk yet.

## Proprietary firmware input

This build downloads Samsung firmware as an input at build time; it is never
committed to this repository. See `docs/proprietary-files.md` for exactly
which packages are required and how the build obtains them
(`external/samloader`, driven by `scripts/download_fw.sh`/`extract_fw.sh`
using the `SOURCE_FIRMWARE`/`TARGET_FIRMWARE`/`MULTILIB_FIRMWARE` values in
`unica/configs/essi85.sh` and `target/d2s/config.sh`).

## Target device and build command

```bash
source buildenv.sh d2s
m --force
```

Key environment variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `SOURCE_METADATA_AUTODETECT` | After firmware extraction, re-derive build-critical source metadata (API level, VNDK version, feature flags, …) from the extracted tree instead of trusting the seed values in `unica/configs/essi85.sh` | `true` in `essi85.sh` |
| `INCLUDE_KERNELSU_MANAGER` | Whether to preload the KernelSU-Next manager APK | `false` (boot-minimal profile) |
| `IMPULSE_SIGNING_KEY_DIR` | Where `scripts/build_in_container.sh` looks for `impulse_platform.pk8`/`.x509.pem` | `$HOME/impulse-keys` |
| `ONEUI85_BUILDER_IMAGE` | Container image tag for the reproducible build | `impulserom-oneui85-builder:ubuntu24.04` |

See `docker/Dockerfile` and `scripts/build_in_container.sh` for the rest of
the container-mode build-time switches (`KEEP_SIGNED_APKS_STOCK`,
`ENABLE_SCOPED_PLATFORM_APK_REBUILDS`, `PATCH_DRIFT_POLICY`,
`IMPULSE_REBUILD_SECSETTINGS`).

## Output

Build output, extracted firmware, logs, and all other generated content land
under `out/`, which is `.gitignore`d in full and must never be committed or
published (see `docs/proprietary-files.md`).

## Signing

- **Development/test builds** fall back to the standard, publicly-known AOSP
  test key pair (`security/aosp_platform.pk8`/`.x509.pem`, already tracked in
  this repository — this is the same test key shipped in AOSP itself, not a
  secret).
- **Release builds** require Impulse's own private platform key
  (`security/impulse_platform.pk8`/`.x509.pem`), which is intentionally
  **not published** — see `.gitignore`. It must exist locally (default
  `$HOME/impulse-keys`, overridable via `IMPULSE_SIGNING_KEY_DIR`) and is
  never checked into any repository. Losing it means future in-place update
  signing for devices already running an Impulse release build becomes
  impossible; back it up offline, not in Git, not in any CI artifact.

## Recording provenance

Before distributing any build, follow the process in
`docs/source-provenance.md`: commit and tag the exact source state, record
the tag, the upstream/kernel commit references, and the resulting artifact's
SHA-256, and only then publish the artifact. Do not build a release from an
uncommitted working tree.
