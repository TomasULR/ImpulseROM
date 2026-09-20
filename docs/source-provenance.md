# Source provenance

This document maps every Impulse ROM release binary to the exact source used
to build it. It exists so that GPL "corresponding source" obligations and
XDA's request for a source link containing Impulse's own modifications can
both be verified independently by a third party, not just asserted.

Rule for every future release: **do not build from an uncommitted working
tree.** Commit, tag, then build. Record the tag and the resulting artifact
hash in the table below before the artifact is distributed anywhere. Every
row below that predates this rule is marked accordingly.

## Upstream base

- Upstream project: [Ocin4ever/EternityROM](https://github.com/Ocin4ever/EternityROM)
  (branch `fifteen`), GPLv3.
- Impulse's working branch (`bringup/oneui85-d2s`) is based on upstream commit
  `c83e070e` ("scripts: internal: build_flashable_zip.sh: fix zipping
  issues").
- As of this writing, `origin` on the Impulse working checkout is still
  `https://github.com/Ocin4ever/EternityROM.git` — no Impulse-owned remote
  has been published yet. The rows below reference the local branch state;
  the commit hashes will only resolve publicly once Impulse's own fork/remote
  is pushed.

## Releases

### Impulse ROM v1.0 — Alpha 1

| Field | Value |
| --- | --- |
| ROM version | `v1.0-oneui85-alpha1` |
| Distributed filename | `ImpulseROM_v1.0-oneui85-alpha1_@c83e070e-dirty_20260824_d2s-sign.zip` |
| Build date | 2026-08-24 |
| ROM SHA-256 | `0727861f7da3b76cf754992e07699db5c322dce7e1c250a4394093e73e1347b6` |
| Upstream EternityROM base commit | `c83e070e` |
| Impulse source commit | **Not available.** The filename's own `-dirty` suffix records that this build was made from an uncommitted working tree on top of `c83e070e`, and no commit or tag was made at build time. |
| Kernel source repository | `https://github.com/Ocin4ever/ExtremeKernel` (see [kernel-source.md](kernel-source.md)) |
| Kernel release used | `v2.0` (commit `f54c88ef6171ff3c4b5067911d5e8e4a0c62ec17`) |
| KernelSU-Next revision | Recorded submodule pointer `eaab98b7ecb2b131f25b11972b49b2106683c6cc`, **not proven** to be what was actually compiled — see [kernel-source.md](kernel-source.md) for why |
| Other submodule revisions | Not recorded at build time; cannot be reconstructed exactly (see below) |

**What can be proven:** the base upstream commit (from the filename and from
`git log`), the kernel release tag and its recorded KernelSU-Next submodule
pointer (verified directly against GitHub — see `kernel-source.md`), and that
the distributed ZIP's `boot.img`/`dtb.img`/`dtbo.img` are byte-for-byte
identical to the `ExtremeKRNL-Nexus-d2s` v2.0 release asset (the release
asset's own SHA-256, `91309ca7b6bce0edd99734b798ef23faf1e0eb2bd34d3055917e39309894eaba`,
was independently recomputed from a locally-held copy of that exact file and
matches the value pinned in
`platform/exynos9825/patches/extremekrnl/customize.sh`).

**What cannot currently be proven:** the exact state of every ROM-side source
file (patches, `unica/` configs, `scripts/`) at the moment this ZIP was
built. The working tree that produced it was never committed or tagged, and
substantial further bring-up work has been committed to the working tree
since 2026-08-24. **Do not tag the current `bringup/oneui85-d2s` working tree
as `v1.0-alpha1`** — it does not represent the tree that actually produced
this artifact. If an exact reconstruction is later needed, the only path is
locating a preserved snapshot of the working tree from on or before
2026-08-24 (none has been found under `/mnt/Bobo/DEV` or the developer's home
directory as part of this audit); absent that, this row's source-side gap is
permanent and should simply be acknowledged rather than papered over.

Earlier, pre-rebrand local iterations exist under the `EternityROM_v5.5-oneui85-alphaN`
naming (alpha1 through at least alpha8, the last of which is explicitly
marked superseded/rejected in `docs/RELEASE_AUDIT_ALPHA8.md`). These predate
the "Impulse ROM" rebrand and are a **different lineage** from
`v1.0-oneui85-alpha1` above — do not conflate the two when citing "Alpha 1."

### Future releases

For every release going forward, fill in this table from a clean, tagged
commit — never from a dirty tree:

| ROM version | Source tag/commit | Upstream base commit | Kernel repo | Kernel tag/commit | KernelSU-Next commit | Build date | ROM SHA-256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _(next release)_ | | | | | | | |

Suggested process (see [BUILDING.md](../BUILDING.md) for the full build
procedure):

1. Land all intended changes on `bringup/oneui85-d2s` (or its successor
   branch) and commit them — no uncommitted state.
2. Tag the commit (e.g. `v1.0-alpha2`).
3. Record the tag, the upstream base commit it's built on, and the kernel
   release/submodule state it will consume, in the table above, **before**
   building.
4. Build from that tag in a clean checkout (the container build in
   `docker/`/`scripts/build_in_container.sh` is the reproducible path).
5. Hash the resulting artifact and add the hash to the table.
6. Only then distribute the artifact.
