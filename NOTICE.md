# Notice

Impulse ROM is a **modified fork** of EternityROM. This file exists so that
authorship and licensing are unambiguous at a glance; see `README.md` for the
full credits list and `LICENSE` for the complete license text.

## Impulse ROM

Impulse ROM adapts EternityROM's build system and One UI/Android base to the
Samsung Galaxy Note10+ Exynos (`d2s` / `SM-N975F`), tracking a newer One UI
8.5 / Android 16 source than upstream currently ships for this device.
Impulse-specific changes include (non-exhaustively; see
`docs/source-provenance.md` for exact commit-level detail once published):
device/source configuration for the `essi85` profile, DEX-inventory and
ELF/VINTF/audio/multilib validation tooling, several device-specific smali
patches, a reproducible container build path, and installation/rollback
documentation for this device.

**Impulse ROM's own modifications are distributed under GPLv3, in accordance
with upstream's license, and do not replace or relicense upstream's
copyright.** Where Impulse modifies a file that carries an upstream copyright
header, that header is preserved; Impulse's changes are additional
modifications to that file, not a claim of original authorship over the
unmodified portions.

## Upstream

- **EternityROM** — © Ocin4ever and contributors. GPLv3.
  <https://github.com/Ocin4ever/EternityROM>. Impulse ROM is forked from this
  project and would not exist without it.
- **Original ROM build system** — Salvo Giangreco
  (`github.com/salvogiangri`), whose UN1CA-based build system, patches, and
  general design this project's build logic is built on top of. See
  `README.md` for the full upstream credits list, which this file does not
  duplicate.

## Kernel

- **ExtremeKRNL / Exynos kernel work** — ExtremeXT
  (`github.com/ExtremeXT`) and the `Ocin4ever/ExtremeKernel` release
  packaging. GPLv2 (Linux kernel). See `docs/kernel-source.md` for exact
  revision provenance and its currently-unresolved points.
- **KernelSU-Next** — the KernelSU-Next contributors.
  <https://github.com/KernelSU-Next/KernelSU-Next>.

## Samsung

Samsung firmware and proprietary device software are used solely as external
build inputs. They are not Impulse ROM source code, are not redistributed by
this repository, and are not represented as original Impulse work anywhere
in this project. See `docs/proprietary-files.md`.
