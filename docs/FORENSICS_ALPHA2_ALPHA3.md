# d2s One UI 8.5 Failure Analysis

This note separates confirmed failures from hypotheses. It is the baseline for
the API 36 bring-up and must be updated whenever a candidate is flashed.

## Confirmed installer failure in the first ZIP

The first recovery install wrote the OS partitions and kernel images, then
aborted during final cleanup. The ZIP stored `scripts/cleanup.sh`, while the
updater referenced `cleanup.sh` and then tried to set metadata on
`/scripts/cleanup.sh`. TWRP returned updater error 25 after the destructive
writes had already completed.

The installer now stages and executes the real ZIP path, treats cleanup as
non-fatal, and validates every `package_extract_file()` source against the ZIP
at build time.

## Confirmed alpha2 boot failure

Alpha2 was installed after a real Format Data. The TWRP log shows fresh F2FS,
successful partition writes, and updater return code 0, so stale `/data` was
not the cause.

Boot reached second-stage Android init:

- system, vendor, product, odm, prism, and optics mounted;
- split SELinux policy compiled and loaded;
- PID 1 then aborted while serializing merged property contexts.

The fatal message was:

```text
Unable to serialize property contexts: Duplicate prefix match detected for
'init.svc.vendor.wvkprov_server_hal'
```

The four cross-partition conflicts found offline were:

```text
init.svc.vendor.wvkprov_server_hal
ro.product.first_api_level
ro.telephony.sim_slots.count
service.bootanim.exit
```

The later kernel panic was a consequence of PID 1 dying, not evidence that the
kernel, DTB, or DTBO had failed. Alpha2 and alpha3 use byte-identical kernel,
DTB, and DTBO images.

## Alpha3 status

Alpha3 removes the four conflicting Android 16 `system_ext` declarations and
passes offline property-context validation. It was built and ZIP-tested but
was never flashed, so it must not be described as booting or functional.

Offline extraction later proved that alpha3 also had a second, independent
boot blocker. Its system image was still arm64-only even though the retained
d2s vendor is not:

- `/system/bin/linker` was absent;
- `/system/lib/{libc,libdl,libm}.so` were absent;
- `com.android.runtime.apex` had no 32-bit linker or bionic payload;
- `com.android.i18n.apex` had no 32-bit ICU payload;
- `/system/lib` contained only 16 ARM32 ELF objects, versus 736 in the selected
  Android 16 multilib source.

All eight executable d2s vendor services below declare
`PT_INTERP=/system/bin/linker`, so none of them could have started in alpha3:

```text
vendor/bin/boringssl_self_test32
vendor/bin/wvkprov
vendor/bin/hw/vendor.samsung.hardware.camera.provider@4.0-service
vendor/bin/hw/android.hardware.audio.service
vendor/bin/hw/vendor.samsung_slsi.hardware.iva@1.0-service
vendor/bin/hw/android.hardware.media.omx@1.0-service
vendor/bin/hw/android.hardware.drm@1.3-service.widevine
vendor/bin/hw/android.hardware.cas@1.2-service
```

## Additional blockers found before alpha4

Alpha2 died early enough to hide two later runtime problems. The first is now
confirmed directly from the alpha3 partition image:

1. d2s selects the new `essi85` profile, but the legacy multilib compatibility
   module accepted only `qssi` and `essi`. The target vendor contains 32-bit
   camera, audio, OMX, DRM, CAS, IVA, and provisioning services. A ROM without
   an API 36 32-bit linker/bionic layer cannot provide those core functions.
2. The active `knoxsdk.jar` patch called
   `com.ocin4ever.spoof.SamsungPropsHooks`, while the framework patch defining
   that class was disabled. This could throw `NoClassDefFoundError` in Knox or
   enterprise paths.

Alpha4 therefore uses Samsung's current Android 16 S23 FE firmware as a local
multilib extraction input, validates vendor ELF32/runtime entry points, and
gates the incomplete KnoxPatch for first boot.

A namespace-aware recursive audit of the real alpha3 vendor against the S711B
GZF2 runtime, i18n, system libraries, and VNDK31 APEX resolved all `DT_NEEDED`
edges for the eight processes: 0 missing libraries and 0 namespace-blocked
direct dependencies. It checked 17,012 versioned imports: 16,998 matched their
exact symbol version, 14 had an exported unversioned base-symbol fallback, and
0 were unresolved. Those 14 remain a device-boot warning, not an offline
missing-symbol failure.

The VNDK31 APEX already shipped in alpha3 and was bit-identical to GZF2; the
missing runtime/system 32-bit layer was the fault. Because 53 library basenames
exist in more than one namespace, alpha4 must also retain
`ro.vndk.version=31`, the VNDK31 APEX, and the target vendor-first linker route.

The implementation was tightened after extraction proved that GZF2 contains
736 top-level `/system/lib` files while the old API 35 prebuilt tracked only
216. Alpha4 therefore consumes the complete extracted GZF2 multilib tree as a
local `SOURCE_EXTRA_FIRMWARES` input; it does not commit or incrementally mix
proprietary firmware blobs.

## Confirmed fixed-partition ceiling

Alpha2's successful TWRP postinstall expanded `/system` to exactly 2,304,000
4096-byte blocks, or 9,437,184,000 bytes. The reconstructed alpha3 system image
was clean ext4 with 2,199,511 blocks and only 6,635 free blocks. Its serialized
image occupied 9,009,197,056 bytes, leaving 427,986,944 physical bytes before
the repartitioned device limit.

The API 36 multilib source adds a larger `/system/lib` plus multilib runtime and
i18n APEX packages. The ZIP builder now hard-fails if the generated system
image exceeds the measured physical ceiling. TWRP also proved the fixed prism
and optics ceilings as 734,003,200 and 31,457,280 bytes respectively; those are
validated in the same pre-packaging gate.

## First-boot scope

The initial API 36 candidate keeps the d2s kernel, DTB/DTBO, vendor hardware
stack, modem contract, camera base, S Pen, display, fingerprint, NFC, CSC, and
basic Bluetooth profiles. Cross-device Android 15 AI/OAT, MIDAS,
protected-content, AppLock, wallpaper, preload-download, and boot-state spoof
mods are gated temporarily.

Features are restored only after a stable boot, in small groups with logs. A
new Android security patch date from the donor does not upgrade the old d2s
kernel, modem, TrustZone, or vendor patch level.

## Fourth confirmed defect class: silent patch drift and platform re-signing

The first full alpha4 build run exposed a fourth defect that affected every
earlier alpha. `APPLY_PATCH` discarded the real `patch` exit status (it
returned the status of `cd -`), so patches that failed against the new
API 36 source were reported as applied. 31 framework patches silently drifted,
so earlier alphas shipped a largely un-patched framework. `APPLY_PATCH` now
does a `--dry-run` at fuzz 0 first, applies only on success, never leaves a
partial apply, and records each outcome in `out/skipped_patches.tsv`.

Once patch status was honest, a second problem surfaced. The build decoded
every Samsung platform APK it intended to patch, then rebuilt and re-signed it
with the ROM key **even when every patch for that APK had drifted and been
skipped**. Substance unchanged, signature lost. Samsung platform apps
(SystemUI, SettingsProvider, SecSettings, ...) hold signature-level permissions
granted by the Samsung-signed framework; re-signing them with a foreign key
strips those permissions and destabilises or breaks boot. The custom-platform-
signature framework patch that would make the ROM key trusted had itself
drifted and never applied, so nothing caught the re-signed apps. This is the
most likely source of the "somehow didn't work" instability beyond the two hard
alpha2/alpha3 stops.

The first alpha4 run reproduced it exactly: 9 platform APKs were re-signed, but
only 1 (`SecSettings`) had a single genuinely-applied patch; the other 8 were
re-signed with no substantive change.

Fix: `apktool.sh` now hashes the decoded tree and, when no customization
changed it, keeps the original Samsung-signed APK untouched instead of
rebuilding. Combined with gating the one cosmetic SecSettings patch, a clean
build re-signs zero platform APKs (`signing_count=0`) and rebuilds only the
unsigned framework JARs it genuinely adapts.

Note: `platform/exynos9825/patches/camera/system/priv-app/SamsungCamera.apk`
was briefly suspected of being a stale build artifact overlaid into the work
dir. It is not — it is committed upstream (git history "camera: fixup camera
icon"), is Samsung-signed with the same platform cert as the S24 FE firmware,
and is deliberately overlaid by `apply_modules` as the exynos9825 camera. There
is no work-dir staleness bug; module-overlaid files simply carry the git
checkout mtime, not the firmware mtime.

## alpha4, first flash attempt: confirmed bootloop, root cause found

The first alpha4 candidate (`..._20260719_d2s-sign.zip`,
`sha256:593a35b1...`) was flashed. TWRP reported install return code 0, but
the device bootlooped. `/proc/last_kmsg` and `/proc/sec_log` were pulled from
the device afterward.

A pasted third-party summary claiming the cause was a duplicate
`wvkprov_server_hal` property context (the alpha2 defect) did **not** match
this device's actual log: `grep` for the exact strings it quoted
("Duplicate prefix match", "InitFatalReboot", signal 6) found nothing in the
real `sec_log`. That summary was not used; the real log was.

The real `sec_log` (a fixed 2 MiB ring buffer) showed second-stage init
failing to load `build.prop` from **every** partition (`/system`, `/vendor`,
`/product`, `/odm`) with `ENOENT`, immediately after `[libfs_mgr]` reported
each of those mounts as `Success`. Mounts succeeding while their own
`build.prop` is unreadable pointed at a path mismatch, not a mount failure.

This was confirmed structurally, not by re-reading the (partly bit-corrupted)
early-boot log region:

- The device's real boot fstab, extracted from the flashed `boot.img`'s own
  ramdisk (`unpack_bootimg`, not the log), mounts `system`/`vendor`/`product`/
  `odm` at conventional paths (`/system`, `/vendor`, ...), **not** at real
  root (`/`). The vendor-partition `fstab.exynos9825` doesn't even list these
  partitions; only the ramdisk copy does.
- `$WORK_DIR/system` (root of the previous `system.img`) is a genuine
  system-as-root tree: absolute symlinks (`bin -> /system/bin`,
  `etc -> /system/etc`, `init -> /system/bin/init`) that only resolve if the
  partition is mounted at real `/`. The real Android content
  (`build.prop`, `framework/`, ...) lives one level deeper, at
  `$WORK_DIR/system/system/`.
- `extract_fw.sh`, `create_work_dir.sh`, and `build_fs_image.sh` (which
  hard-coded `MOUNT_POINT="/"` for the system partition, matching upstream
  AOSP's `build_image.py` system-as-root convention) were all internally
  consistent with each other and with the S24 FE donor, which genuinely is
  system-as-root. The mismatch was entirely between that assumption and this
  specific target device's actual (conventional) fstab.

Mounting a system-as-root image at a conventional `/system` mount point would
put every real file one path level too deep (`/system/system/build.prop`
instead of `/system/build.prop`), which looked like a match for the observed
failure.

**This diagnosis turned out to be wrong** — see the correction below. It
reached a plausible-looking conclusion from real structural evidence
(the fstab really does say `/system`), but missed a decisive fact only
visible in the actual boot log: this specific `init` binary performs a real
`SwitchRoot("/system")` regardless of what the fstab's `mnt_point` field
says, so the original system-as-root packaging was already correct for it.

## alpha4, second flash attempt: the mount-point fix was wrong, reverted

The "corrected" candidate above (`sha256:a7188a6d...`, flat `/system`
packaging) was flashed and **also bootlooped**. Fresh `/proc/last_kmsg` and
`/proc/sec_log` were pulled again.

Sanity check first: `TWRP` was used to mount the physical `system`
partition read-only (`/system_root`, `ext4`) and `build.prop` was read
directly from it — confirming the flat-packaged content really was what got
flashed (`ro.eternityrom.version=v5.5-oneui85-alpha4`), so this was not a
stale-file mixup.

The new `sec_log` showed the exact same
`Couldn't load property file '/system/build.prop'` cascade as before, which
initially looked like the fix hadn't taken effect. It had — that cascade
came from a *different, unrelated* boot session further along in the same
ring buffer, one whose log explicitly states
`init: First stage mount skipped (recovery mode)`. That session never
mounts any partition at all (by design — it's a recovery-mode init path,
most likely triggered by the bootloader after repeated crash-reboots), so
of course it can't read `build.prop`. It is not evidence about the ROM.

The real, relevant session (identified by grepping `Booting Linux on
physical CPU 0x0`, then reading forward from that offset — physical line
position in this ring buffer does **not** track chronological order, so
"nearby" log lines are not reliable evidence) showed:

```text
init: [libfs_mgr]__mount(...type=erofs)=-1: Invalid argument
init: [libfs_mgr]__mount(...type=ext4)=0: Success
init: Switching root to '/system'
init: Unable to move mount at '/dev': No such file or directory
Kernel panic - not syncing: Attempted to kill init! exitcode=0x00007f00
```

`init: Switching root to '/system'` is decisive: this ramdisk's `init`
genuinely performs `SwitchRoot()` (confirmed against `system/core/init/
switch_root.cpp` strings in the actual `init` binary), unconditionally,
regardless of the fstab's literal `mnt_point`. `SwitchRoot()` needs empty
stub directories (`/dev`, `/proc`, `/sys`, ...) at the new root as
`MS_MOVE` targets for the special filesystems — exactly the outer-tree
placeholder directories the flat-packaging fix had removed. Without them,
the move fails and init's own death panics the kernel.

The *same* log region was checked in the very first (pre-any-fix) bootloop
capture: `Switching root to '/system'` also appears there, and — because
that build still had the outer system-as-root tree with its `/dev` stub —
the move succeeds and boot continues (`product`, `vendor`, `odm`, `prism`,
`optics` all mount successfully afterward). So the original nested,
system-as-root packaging was correct for this `init` all along.

Fix: reverted. `TARGET_SYSTEM_AS_ROOT=true` restored in `target/d2s/
config.sh` (with a comment recording why); the conditionals added to
`build_fs_image.sh`/`build_flashable_zip.sh` are kept (harmless when true,
and documents the option for a future target that might genuinely need it),
but they now resolve back to the original outer-tree, `MOUNT_POINT="/"`
packaging. The mount-point-relative `lost+found` fix is kept regardless,
since it's correct for either mode.

## Correction from the newest alpha4 device log: second-stage init works

The earlier "silent A11 to A16 init handoff" conclusion was caused by reading
the wrapped Samsung ring buffer in physical-file order. It is disproved by the
newest immutable capture,
`out/logs/bootloop-alpha4-2-20260719-2125/last_kmsg`. In chronological boot
order it records all of the following:

```text
/system/bin/init argv0: second_stage
init: Parsing file /system/etc/init/hw/init.rc...
init: Service 'vold' (pid 496) exited with status 1
init: vold has reboot_on_failure option and failed, shutting down system.
init: Clear action queue and start shutdown trigger shutdown
init: Reboot ending, jumping to kernel
```

SELinux is opened, compiled and loaded before that sequence. Property service,
APEX/linkerconfig, servicemanager and hwservicemanager also start. The first
hard stop is therefore `vold`, not `SwitchRoot`, the init handoff, KernelSU or
a kernel panic. In the latest capture `vold` lives for less than 30 ms and
`vold.rc` deliberately converts its `exit(1)` into `reboot,vold-failed`.

The daily-driver kernel comparison still usefully rules out the KernelSU
warning, but it does not prove that every Android 16 kernel contract is
already satisfied. Kernel work now requires a concrete post-`vold` failure;
blindly replacing first-stage init is no longer justified.

## Confirmed build contamination behind the alpha4 vold failure

The active DeKnox module was written for older Samsung releases. Its
`customize.sh` copied an entire A26 Android 15 `/system` tree and an Android 15
Tab framework tree over the S721B Android 16 source. This replaced at least
`vold`, `vdc`, `installd`, `libandroid_servers.so`, `libepm.so` and `libmdf.so`
after the correct donor system had been assembled. Most companion DeKnox
smali patches had drifted and were skipped, so the result was not a coherent
Android 15 compatibility layer; it was a mixed API35/API36 boot core.

The alpha4 `vold` hash was the A26 prebuilt hash, not the S721B donor hash.
It requested `android.system.keystore2-V4-ndk.so` and `libkeyutils.so`; the
assembled Android 16 system supplied Keystore2 V5 and neither of those A26
dependencies. That is a direct structural explanation for the immediate
pre-logger `exit(1)`. The exact dynamic-linker sentence is absent from the
device capture, so the missing-library mechanism is **very high confidence**,
not a claimed verbatim runtime error.

The fix is target-specific: `unica/mods/deknox/essi85/disable` prevents all of
the legacy overlay. The gate originally compared seven early core files and
now compares twelve boot/graphics-core files against the selected S721B source
firmware byte-for-byte. The old alpha4 work tree fails the original gate on six
files; the first clean alpha5 work tree passes all seven historical entries.

## DEX result

Samsung's source `services.jar` has one physical DEX-041 container containing
logical `classes.dex` and `classes.dex/2`. The port intentionally flattens it
to standalone DEX-040 `classes.dex` and `classes2.dex`, because the available
smali writer cannot emit a valid multi-unit DEX-041 container.

The exact class/method/field/type inventories are preserved with zero missing
or added entries. The second unit still contains `PackageManagerService`,
`InstallPackageHelper`, `PackageManagerServiceUtils`, `ScanPackageUtils` and
`WindowManagerService`. Both outputs have valid header size, file size,
Adler32 and SHA-1 checksums and pass ZIP CRC, zipalign and baksmali parsing.
This is offline evidence only; ART acceptance still needs a boot that reaches
zygote. A fail-closed inventory/sentinel gate is part of the next candidate so
a later framework patch cannot silently drop or move those classes.

## Whole-system findings after vold

The audit found additional integration debt, but did not manufacture a kernel
shim without a runtime consumer:

- The d2s device manifest truthfully declares shipping FCM level 3. The A16
  donor only shipped matrices 5 and newer. The exact stock N975F level-3 and
  level-4 matrices are restored: level 3 is the hard contract and the target
  level is not falsified. The stock HIDL health 2.1 service is retained alongside the
  newer AIDL service because FCM3 still requires a real HIDL health instance.
  A host gate checks every required combined-matrix HAL, not only XML hashes.
- Four legacy `/sys` rules in `vendor/ueventd.rc` used obsolete four-field
  grammar. Three CLAT rules are converted to Android 16 path-plus-attribute
  grammar and one invalid directory rule is removed. These were warnings, not
  the `vold` reboot.
- The current kernel differs from the stock FCM3 requirement on
  `CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y`. Android 14+ disables the runtime
  kernel/AVB part of `verifyBuildAtBoot`, so this is a compliance/security
  gap, not a current boot hard stop. A final kernel should restore the stock
  option rather than weakening the matrix.
- The API36 cgroup and task-profile files are donor-identical. Current logs
  show documented fallbacks and no cgroup hard failure before `vold`.
  `CGROUP_PIDS`, `CGROUP_DEVICE`, scheduler permissions and profile paths must
  be checked from the next live boot before changing the kernel or ramdisk.
- Data encryption is still deliberately disabled in the legacy fstab. A fresh
  Format Data is mandatory for bring-up; restoring tested FBE is a security
  and release requirement after stable boot.
- Drifted framework features remain a recorded backlog. They stay stock for
  first boot rather than being force-applied to the wrong Android 16 methods.

## Alpha7 audio incompatibility and alpha8 bridge

The d2s vendor originally declared
`android.hardware.audio@5.0::IDevicesFactory/default` and shipped the matching
32-bit service plus `audio.primary.exynos9825.so`. The API36 framework in this
port contains factories for AIDL 1 and HIDL 7.1, 7.0 and 6.0, but no HIDL 5.0
adapter. `libaudiohal` selects the declared HAL version and dynamically opens
the matching `libaudiohal@<version>.so`; the alpha7 contract therefore selected
an adapter that was not present. This is a deterministic audio initialization
failure, so alpha7 was rejected without exposing a phone to another flash.

The target kernel, ABOX/VTS/codec configuration, mixer paths, policy XML and
legacy Exynos9825 primary HAL all match the stock N975F firmware. Alpha8 keeps
that hardware-facing stack unchanged and inserts the smallest coherent
generation bridge: the S711B Android 16/VNDK31 32-bit HIDL 6.0 audio/effect
wrappers and their interface libraries. Vendor VINTF now declares audio and
effect 6.0. Both 32-bit and 64-bit spatializer/AIDL pairs also come from that
same donor, replacing the older pair that depended on a private system library
blocked by the vendor namespace.

The fail-closed packaged-image audit reports:

- audio provenance and contract: 16/16 checks passed;
- all 13 bridge/spatializer files hash-match the pinned S711B donor;
- the 12 hardware-facing d2s files hash-match the pinned N975F firmware;
- 34 ELF roots, including every audio HAL/effect: zero missing libraries, zero
  namespace blocks, zero missing versioned symbols and zero missing strong
  unversioned symbols;
- `audio.primary.exynos9825.so`: 48-object closure, 315 dependency edges,
  1531/1531 exact versioned and 2055/2055 strong unversioned symbols;
- 32-bit spatializer: 24-object closure and 64-bit spatializer: 25-object
  closure, both with no unresolved imports.

Two stock-optional effect entries still name absent `libplaybackrecorder.so`
and `libgearvr.so`. They were already optional/stale in the stock policy and
are warnings rather than providers selected by the active effect graph. Real
speaker, microphone, telephony, Bluetooth, USB-C and spatializer behavior still
requires the live matrix in [FLASH_TEST_D2S.md](FLASH_TEST_D2S.md).

## Candidate state and next proof

There is still **no boot-tested-good One UI 8.5 candidate**. Offline success is
not a boot claim.

- alpha4 base and `_2` are device-proven `vold-failed` builds contaminated by
  the API35 overlay. Never flash them again.
- alpha4 `_1` is the device-proven flat-system `SwitchRoot` regression. Never
  flash it again.
- alpha5 (`sha256:5dae060a0f8aa584975b0d3e50dc17d4c44133b9f9c65bb6310b326cdde432a6`)
  is the first clean API36-core build and passed its contemporary offline
  gates, but a stronger audit subsequently rejected it for missing FCM3 and
  stale ueventd rules. It is an intermediate forensic artifact, not the flash
  candidate.
- alpha6 added the FCM/ueventd and DEX inventory gates, but its packaged
  `SamsungCamera.apk` did not match the signed source APK. It was rejected
  offline and never flashed.
- alpha7 restored the camera but is rejected because its HIDL audio 5.0
  declaration cannot be serviced by the API36 framework.
- alpha8 was initially selected as the first-boot candidate:
  `EternityROM_v5.5-oneui85-alpha8_@c83e070e-dirty_20260802_d2s-sign.zip`,
  5860324536 bytes, SHA-256
  `db666df3b21b89471f78c806b812de84e8b622ed05d96e440a3935e87955f058`.
  Its reconstructed filesystems, DEX inventory, 432 APK signatures, VINTF,
  multilib/VNDK31 and expanded audio gates all pass offline. It is nevertheless
  now rejected: the later 333-root AArch64 audit proved that the legacy
  QHD/ultrasonic module had overwritten `bootanimation`, `surfaceflinger`,
  `libandroid_runtime.so`, `libgui.so` and `libui.so` with API35 e2s prebuilts.
  Six vendor NN/media/gralloc/Vulkan/Mali roots reach that `libui.so`, whose
  `android.hardware.graphics.common-V5-ndk.so` dependency is absent.

The post-alpha8 repair keeps the exact S721B DZF3 API36 `bootanimation`,
`surfaceflinger`, `libandroid_runtime.so`, `libgui.so` and `libui.so` instead of
copying the legacy e1s/e2s platform binaries. Samsung MultiResolution code is
present in the source `surfaceflinger`, while the existing framework/SystemUI
and floating-feature patches select the target behavior. A reversible overlay
test against reconstructed alpha8 passed the complete 333-root AArch64 closure
with zero missing libraries, namespace blocks, or strong/versioned symbols.
The next decisive step is a clean alpha9 rebuild and both ABI/package gates;
only that new artifact may proceed to a controlled flash with live
logcat/dmesg. One UI 9 is deferred until this Android 16/One UI 8.5 base reaches
`sys.boot_completed=1` and passes the hardware matrix.
