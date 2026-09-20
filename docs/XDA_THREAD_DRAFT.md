# Private XDA thread outline — Impulse ROM

> **Do not paste this text verbatim into XDA.** Current XDA Rule 15 says that
> AI-generated forum content is not permitted. Treat this document as a private
> factual outline and release checklist, rewrite the post in your own words, and
> verify every claim against the release build before publishing.

## Thread title

```text
[ROM][ALPHA][d2s][SM-N975F][Android 16] Impulse ROM v1.0 | One UI 8.5
```

## Private opening-post outline — XDA BBCode structure

```bbcode
[CENTER]
[SIZE=7][B]Impulse ROM[/B][/SIZE]
[SIZE=5]One UI 8.5 / Android 16 for the Galaxy Note10+ Exynos[/SIZE]

[B]Device:[/B] SM-N975F (d2s) only
[B]Current release:[/B] v1.0 One UI 8.5 Alpha 1
[B]Android:[/B] 16 / API 36
[B]Security patch:[/B] 5 June 2026
[B]SELinux:[/B] Enforcing
[/CENTER]

[COLOR=rgb(184, 49, 47)][SIZE=5][B]IMPORTANT WARNING[/B][/SIZE][/COLOR]

[B]Impulse ROM is an alpha release. It is intended for experienced users and secondary devices, not for a phone you depend on every day.[/B]

[LIST]
[*][B]SM-N975F / d2s Exynos only.[/B] Do not flash this on Snapdragon, Note10, Note10+ 5G or any other model.
[*]Unlocking the bootloader wipes the device and permanently trips the Knox e-fuse.
[*]Samsung Pay, Samsung Wallet and Knox-dependent features remain unavailable even after returning to stock.
[*]A public installation requires Format Data. Back up everything first.
[*]Keep verified stock Odin firmware, a working d2s TWRP image and an off-device EFS backup before flashing.
[*]You accept responsibility for data loss, broken applications or a non-booting device.
[/LIST]

[SIZE=5][B]About Impulse ROM[/B][/SIZE]

Impulse ROM brings the Galaxy S24 FE system base to the Exynos Galaxy Note10+, combining One UI 8.5 and Android 16 with the Note10+ vendor and hardware compatibility layer.

The project is a GPLv3 fork of EternityROM by Ocin4ever, built on the ROM build system created by Salvo Giangreco. It keeps the original authorship and copyright notices and adds d2s-specific compatibility, stability and installation safeguards.

[SIZE=5][B]Highlights[/B][/SIZE]

[LIST]
[*]One UI 8.5 based on Galaxy S24 FE firmware
[*]Android 16 / API 36 with the 5 June 2026 system security patch
[*]QHD+ 1440 x 3040 Note10+ display configuration
[*]SELinux enforcing
[*]ExtremeKRNL for d2s
[*]KernelSU-Next manager included — this build is rooted by design
[*]Package-scoped ROM signing; no unrestricted signature bypass
[*]Fixed recurring system soft reboots caused by incompatible Samsung OLED afterimage compensation
[*]Fixed Samsung Photo Editor filter crashes with a matching-generation Filter Provider
[*]Extra dim backend restored for the Note10+; full Modes and Routines integration is being finalized
[/LIST]

[SIZE=5][B]Working[/B][/SIZE]

[LIST]
[*]System boot and normal UI
[*]Calls, SMS and LTE mobile data
[*]Wi-Fi and Bluetooth
[*]Speakers, earpiece, microphones and normal media audio
[*]Camera package present on the developer device; clean-install availability and photo/video capture remain unverified
[*]Fingerprint enrollment and unlock
[*]QHD+ display, touch and automatic brightness
[*]USB, ADB and MTP
[*]S Pen basics
[*]Wired charging
[/LIST]

[SIZE=5][B]Known issues[/B][/SIZE]

[LIST]
[*][B]Wireless charging does not work.[/B] The kernel interface is present, but the userspace cause has not yet been confirmed.
[*][B]Samsung Health refuses to start[/B] with the unauthorized-modifications / Knox-rooting error.
[*]Samsung Pay and Wallet are not supported. Secure Folder is reported working on Impulse; the next build still requires regression testing.
[*]Play Integrity fails. Some banking, work-profile and streaming applications may not run.
[*]Samsung camera AI, Gallery OCR and related NPU features are unstable. The Samsung snap service can restart when a model cannot be mapped.
[*]In Alpha 1, Extra dim works through its system backend and Quick Settings shortcut, but the Modes and Routines action may be shown as unavailable. The source fix is prepared for the next build.
[*]This release has not completed the full clean-install community test matrix. Please treat it as an alpha.
[/LIST]

[SIZE=5][B]Installation[/B][/SIZE]

[COLOR=rgb(184, 49, 47)][B]The following is only a summary. Read the complete installation guide before flashing.[/B][/COLOR]

[LIST=1]
[*]Download stock Odin firmware for your exact SM-N975F CSC and verify that it is complete.
[*]Back up all personal data and two-factor authentication credentials.
[*]Unlock the bootloader. This wipes the device and permanently trips Knox.
[*]Install a compatible d2s TWRP recovery and boot directly into recovery.
[*]Create an EFS backup and copy it away from the phone.
[*]In TWRP select Wipe -> Format Data and type yes. A normal factory reset is not enough.
[*]Copy the Impulse ROM ZIP to the phone, SD card or USB OTG storage.
[*]Verify the published SHA-256. Do not flash if it differs.
[*]Flash the ZIP and follow the on-screen confirmation. Do not interrupt filesystem resizing.
[*]Reboot. The first boot may take 10 to 20 minutes.
[/LIST]

[B]Dirty flashing from EternityROM 5.5 is unsupported. Use a clean installation with a complete backup; in-place migration has not been tested.[/B]

[SIZE=5][B]Download[/B][/SIZE]

[B]ROM:[/B] [URL='REPLACE_WITH_PUBLIC_DOWNLOAD_URL']ImpulseROM v1.0 One UI 8.5 Alpha 1[/URL]

[CODE]
File: ImpulseROM_v1.0-oneui85-alpha1_@c83e070e-dirty_20260824_d2s-sign.zip
Size: 5,799,702,082 bytes
SHA-256: 0727861f7da3b76cf754992e07699db5c322dce7e1c250a4394093e73e1347b6
[/CODE]

[B]The flashable ZIP is not cryptographically signed. Always verify the SHA-256 after downloading.[/B]

[SIZE=5][B]Changelog — v1.0 Alpha 1[/B][/SIZE]

[LIST]
[*]Initial Impulse ROM rebrand and d2s alpha release
[*]Galaxy S24 FE One UI 8.5 / Android 16 system base
[*]Disabled incompatible AfterimageCompensationService configuration responsible for recurring system soft reboots
[*]Updated Filter Provider to fix Samsung Photo Editor filter crashes
[*]Restored protected-content support required by Extra dim
[*]Hardened d2s recovery assertions and installation checks
[*]Added package-scoped Impulse platform signing
[*]Kept SELinux enforcing
[/LIST]

[SIZE=5][B]Source code and licences[/B][/SIZE]

[B]Impulse ROM source:[/B] [URL='REPLACE_WITH_PUBLIC_IMPULSE_SOURCE_URL']REPLACE BEFORE POSTING[/URL]
[B]Upstream EternityROM:[/B] [URL='https://github.com/Ocin4ever/EternityROM']github.com/Ocin4ever/EternityROM[/URL]
[B]Kernel source:[/B] [URL='https://github.com/Ocin4ever/ExtremeKernel/tree/f54c88ef6171ff3c4b5067911d5e8e4a0c62ec17']ExtremeXT Exynos 9820 kernel source[/URL]
[B]KernelSU-Next:[/B] [URL='https://github.com/KernelSU-Next/KernelSU-Next']github.com/KernelSU-Next/KernelSU-Next[/URL]

Impulse ROM is distributed under GPLv3. The Linux kernel is GPLv2. Samsung proprietary firmware blobs are build inputs and are not represented as original Impulse ROM work.

[SIZE=5][B]Credits[/B][/SIZE]

[LIST]
[*]Ocin4ever — EternityROM, from which Impulse ROM is forked
[*]Salvo Giangreco (@salvo_giangri) — original ROM build system
[*]ExtremeXT — ExtremeKRNL and Exynos kernel work
[*]rifsxd and the KernelSU-Next contributors — root solution
[*]Samsung — original firmware and device software
[*]Everyone testing and reporting issues with usable logs
[/LIST]

[SIZE=5][B]Bug reports[/B][/SIZE]

Before reporting a bug, reproduce it once and attach:

[CODE]
adb shell getprop ro.boot.em.model
adb shell getprop ro.build.version.security_patch
adb logcat -b all -d > logcat-all.txt
adb bugreport impulse-bugreport.zip
[/CODE]

Also include the exact ZIP filename, its SHA-256, whether you clean-flashed, and the steps that trigger the problem. Reports without logs may not be actionable.

[SIZE=5][B]Screenshots[/B][/SIZE]

[I]Attach current screenshots here: About phone, home screen, Settings, Quick Settings, Camera and Extra dim.[/I]

[CENTER][B]Flash carefully, keep a rollback path, and enjoy giving the Note10+ another life.[/B][/CENTER]
```

## Replace before publishing

- `REPLACE_WITH_PUBLIC_DOWNLOAD_URL`
- `REPLACE_WITH_PUBLIC_IMPULSE_SOURCE_URL`
- Add current screenshots.
- Rebuild and test the pending Modes and Routines Extra dim fix, then update the
  version, filename, size, checksum and changelog if the release becomes Alpha 2.
- Perform at least one clean installation from the documented stock baseline.
- Capture a wireless-charger log and either fix the issue or retain the warning.
