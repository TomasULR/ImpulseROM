# Impulse ROM — diagnosed defects and applied fixes

Evidence base: 39 MB `logcat -b all` + 2693-line crash buffer + full bugreport
pulled from a live `SM-N975F` on 2026-08-24, running
`v5.5-oneui85-alpha15` (kernel `4.14.356-openela-rc1-ExtremeKRNL-Nexus-v1+`,
uptime 2 weeks, flashed 2026-08-10).

Device identity note: `ro.boot.em.model` reads `SM-N975F` (bootloader, real
hardware) while `ro.product.model` reads `SM-S721B` and `ro.product.device`
reads `r12s`. The port carries the S24 FE source firmware's identity.

---

## 1. Random restarts — FIXED

Two unrelated events were both perceived as "random restarts".

### 1a. AfterimageCompensationService SIGSEGV (real defect)

```
#00 ABC::bpProcess(unsigned char*, float*, int, AbcDisplayParams&)+240   libandroid_servers.so
#01 Java_com_samsung_android_hardware_display_AfterimageCompensationService_nativeDataSave+288
#03 com.samsung.android.hardware.display.AfterimageCompensationService$AfcThread.run+3924
```

Three identical crashes: 08-13 22:46:47, 08-19 06:51:28, 08-21 16:59:39, at
process uptimes of 294813 s / 358388 s / 209281 s (3.4 / 4.1 / 2.4 days).

Root cause: `target/d2s/overlay/values/` (commit `19d322fc`, "import d2s
values") turns afterimage compensation on and supplies the **stock Android 12
d2s** AFPC geometry:

```xml
<bool    name="config_AFC_enabled">true</bool>
<integer name="config_AFC_type">2</integer>
<integer name="config_AFPC_model">190202</integer>
<integer name="config_AFPC_size">551186</integer>
<integer name="config_AFPC_width">360</integer>
<integer name="config_AFPC_height">760</integer>
```

But this ROM ships the **r12s / One UI 8.5** `libandroid_servers.so`, whose
`ABC::bpProcess()` is a different generation and expects a different data
layout. Feeding it the d2s values makes it write out of bounds.

Gate chain, confirmed in smali:
`SemMdnieManagerService.mUseAfterimageCompensationServiceConfig`
← `Resources.getBoolean(0x1110014)` ← `config_AFC_enabled`.
(The `vendor.display.enable_abc` / `vendor.display.enable_aiqe_abc` props read
by `checkApABCSupported()` are both unset and are *not* the gate.)

**Fix:** `config_AFC_enabled` → `false` in
`target/d2s/overlay/values/bools.xml`.

Trade-off: Samsung's OLED burn-in compensation is off. It was already crashing
rather than compensating, so no working protection is lost.

### 1b. Device Care scheduled restart (not a defect)

08-15 03:18:15 and 08-22 03:18:15 — exactly 7 days apart, same minute:

```
!@*** FATAL EXCEPTION IN SYSTEM PROCESS: android.ui
java.lang.NullPointerException: NPE by silent reset. It's normal operation caused by device care
    at com.android.server.power.PowerManagerService$4.run
```

This is Samsung's weekly auto-restart working as designed. No fix. It can be
turned off in Device Care if unwanted.

### Both are soft reboots, not kernel reboots

Kernel uptime stayed at 2 weeks across all five events. `system_server` dies,
zygote restarts, the boot animation shows — the kernel never reboots.

---

## 2. Wireless charging — ROOT CAUSE NOT YET CONFIRMED

The hardware and kernel side are **fully present**:
`/sys/class/power_supply/` exposes `wireless` (type `Wireless`),
`mfc-charger`, and ~30 `battery/wc_*` nodes. `dumpsys battery` has a
`Wireless powered` field. All read correctly as 0 while on USB.

The five `android.hardware.health@2.1-service-samsung` aborts
(`Health::updateLrpSysfs()` → `DEAD_OBJECT`) are **cascade damage, not the
cause** — every one lands 10–30 s after a `system_server` death:

| system_server | health HAL abort | delay |
|---|---|---|
| 08-13 22:46:49 | 08-13 22:47:19 | 30 s |
| (03:18 auto-restart) | 08-15 03:18:38 | ~23 s |
| 08-19 06:51:30 | 08-19 06:51:39 | 9 s |
| 08-21 16:59:40 | 08-21 17:00:00 | 20 s |
| (03:18 auto-restart) | 08-22 03:18:21 | ~6 s |

Fixing §1 removes all five.

Separate real finding: `com.sec.android.sdhms` polls
`/sys/class/power_supply/battery/chg_type`, which does not exist on the d2s
4.14 kernel (it has `charge_type` and `charging_type`). `chg_type` is the r12s
name. SDHMS is diagnostics only, so this is log noise rather than a charging
defect — but it is a genuine porting gap.

**Still needed:** a log capture taken while the device sits on a wireless
charger. Nothing in the current 39 MB log covers that state.

---

## 3. Samsung Health — NOT FIXED

```
SHEALTH#OobeConsentDoneHandler: handleKnoxInitResult :: KnoxInitResult(mCode=-4112)
SHEALTH#HomeAppCloseActivity: mStateType : OOBE_ERROR_KNOX_ROOTING_DEVICE
SHEALTH#HomeAppCloseActivity: showDeviceRootingErrorPopup()
```

Samsung Health closes itself at the end of OOBE, showing the Czech
"unauthorized changes" dialog with code `0x240304040f70006281c`.

### What was applied and verified in the build

`unica/mods/knoxpatch/` was re-enabled and three of its patches landed:

- `samsungkeystoreutils.jar` — `isVerifiableIntegrity()` now `const/4 v0, 0x1; return v0`
- `services.jar` `DarManagerService.checkDeviceIntegrity()` — returns `1`
  (supplied by `target/d2s/patches/android16_compat/0002-Allow-Secure-Folder-on-unlocked-d2s.patch`,
  which is why the KnoxPatch copy showed as drifted but the effect is present)
- `ro.config.iccc_version` removed, `wlan.wfd.hdcp=disable`

**None of them changes the verdict.** `KnoxInitResult` is Samsung Health's own
class (5 references in its APK), not a Knox SDK type, and `-0x1010` appears
nowhere in `knoxsdk.jar`. The gate is somewhere Health reaches through
`EnterpriseDeviceManager` / `EnterpriseKnoxManager` / `TimaKeystore`, not
through the ICD/SAK paths those patches cover.

Ruled out along the way:

- **Not a missing class.** Health references
  `com.samsung.android.knox.tima.iccc.SemIntegrityControlCheckCenterServiceManager`,
  which does not exist in this ROM — but `knoxsdk.jar` here is byte-identical to
  the donor firmware, and the donor has no `tima`/`iccc` classes either. Stock
  One UI 8.5 simply does not ship them.
- **Not a server round-trip.** `KnoxInit` at 17:54:25.678, error at
  17:54:25.740 — 62 ms. The check is local, so a local spoof could in principle
  work.

### What would actually fix it

KnoxPatch's real mechanism for this is the `SamsungPropsHooks` pair:
`framework.jar` (adds the hook class, patches `Instrumentation`,
`SystemProperties.get()` and `Settings$Global`) plus `knoxsdk.jar`
(`EnterpriseDeviceManager.getAPILevel()`). Both are kept as `*.patch.disabled`.

A dry run against the current tree fails **every hunk** (2/2, 2/2, 1/1) — they
were cut against One UI 7. Enabling them needs all three hunks rebased *and* a
`framework.jar` rebuild, which is the operation that blocked this port's build
before. Deliberately not attempted: `framework.jar` is the highest-risk artifact
in the tree and a bad rebuild bootloops the device.

Not fixable at all: the Knox e-fuse is blown permanently on bootloader unlock.
This does not establish that Secure Folder is unavailable on the port: a September tester reports it working. Preserve and regression-test that compatibility.

## 4. Extra dim / extreme screen dimming — FIXED FOR NEXT BUILD

The backend was never broken. Setting the secure setting live works:

```
ColorDisplayService: Turning on reduce bright colors
MdnieScenarioControlService: onChange uri : .../reduce_bright_colors_activated
```

Only the Settings entry was hidden. `SecAccessibilityUtils.isSupportReduceBrightness()`
requires **both**:

1. `ro.surface_flinger.protected_contents` == true — the r12s source firmware
   sets this in `vendor/build.prop`; **stock d2s never defined it**, and this
   port ships the d2s vendor partition, so the One UI 8.5 system half looks for
   something its own vendor never declares.
2. `ro.product.vendor.device` must not prefix-match `excludeDeviceNameSet`
   = `{"beyond", "d1", "d2"}` — and `d2s` matches `"d2"`. Samsung explicitly
   blacklisted the S10 and Note10 families from Extra dim.

`SystemUI.ReduceBrightColorsTile` repeats both checks for the QS tile. The
Samsung Accessibility package repeats them a third time in its Modes and
Routines provider. Alpha1 did not patch that third copy, so routines report
the action as unavailable even while the backend works.

**Fix:** `platform/exynos9825/patches/protected_content/` re-enabled, plus a new
`customize.sh` that sets the vendor prop and rewrites the three blacklist
string literals in both SystemUI and the Samsung Accessibility routine
provider. Accessibility is admitted only through the package- and path-scoped
platform-signature bridge; the build fails if its expected helper drifts.

On an alpha1 dirty flash, the hidden Settings page can be opened directly and
the Quick Settings shortcut re-registered without data loss. That restores the
tile, but the Modes and Routines action requires the next rebuilt system image.

The upstream `0001-Remove-device-specific-checks.patch` files are kept as
`*.patch.disabled`: they were cut against a One UI 7 SecSettings where these
classes lived in `smali_classes4` (here: `smali_classes5`), and their second
hunk overwrites a register the surrounding code reuses as the constant `false`.
`APPLY_PATCH` runs `patch -p1 --fuzz=0`, so they would have silently landed in
`out/skipped_patches.tsv` (26 patches were already skipped in the last build).

---

## 5. Instagram stuttering — NO ROM DEFECT FOUND

Measured, not inferred:

```
Total frames rendered: 156659
Janky frames: 5418 (3.46%)
50th 10ms | 90th 20ms | 95th 32ms | 99th 48ms
```

3.46 % jank is normal-to-good for a heavy social app on this hardware — the
system launcher measures worse at 11.20 %. Thermals are clean (AP 33.7 °C,
thermal status 0, `scaling_max_freq` == `cpuinfo_max_freq` on all clusters).

Two earlier hypotheses were checked and **disproved**:

- *Missing VP8/VP9 software fallback* — wrong. `c2.android.vp8.decoder` and
  `c2.android.vp9.decoder` are both registered; an earlier `grep -A4` had
  truncated the decoder list.
- *Memory pressure* — wrong. `MemAvailable` is 3.5 GB and zram compresses
  4.5:1 (2.27 GB → 505 MB). The load average of ~13 comes from ~12 TrustZone
  kernel threads parked in D-state, which is normal on Exynos.

The two `com.instagram.android` entries in the crash buffer are collateral from
`system_server` dying (08-13 22:46:49 and 08-21 16:59:41 — the same seconds as
§1a), as are `com.android.phone`, `mobilewips`, `sdhms` and `lool`. The ~200
hitches over 150 ms in the frame histogram fall in the same window. Fixing §1
should remove the worst episodes.

---

## 6. Photo editor — ROOT-CAUSED AND FIXED

```
FATAL EXCEPTION: Effect_Init_Thread
Process: com.sec.android.mimage.photoretouching
java.lang.StringIndexOutOfBoundsException: length=22; index=44
    at java.lang.String.substring(String.java:2910)
    at com.samsung.android.camera.filter.SemFilterManager.loadFilter(Unknown Source:166)
```

`SemFilterManager` is defined in `/system/framework/secimaging.jar`, not in the
editor APK. `loadFilter()` queries
`content://com.samsung.android.provider.filterprovider/allfilters` with a **null
projection** and strips the package prefix off every filename:

```smali
# secimaging.jar SemFilterManager.smali:1054
invoke-virtual {v6}, Ljava/lang/String;->length()I   # package_name
move-result v10
add-int/2addr v10, v5                                # + 1
invoke-virtual {v13, v10}, Ljava/lang/String;->substring(I)Ljava/lang/String;
```

Dumping `filter.db` with root found the offending row:

| column | length | value |
| --- | ---: | --- |
| `filename` | **22** | `myfilter_sample_05.sel` |
| `package_name` | **43** | `com.samsung.android.provider.filterprovider` |

`substring(43 + 1)` on 22 characters is exactly `length=22; index=44`. All 12
rows in `filters` are well-formed; `allfilters` merges `filters` with `myfilter`
and only that merged row carries a bare filename.

### The real cause is a provider generation mismatch

| component | version | targetSdk | generation |
| --- | --- | ---: | --- |
| `secimaging.jar` (the consumer) | byte-identical to donor | 36 | One UI 8.5 |
| `/system/app/FilterProvider` (shipped) | **7.0.12** | 34 | Android 12 |
| `FilterProvider` in donor firmware | **9.5.18** | 35 | One UI 8.5 |

The shipped APK (353,297 bytes, `bce394ff…`) matches neither donor
(756,758 bytes) nor stock d2s (295,986 bytes), and the identical file sits in
`out/target/d2s/work_dir`. Of 46 identifiers unique to the d2s build, 39 are
present in it; of 1365 unique to the donor, 4 are. It carries d2s-era class
names (`FilterPackageService$a`, `SamsungAccountCallbackService$a`) and d2s-era
filter names (`CookiNCream`, `Everyday`, `Monogram`).

Nothing in the tree copies that APK — `create_work_dir.sh` rsyncs `system` from
the donor and the only build-log mention is `Deleting
/system/system/app/FilterProvider/oat`. The most likely explanation is an
incremental work dir that kept a copy from an earlier run. **Worth a clean work
dir for the next build**, since other files could be equally stale.

### Verified on device

Installing the donor 9.5.18 provider over the 7.0.12 one (both carry the same
Samsung Cert, so `pm install -r` accepts it) and clearing the provider's data
produced **13 rows with zero malformed filenames**, and a completely different,
newer filter set (FilmClassic, Crystal, Pure, FilmPop, Fleecia film, Lomo 400).

Note that `pm clear` **alone does not fix it** — the 7.0.12 provider re-seeds the
malformed `myfilter` row on the next query. Only the provider swap works.

**Fix:** `platform/exynos9825/patches/camera/customize.sh` now deletes the
work-dir copy and re-adds `system/app/FilterProvider/FilterProvider.apk` from
`$FW_DIR/$SOURCE_FIRMWARE_PATH`, making the provider generation deterministic.

## 7. Most frequent crash overall — NOT YET ADDRESSED

`vendor.samsung.hardware.snap-service`, 22 × SIGSEGV,
`Abort message: 'Failed to map model.'`, null deref in
`libsnaplite_native.so` under `SnapliteSession::Close()`.

Same class of failure in Gallery OCR — `com.sec.android.gallery3d` × 9,
null deref at `TfLiteInterpreterGetTensor` in
`libStrideTensorflowLite.camera.samsung.so`. Plus
`android.hardware.neuralnetworks@1.3-service.eden-drv` × 1 and
`com.samsung.android.app.smartcapture` × 7.

Common theme: NPU/NN model files fail to map. The r12s system-side NN stack is
paired with the d2s Exynos 9825 eden driver.
