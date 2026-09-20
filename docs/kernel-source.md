# Kernel source (GPLv2)

The Linux kernel is licensed under GPLv2. Impulse ROM does not vendor or
build kernel source itself — the ROM build downloads a prebuilt, checksum-verified
flashable kernel package as a build input. This document records exactly what
is and is not currently provable about that package's source correspondence.
Everything below was verified directly against GitHub on 2026-09-19; nothing
here is guessed.

## Has Impulse modified the kernel?

**No.** `platform/exynos9825/patches/extremekrnl/customize.sh` only downloads,
checksum-verifies, and repackages a prebuilt kernel release. There is no
kernel source tree in this repository and no kernel submodule in
`.gitmodules`. If Impulse modifies kernel source in the future, those
modifications must be published separately under GPLv2 (a public fork of the
kernel repository, with the changes as commits), and this document must be
updated to reflect it.

## Repositories involved

Two distinct repositories are relevant, and they are **not the same
project** — this is a real discrepancy, not a typo, and is called out
explicitly because internal notes (`docs/ROM_RESEARCH.md`) name one while the
build script actually consumes the other:

1. **`https://github.com/Ocin4ever/ExtremeKernel`** — a fork of
   `https://github.com/ExtremeXT/M62-backport`. This is the repository the
   ROM build script actually points at
   (`EXTREMEKRNL_REPO="https://github.com/Ocin4ever/ExtremeKernel/releases"`
   in `platform/exynos9825/patches/extremekrnl/customize.sh`) and where the
   `ExtremeKRNL-Nexus-d2s` flashable zip is published as a GitHub Release
   asset.
2. **`https://github.com/ExtremeXT/android_kernel_samsung_exynos9820`** — a
   large (720k+ commit), actively developed kernel tree for the Exynos9820
   family, with its own `KernelSU` (not `KernelSU-Next`) submodule. This is
   the repository `docs/ROM_RESEARCH.md` names as "the useful kernel branch
   for d2s" (branch `llvm1`).

**Unresolved:** whether `ExtremeXT/M62-backport` (and therefore
`Ocin4ever/ExtremeKernel`) is a fork/downstream of
`ExtremeXT/android_kernel_samsung_exynos9820`, a sibling branch under a
different name, or an unrelated tree that happens to target the same SoC
family. This audit did not find a direct fork/parent link between the two on
GitHub. Resolve this with the ExtremeXT/Ocin4ever maintainers before stating
a single authoritative kernel source repository in public-facing materials.

## What is verified for the `v2.0` kernel release (used by Alpha 1 and Alpha 2)

- Tag `v2.0` on `Ocin4ever/ExtremeKernel` resolves to commit
  `f54c88ef6171ff3c4b5067911d5e8e4a0c62ec17` ("Update build.yml"), confirmed
  via the GitHub API (`git/refs/tags/v2.0`). This is a lightweight tag (points
  directly at a commit, not an annotated tag object).
- At that commit, the `KernelSU-Next` submodule is recorded at
  `eaab98b7ecb2b131f25b11972b49b2106683c6cc`
  (`https://github.com/KernelSU-Next/KernelSU-Next`), confirmed via the
  GitHub API (`contents/KernelSU-Next?ref=f54c88e...`).
- The `ExtremeKRNL-Nexus-d2s.zip` release asset for `v2.0` has SHA-256
  `91309ca7b6bce0edd99734b798ef23faf1e0eb2bd34d3055917e39309894eaba`. This
  exact value is pinned in `platform/exynos9825/patches/extremekrnl/customize.sh`
  and was independently re-verified by hashing a locally-held copy of that
  release asset — **the hashes match.**
- The `boot.img`/`dtb.img`/`dtbo.img` shipped inside the Impulse Alpha 1 and
  Alpha 2 ROM packages are byte-for-byte identical to that same verified
  `v2.0` release asset (per `docs/RELEASE_WORK_20260919.md`'s recorded
  comparison).

## What is NOT verified: the exact KernelSU-Next commit actually compiled in

This is a real, evidenced gap, not a hypothetical one. The commit that tags
`v2.0` (`f54c88e`) is the **same commit** that changed the `build_d2s` job in
`.github/workflows/build.yml` from a pinned submodule checkout to a floating
one:

```diff
  - name: Update submodules
    run: |
      git submodule sync --recursive
-     git submodule update --init --force --recursive
+     git submodule update --init --force --recursive --remote
```

`--remote` means the CI job checks out whatever `KernelSU-Next`'s tracked
branch HEAD is **at the moment the workflow runs**, not the commit recorded
in `ExtremeKernel`'s own git tree. The tree-recorded pointer
(`eaab98b7ecb...`) is therefore a fact about the git tree at tag `v2.0`, but
it is **not proof** of what was actually checked out and compiled during the
CI run that produced the distributed release asset — those can differ if
`KernelSU-Next`'s default branch moved between whenever `eaab98b` was
committed to `ExtremeKernel` and whenever that specific CI run executed.
Concretely: GitHub Actions run `#33` (`Kernel Build Workflow`, triggered at
commit `f54c88e`, 2026-08-08) produced a `d2s` build artifact, which is
consistent with being the run behind the `v2.0` release, but this was not
possible to confirm with certainty (release assets can be attached
independently of a specific workflow run, and this project's Actions run
history only retains a limited window).

**Conclusion: the exact KernelSU-Next commit compiled into the distributed
`v2.0` kernel binaries used by Impulse Alpha 1/Alpha 2 is unresolved.** Do
not state a specific commit as the one used in the binary. If this needs to
be closed out, it requires either an admission from the ExtremeKernel
maintainer of what was checked out at build time, or a reproducible rebuild
of that exact release from the same starting conditions.

## KernelSU vs. KernelSU-Next

These are two different projects. `Ocin4ever/ExtremeKernel` vendors
**KernelSU-Next** (`https://github.com/KernelSU-Next/KernelSU-Next`).
`ExtremeXT/android_kernel_samsung_exynos9820` vendors the original
**KernelSU** project instead. The KernelSU-Next *manager APK* bundled by
Impulse's build (`platform/exynos9825/patches/extremekrnl/customize.sh`,
`INCLUDE_KERNELSU_MANAGER`) is pinned to release `v1.0.9`
(`KernelSU_Next_v1.0.9_12797-release.apk`,
SHA-256 `0013c41c9aeda2699f8a8af840839eb495f89bce7264b5c8fa42152b4c8d9a1e`) —
this is the userspace manager app only, and is a separate fact from the
in-kernel KernelSU-Next driver commit discussed above.

## Recommended action

- Contact the ExtremeKernel maintainer to ask (a) whether `M62-backport`
  is derived from `android_kernel_samsung_exynos9820`/`llvm1`, and (b)
  whether they can state the exact `KernelSU-Next` commit that was actually
  built into the published `v2.0` release assets.
- Until that's answered, publish this document as-is alongside the source —
  it is more credible to XDA and to GPL scrutiny to show verified, honestly
  bounded provenance than to assert a single unverified commit.
- For any future kernel release Impulse consumes, remove the `--remote` step
  dependency by asking upstream to pin the submodule before tagging, or by
  independently re-deriving and recording the submodule commit at the moment
  of consumption.
