# Impulse ROM — installation guide (Galaxy Note10+ Exynos, d2s)

One UI 8.5 / Android 16 for the SM-N975F, ported from Galaxy S24 FE firmware.

> **Release candidate instructions: a complete clean-install test is still required.**
> **Dirty flashing from EternityROM 5.5 is unsupported.** Back up your data and
> use the clean-install procedure; in-place migration and signing compatibility
> have not been validated.
> **This guide assumes you are starting from stock Samsung firmware.**
> Read the whole page before you touch anything. Every irreversible step is
> marked. If any check on this page fails, stop.

---

## 1. Is this ROM for your phone?

Run this on the phone (Settings → About phone) or `adb shell getprop ro.boot.em.model`.

| Your model | Codename | Supported |
| --- | --- | --- |
| **SM-N975F** | d2s | **Yes — this ROM** |
| SM-N975U / N975U1 / N975W | d2q | No — Snapdragon, different SoC |
| SM-N9750 | d2x | No — not yet ported |
| SM-N976B / N976N | d2xks | No — 5G variant, not yet ported |
| SM-N970F | d1 | No — Note10, not Note10+ |

The installer refuses to run on anything whose `ro.boot.em.model`,
`ro.product.model` or `ro.product.device` does not match `SM-N975F` / `d2s`.
Do not try to bypass that check.

---

## 2. What you permanently give up

These are **not reversible**, not by reflashing stock, not by warranty service.

- **Knox is blown.** Unlocking the bootloader burns a one-way e-fuse.
  Stock Knox-dependent features can be affected. Secure Folder is reported
  working on Impulse by a tester; preserve that compatibility and retest it on
  each release. This does not restore the hardware Knox state.
- **Warranty.** Check the terms applicable to your device and location.
- **Play Integrity.** Banking and some streaming apps may refuse to run.
  Expect `BASIC` at best. Some apps will never work again.

If any of those matter to you, stop here and keep stock firmware.

---

## 3. Known state of this release

This is an **alpha**. Be honest with yourself about what that means.

The connected Alpha 1 device boots with SELinux enforcing and a 1440x3040
display. Its Camera package is present, but a tester reports Camera missing
after installation. Camera availability on a clean install and photo/video
capture are release gates, not established working features of the next build.

Known broken or unverified:

| Item | Status |
| --- | --- |
| Wireless charging | Reported broken under enforcing and working under permissive; needs charger-time AVC evidence. Keep enforcing. |
| Secure Folder | Tester reports working; regression testing required. |
| Samsung Pay / Wallet | Not supported or promised by this port. |
| Samsung Health | **Does not work.** Refuses to start on a Knox-tripped device |
| Photo editor | Matching FilterProvider is present, but a separate native memory crash remains under investigation. |
| Camera AI features / Gallery OCR | Unstable — NPU model loading fails |
| Play Integrity | No Device/Strong verdict promised; not rechecked for this release. |

See `FIXES_IMPULSE.md` for the full engineering detail.

---

## 4. Before you start — the rollback kit

**Do not skip this.** Download these *before* unlocking anything, and verify
they are complete. This is what gets you back to a working phone.

1. **Stock Odin firmware** for your exact CSC. The reference build used by this
   project is `SM-N975F/BTU`, `N975FXXS9HWHA` (Android 12, bootloader binary 9).
   Get it from a firmware mirror and check the MD5 Samsung appends.
   You need all five files: `AP`, `BL`, `CP`, `CSC`, `HOME_CSC`.
2. **Odin** (Windows) or **Heimdall/Thor** (Linux).
3. **TWRP for d2s** — a build that can mount and resize ext4.
4. **A full backup of your data.** Photos, messages, 2FA seeds, everything.
   Installation formats the phone.
5. **Your EFS partition backed up** from TWRP once you have recovery. Losing
   EFS loses your IMEI, and that is not something a reflash fixes.

Charge the phone to at least **60%**. A phone that dies mid-flash is the single
most common way people brick one.

---

## 5. Installation

### 5.1 Enable developer options

Settings → About phone → Software information → tap *Build number* 7 times.
Then Settings → Developer options → enable **OEM unlocking**.

If **OEM unlocking is greyed out or missing**, your phone is not eligible yet.
Sign in to a Google account, connect to the internet, and leave the phone for
up to 7 days — Samsung enforces a rolling wait after a factory reset. Do not
proceed until the toggle is available.

### 5.2 Unlock the bootloader — *irreversible*

1. Power off.
2. Hold **Volume Up + Volume Down** and plug in USB to reach Download mode.
3. Long-press **Volume Up** to enter the unlock prompt.
4. Confirm the unlock. **The phone wipes itself.**
5. Boot to Android once, complete setup enough to reach Developer options,
   and confirm **OEM unlocking** is still on and now greyed out as unlocked.

This is where Knox is blown. There is no way back.

### 5.3 Flash TWRP

1. Power off, enter Download mode again.
2. In Odin, put the TWRP `.tar` in the **AP** slot.
3. Uncheck **Auto Reboot**.
4. Flash. When it finishes, immediately hold **Volume Up + Power** to boot
   straight into TWRP. If you let it boot to Android, stock recovery is
   restored and you start over.
5. In TWRP, allow modifications when prompted.

### 5.4 Back up EFS

TWRP → Backup → select **EFS** (and **Modem** if listed) → swipe to back up.
Copy that backup off the phone to your computer. Do this now, not later.

### 5.5 Format data — *destroys all user data*

TWRP → Wipe → **Format Data** → type `yes`.

This must be **Format Data**, not "Wipe" and not "Factory Reset". Format Data
removes encryption. The other two leave the old encryption in place and the ROM
will not boot correctly.

### 5.6 Flash Impulse ROM

1. Copy `ImpulseROM_v1.0-oneui85-alpha1_<commit>_<date>_d2s-sign.zip` to the
   phone or an SD card / OTG drive.
2. **Verify the checksum before flashing:**
   ```
   sha256sum ImpulseROM_*.zip
   ```
   Compare against the SHA-256 published with the release. If it does not
   match, do not flash it — re-download.
3. TWRP → Install → select the ZIP → swipe to flash.
4. The installer prints a summary and waits. Press **Volume Up** to continue,
   or hold **Volume Down + Power** for 7 seconds to abort.
5. Installation takes a long while. The ZIP is around 5.8 GB and the installer
   expands filesystems with `resize2fs` afterwards. **Do not interrupt it.**
6. Reboot to system.

First boot takes **10 to 20 minutes**. It is normal for the phone to sit on the
boot animation, and normal for it to feel slow for the first hour while the
runtime compiles apps in the background. Do not reboot during this.

---

## 6. After installation

- Skip Google/Samsung sign-in on first boot until the phone settles.
- Battery statistics will be nonsense for the first few charge cycles.
- If you want the **Extra dim** accessibility feature:
  Settings → Accessibility → Vision enhancements → **Extra dim**.

### Photo editor filters crash

The build pins the matching-generation Filter Provider. This addresses the
previous malformed filter-name defect, not the separate native editor crash
observed on 17 September 2026. If you
are on an older build and the editor dies as soon as you open the Filters tab,
the only real fix is updating the ROM — clearing the app's data does not help,
because the old provider re-creates the bad entry on the next launch.

---

## 7. If it does not boot

A bootloop is recoverable. A panicked Odin flash of the wrong file often is not.

1. Hold **Volume Down + Power** for 7 seconds to force off.
2. Boot to TWRP (**Volume Up + Power**).
3. Capture the log **before** you wipe anything — it is the only way anyone can
   help you:
   ```
   adb pull /tmp/recovery.log
   adb shell "cat /proc/last_kmsg" > last_kmsg.txt
   ```
4. Try **Format Data** once more, then reboot.
5. If it still fails, go back to stock: Download mode → Odin →
   `BL` + `AP` + `CP` + `CSC` (use `CSC`, **not** `HOME_CSC`, for a clean wipe).
   Do **not** tick Re-Partition and do **not** supply a PIT file.

---

## 8. Reporting a problem

Include all of these or nobody can help:

- Exact ZIP filename and its SHA-256
- Model from `ro.boot.em.model`
- What you did immediately before the problem
- `adb logcat -b all -d > logcat.txt` and `adb bugreport`

---

## 9. Licence and origin

Impulse ROM is GPLv3, forked from [EternityROM](https://github.com/Ocin4ever/EternityROM)
by Ocin4ever, which is built on the ROM build system by Salvo Giangreco
(salvo_giangri). Full source for this fork must be published alongside every
binary release — that is a licence obligation, not a courtesy.
