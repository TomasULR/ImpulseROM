# d2s One UI 8.5 alpha8 — rejected, do not flash

This document retains alpha8's forensic identity and the future controlled-test
procedure. It is **not permission to flash alpha8**.

> **STOP:** The expanded AArch64 audit performed after the original release
> audit invalidated alpha8. The QHD/ultrasonic feature module replaced five
> API36 graphics-core files with Android 15/API35 e2s prebuilts. Six real
> vendor graphics/media/NN roots then reach `libui.so`, which requires absent
> `android.hardware.graphics.common-V5-ndk.so`. Alpha8 must not be flashed.

## Candidate identity

```text
file:   EternityROM_v5.5-oneui85-alpha8_@c83e070e-dirty_20260802_d2s-sign.zip
sha256: db666df3b21b89471f78c806b812de84e8b622ed05d96e440a3935e87955f058
size:   5860324536 bytes
source: SM-S721B/EUX S721BXXSCDZF3 — Android 16 / One UI 8.5 / API 36
multilib: SM-S711B/EUX S711BXXSGGZF2 — Android 16 ARM32 runtime
target: SM-N975F/BTU N975FXXS9HWHA — d2s vendor and fixed partitions
kernel: pinned ExtremeKRNL Nexus d2s v2.0
```

The filename suffix `-sign.zip` is historical. The builder does not add a ZIP
signature, so only the full SHA-256 above identifies the approved artifact.
The identity below is retained only to prevent confusion with a corrected
future candidate.

## What alpha8 fixes

- It retains the four property-context fixes that allowed alpha2 init to pass.
- It supplies and validates the complete API36 ARM32 linker, bionic, ICU,
  system libraries and VNDK31 contract required by eight legacy vendor
  services.
- It disables legacy DeKnox only for `essi85`. That module had overwritten the
  Android 16 `vold`, `vdc`, `installd` and related libraries with Android 15
  files. The build now requires twelve boot/graphics-core files to hash-match the S721B
  donor.
- It keeps system-as-root packaging. The flat-system alpha4 experiment removed
  `/dev`, `/proc` and `/sys` switch-root stubs and is known bad.
- It restores the exact stock N975F FCM3 and FCM4 framework matrices for the
  vendor manifest's real target level 3; the target level is not changed. The
  real HIDL health
  2.1 service is restored alongside the newer AIDL health service, and a host
  gate checks all mandatory combined-matrix HAL instances.
- It fixes the audio-generation mismatch that invalidated alpha7. Android 16
  `libaudiohal` can load HIDL 6.0/7.x or AIDL adapters, while the stock d2s
  vendor declared HIDL 5.0. Alpha8 installs a pinned 32-bit HIDL 6.0 wrapper
  from the matching Android 16/VNDK31 S711B donor over the unchanged d2s
  Exynos9825 legacy HAL and declares audio/effect 6.0 in VINTF.
- It replaces both 32-bit and 64-bit vendor spatializer pairs with the coherent
  S711B/VNDK31 implementation. This removes a private-system namespace
  dependency that the older spatializer could not legally resolve.
- The build now fail-closes on firmware provenance, audio init/VINTF/SELinux
  contracts, policy XIncludes, effect libraries, wrapper entry points and the
  complete 32-bit ELF dependency/symbol closure for every audio HAL and effect.
- It converts three obsolete CLAT ueventd rules to Android 16 grammar, removes
  one invalid IIO directory rule and rejects any remaining malformed `/sys`
  rule at build time.
- It preserves both logical units from Samsung's DEX-041 `services.jar` as
  standalone DEX-040 outputs and verifies exact class/method/field/type
  inventories plus PackageManager/WindowManager sentinels.
- It keeps Samsung-signed APKs byte-identical for first boot. Drifted feature
  patches stay stock and are recorded in `out/skipped_patches.tsv`.

## Why previous attempts failed

1. The first ZIP wrote partitions and then returned updater error 25 because
   cleanup used the wrong ZIP path.
2. Alpha2 installed successfully, then PID 1 aborted on four duplicate split
   property-context declarations.
3. Alpha3 was never flashed. Offline analysis found it lacked the 32-bit
   runtime required by camera, audio, OMX, DRM, CAS, IVA and provisioning.
4. Alpha4 `_1` used a flat system image. Device logs prove `SwitchRoot()` then
   failed to move `/dev`, killing init and panicking the kernel.
5. Alpha4 base and `_2` actually reached Android 16 second-stage init, loaded
   SELinux and started core services. `vold` exited within 30 ms and its
   `reboot_on_failure` action restarted the phone as `vold-failed`. Their build
   recipe had replaced API36 `vold` with an API35 binary needing unavailable
   Keystore2 V4 and `libkeyutils` dependencies.
6. Alpha5 removed that contamination and passed 60 tests, but the stronger
   whole-system audit then rejected it for a missing FCM3 framework matrix and
   four stale ueventd rules. Alpha5 was not flashed.
7. Alpha6 corrected FCM/ueventd and DEX packaging, but the packaged
   `SamsungCamera.apk` no longer matched the signed S721B source. It was
   rejected offline and was not flashed.
8. Alpha7 restored the exact camera APK and passed its contemporary build
   gates. A broader system audit then proved that API36 could not load the
   declared HIDL audio 5.0 implementation, so alpha7 was rejected before flash.
9. Alpha8 adds the coherent HIDL 6.0 audio/spatializer compatibility layer and
   passes the expanded audio and packaged-image gates. A later whole-vendor
   ELF64 audit nevertheless rejects it: five graphics-core files came from
   Android 15 and `libui.so` has an unsatisfied graphics-common V5 dependency.

The corrected evidence chain is in
[FORENSICS_ALPHA2_ALPHA3.md](FORENSICS_ALPHA2_ALPHA3.md).

## Mandatory no-flash gates

- [ ] A corrected post-alpha8 artifact passes both ELF32 and full ELF64 gates.
- [x] Replacing alpha8's five API35 graphics-core files with the exact S721B
      DZF3 API36 originals passes the 333-root ELF64 closure with zero missing
      libraries, namespace blocks, or strong/versioned symbols. The build now
      preserves and hash-pins those source files instead of copying legacy e1s/e2s
      platform binaries.
- [x] All candidate fields above are final and the host SHA-256 was rechecked.
- [x] The historical alpha8 package gate passed: ZIP CRC and 33-member allowlist,
      transfer-list coverage, reconstructed filesystem checks, system-as-root
      stubs, seven historical packaged core hashes, 432/432 APK signatures, multilib/VNDK,
      FCM3, ueventd, DEX and audio inventories.
- [x] Both stock Odin copies and both protected EFS-family backup copies were
      rehashed successfully on 2026-08-02.
- [ ] The phone-side gates in [ROLLBACK_D2S.md](ROLLBACK_D2S.md) are complete:
      known-good ZIP, recovery dump, Recovery/Download Mode and battery.
- [ ] The known-good `EternityROM_v5.5_d2s.zip` is available on both host and
      removable storage with SHA-256
      `8830d5d12d01c5987bc292ddeff303dc6cda648e929c338bc1c9259d0ba64834`.
- [ ] The installed recovery partition was dumped read-only, its byte count was
      checked against `blockdev --getsize64`, and its repeated hash is stable.
- [ ] Recovery and Download Mode were both entered without writing anything.
- [ ] Battery is at least 70 percent and the USB cable is stable.
- [ ] Explicit approval names the exact corrected post-alpha8 SHA-256. Approval
      for alpha8 or any older alpha does not carry forward.

## Prepare the capture directory

On the host:

```bash
umask 077
mkdir -p out/logs/boot-alpha8-$(date +%Y%m%d-%H%M%S)
```

Use the created directory for every command below. Do not publish EFS images,
serial numbers, IMEI-bearing properties or radio identity files.

## TWRP install

1. Boot TWRP `3.7.1_12-ExtremeXT_v2` and reconnect ADB.
2. Make a fresh Nandroid backup of boot and every partition the installer will
   write. Confirm that the backup has completed before continuing.
3. Copy the exact alpha8 ZIP to removable storage. Verify the device-side file:

   ```bash
   adb shell sha256sum /external_sd/Download/EternityROM_v5.5-oneui85-alpha8_@c83e070e-dirty_20260802_d2s-sign.zip
   ```

   The output must equal the full approved host SHA-256.
4. Use **Format Data**, not a normal data wipe. Also wipe Dalvik/ART cache and
   Cache. The bring-up fstab deliberately disables FBE and an old encrypted
   `/data` is not a valid test input.
5. Install the ZIP once. Require updater return code 0, then save the complete
   recovery log before rebooting:

   ```bash
   adb exec-out cat /tmp/recovery.log > recovery-install.log
   ```

6. Do not wipe after install. Start the live captures below, then reboot
   System. First boot may legitimately spend several minutes compiling ART.

## Live capture

Run these in separate terminals before or immediately after `adb reboot`:

```bash
timeout 900 adb logcat -b all -v threadtime > live-logcat-all.txt 2>&1
```

```bash
timeout 900 adb shell dmesg -w > live-dmesg.txt 2>&1
```

```bash
for i in $(seq 1 900); do
    printf '%s ' "$(date --iso-8601=seconds)"
    adb get-state 2>&1
    sleep 1
done > adb-state-timeline.txt
```

The last command is diagnostic monitoring only; stop it after the result is
clear. A disappearing ADB device does not by itself prove a reboot.

## Success gate

Reaching a boot animation is not success. Require all of these:

```bash
adb wait-for-device
adb shell 'getprop sys.boot_completed; getprop init.svc.vold; pidof vold; getprop init.svc.vendor.audio-hal; pidof android.hardware.audio.service; getenforce'
```

Expected values are `1`, `running`, a live `vold` PID, `running`, a live audio
service PID and `Enforcing`. Then capture:

```bash
adb shell getprop > getprop.txt
adb shell dmesg > dmesg-after-boot.txt
adb logcat -b all -d -v threadtime > logcat-after-boot.txt
adb shell cat /linkerconfig/ld.config.txt > linkerconfig.txt
adb shell mount > mount.txt
adb shell ps -AZ > ps-az.txt
adb shell lshal > lshal.txt
adb shell dumpsys package > dumpsys-package.txt
adb shell dumpsys audio > dumpsys-audio.txt
adb shell dumpsys media.audio_flinger > dumpsys-media-audio-flinger.txt
adb shell dumpsys media.audio_policy > dumpsys-media-audio-policy.txt
adb shell 'cat /proc/asound/cards; cat /proc/asound/pcm' > proc-asound.txt
adb shell 'cat /proc/cgroups; cat /proc/mounts; ls -l /proc/pressure' > cgroups.txt
adb shell 'ls -l /data/tombstones 2>/dev/null' > tombstones-index.txt
```

Before enabling deferred mods, test setup wizard/launcher, calls and mobile
data, Wi-Fi, Bluetooth, GPS, cameras, video decode/encode, DRM playback,
fingerprint, S Pen, sensors, NFC, USB/MTP, charging, sleep/wake and a warm
reboot. Record pass/fail/degraded for each item.

Audio is a separate release gate. Test every route and capture logcat while
switching routes:

- media through the bottom speaker and call audio through the earpiece;
- ringtone, alarm, notification and volume/mute transitions;
- main microphone, call uplink/downlink, voice recorder and camera recording;
- Bluetooth A2DP media and Bluetooth SCO call/microphone;
- a USB-C headset or USB DAC, including its microphone when present;
- speakerphone, route changes during a call, suspend/resume and a warm reboot;
- SoundAlive/Dolby/spatial audio, equalizer and haptic-audio effects where the
  UI exposes them.

Save the focused runtime trace as well:

```bash
adb logcat -b all -d -v threadtime | grep -Ei 'audio|audioserver|audioflinger|audiopolicy|soundalive|spatial|tinyalsa|abox' > audio-focused-logcat.txt
adb shell 'lshal | grep -E "android.hardware.audio|samsung.hardware.audio"' > audio-lshal.txt
```

Any service death, tombstone, unresolved library, `CANNOT LINK EXECUTABLE`,
continuous route retry or silent/corrupt route keeps the hardware matrix red.

## Bootloop capture

If the phone resets or never reaches ADB/UI, return to TWRP immediately. The
Samsung logs are small rings and later boots overwrite the useful region:

```bash
adb exec-out cat /proc/last_kmsg > last_kmsg
adb exec-out cat /proc/sec_log > sec_log
adb pull /sys/fs/pstore pstore
adb shell dmesg > recovery-dmesg.txt
```

If `/data` mounts safely, also collect without modifying it:

```bash
adb pull /data/tombstones tombstones
adb pull /data/system/dropbox dropbox
adb pull /data/misc/logd logd
```

Read `sec_log` chronologically from boot markers; its physical tail is not
necessarily the newest event. Classify the first fatal consumer before any
kernel, partition, SELinux or framework change. If `vold` still exits without
its own error text, build one diagnostic variant that routes its stderr to
kmsg; do not remove `reboot_on_failure` from the release candidate.

## Remaining engineering debt

- Restore FBE and verify data migration only after stable unencrypted bring-up.
- Rebuild the kernel with the stock
  `CONFIG_SECURITY_PERF_EVENTS_RESTRICT=y`; evaluate missing cgroup controllers
  from live consumers rather than weakening FCM3.
- Rebase the 29 drifted feature patches one subsystem at a time after the base
  boot/hardware matrix is green.
- Re-enable platform APK edits only after the custom-platform-signature path is
  rebased and tested with both Samsung and ROM certificates.
- Do not start One UI 9 work until One UI 8.5 reaches
  `sys.boot_completed=1` and this hardware matrix is repeatably green.
