# d2s One UI 8.5 Test Matrix

Use this matrix for every alpha build. Record build filename, source firmware,
kernel zip, flash method, wipe state, and tester device before testing.

## Current Alpha Build Record

| Field | Value |
| --- | --- |
| Build date | 2026-08-02 |
| Build ZIP | `EternityROM_v5.5-oneui85-alpha8_@c83e070e-dirty_20260802_d2s-sign.zip` |
| SHA256 | `db666df3b21b89471f78c806b812de84e8b622ed05d96e440a3935e87955f058` |
| Source firmware | `SM-S721B/EUX S721BXXSCDZF3/S721BOXMCDZF3/S721BXXSCDZF3` |
| Multilib firmware | `SM-S711B/EUX S711BXXSGGZF2/S711BOXMGGZF2/S711BXXSGGZF2` |
| Target firmware | `SM-N975F/BTU N975FXXS9HWHA/N975FOXM9HWH6/N975FXXS9HWH6` |
| Offline ZIP test | **Rejected after expanded ELF64 audit:** API35 graphics core and missing graphics-common V5 |
| Device flash test | Not run yet |
| Expected first flash | Clean flash in TWRP, then Format Data |

## Boot Blockers

| Area | Pass Criteria | Evidence |
| --- | --- | --- |
| Boot | Reaches setup wizard or launcher without bootloop | Boot time, logcat |
| Init | No repeated critical init service failures | `logcat -b all`, `dmesg` |
| VINTF | No fatal framework/vendor manifest mismatch | `lshal`, VINTF logs |
| SELinux | Enforcing mode without permissive dependency | `getenforce`, denials |
| Storage | `/data`, `/system`, `/vendor`, `/product`, `/odm`, `/prism`, `/optics` mount | `mount`, recovery log |
| Display | QHD panel renders correctly | Screenshot/photo |
| Touch | Touch input works through setup | Manual test |
| RIL | SIM detected and network registers | Settings, calls |
| Audio HAL | `vendor.audio-hal` and `audioserver` stay running | init state, PID, logcat, audio dumpsys |

## Hardware Smoke

| Feature | Pass Criteria | Notes |
| --- | --- | --- |
| Wi-Fi | Scan, connect, internet | Test 2.4 and 5 GHz |
| Mobile data | LTE data works | APN auto-load |
| Calls | Incoming and outgoing calls | Earpiece and speaker |
| SMS | Send and receive SMS | Include OTP-style message |
| Audio | Speaker, earpiece, USB-C and microphones | Complete the audio matrix below |
| Bluetooth | Pairing, A2DP and SCO audio/mic | Watch route and profile regressions |
| GPS | Locks outdoors | Capture approximate TTFF |
| NFC | Toggle and tag read | Test NFC cover if available |
| USB | ADB and MTP | Replug test |
| Charging | Wired fast charge, thermal sane | Battery stats |
| Sensors | Rotation, proximity, light, compass | Sensor test app |
| Fingerprint | Enroll and unlock | Test after reboot |
| AOD | Shows and wakes correctly | Burn-in movement visible |
| SPen | Pointer and button basics | AirAction is not a release blocker |

## Audio

| Route or function | Pass Criteria | Evidence |
| --- | --- | --- |
| HAL lifetime | `vendor.audio-hal` and `audioserver` remain running without restart loops | `getprop`, `pidof`, logcat |
| Media speaker | Clean playback, both channels where applicable, working volume/mute | Recording plus audio dumpsys |
| Earpiece | Incoming and outgoing call audio is clear | Call test |
| Speakerphone | Route switches both directions during a live call | Call test and logcat |
| Main microphone | Voice Recorder captures intelligible audio | Saved recording |
| Telephony microphones | Remote party hears normal uplink in handset and speakerphone modes | Two-way call |
| Camera microphones | Front and rear video contain synchronized, clean audio | Saved clips |
| Bluetooth A2DP | Media plays and reconnects after Bluetooth toggle | Audio policy dump |
| Bluetooth SCO | Call downlink and headset microphone both work | Two-way call |
| USB-C audio | Headset or DAC playback works; test its microphone if present | Replug and route test |
| Alerts | Ringtone, alarm and notification play at the expected stream volumes | Manual test |
| Effects | Equalizer, SoundAlive/Dolby and spatial audio do not crash or mute output | UI test and logcat |
| Haptic audio | Haptic generator and normal vibration remain functional | Manual test |
| Power cycle | Audio still works after suspend/resume and a warm reboot | Repeat speaker/mic test |

## Camera

| Feature | Pass Criteria | Notes |
| --- | --- | --- |
| Launch | SamsungCamera opens repeatedly | No crash after force stop |
| Photo | Rear and front capture save | Check Gallery |
| Video | Rear and front 1080p record | Playback audio/video |
| UW | `0.5x` preview and capture | Known regression area |
| Tele | Tele shortcut works | Verify actual lens or crop |
| Portrait | Rear/front portrait capture | Watch EGL/camera flicker |
| Night | Capture completes | Thermal check |
| Pro video | UI opens, records basic clip | 4K if available |
| HDR10+ | Toggle and record if exposed | Known regression area |
| Lens switch | 20 repeated switches without crash | Include video mode |
| Gallery AI | Edit/remaster launches | Watch missing model crashes |

## Software Features

| Feature | Pass Criteria | Notes |
| --- | --- | --- |
| Galaxy AI | Core features open without crash loops | Disable heavy offenders if needed |
| Now Brief | Opens or is cleanly removed | No background crash loop |
| Secure Folder | Creates or is intentionally disabled | Document final state |
| Good Lock | Installs and opens core modules | Gesture/nav options |
| Play Integrity | Document state only | Do not block alpha on pass |
| Updates | Galaxy Store and Play Store update apps | Watch signature conflicts |

## Stability

| Test | Pass Criteria | Evidence |
| --- | --- | --- |
| Idle | 24-hour idle without reboot | Battery graph, logs |
| Camera thermal | 30-minute camera/video run | Temperature and throttling |
| App install | Install, update, uninstall common apps | Play Store logs |
| Reboot | 5 clean reboots | No data corruption |
| Dirty flash | Flash over previous alpha | Recovery log |
| Clean flash | Flash from wiped data | Recovery log |

## Required Logs For Failed Builds

```bash
adb shell getprop > getprop.txt
adb shell dmesg > dmesg.txt
adb logcat -b all -d > logcat_all.txt
adb shell lshal > lshal.txt
adb shell dumpsys SurfaceFlinger > dumpsys_surfaceflinger.txt
adb shell dumpsys thermalservice > dumpsys_thermalservice.txt
adb shell dumpsys audio > dumpsys_audio.txt
adb shell dumpsys media.audio_flinger > dumpsys_media_audio_flinger.txt
adb shell dumpsys media.audio_policy > dumpsys_media_audio_policy.txt
adb shell 'cat /proc/asound/cards; cat /proc/asound/pcm' > proc_asound.txt
adb pull /data/tombstones tombstones
adb pull /sys/fs/pstore pstore
```
