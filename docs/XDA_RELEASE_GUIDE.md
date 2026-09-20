# Publishing Impulse ROM on XDA

Practical checklist for releasing as a Galaxy Note10+ (Exynos) One UI 8.5 ROM.

---

## 0. Do not post yet

Publish only after the current build has been **flashed and lived with**. A ROM
thread that bootloops on day one is very hard to recover reputationally, and on
XDA people flash first and read second.

Minimum before posting:

- A clean-flash test from stock on a device that is not your daily driver, if
  you can manage it.
- At least 48 hours of uptime with no `system_server` crash in
  `logcat -b crash`.
- Wireless charging either fixed or **explicitly listed as broken** in the OP.

---

## 1. Where it goes

**Forum:** *Samsung Galaxy Note 10+ → Note 10+ ROMs, Kernels, Recoveries & Other Development*

Make sure you are in the **Exynos** section, not the Snapdragon one. The Note10+
has separate device forums and posting an Exynos-only ROM in the Snapdragon
forum is how people hard-brick phones.

**Posting rights:** XDA restricts new accounts from starting threads in
development forums. If your account is new, build up post history in the general
Note10+ forum first by actually helping people.

---

## 2. Thread title

The convention that people search for:

```
[ROM][d2s][SM-N975F][16] Impulse ROM v1.0 | One UI 8.5 | Android 16
```

Keep `d2s`, `SM-N975F`, `One UI 8.5` and `Android 16` literally in the title.
Those are the search terms. Do not use a prefix like `[STABLE]` on an alpha.

---

## 3. Opening post structure

XDA readers scan in this order. Follow it.

### 3.1 One-line pitch
> One UI 8.5 / Android 16 on the Galaxy Note10+ Exynos, ported from Galaxy S24 FE firmware.

### 3.2 Big red warning block
Bootloader unlock trips Knox permanently. Samsung Pay / Wallet are not supported. Secure Folder is reported working
on Impulse and must be regression-tested. Installation formats the device. SM-N975F only.

### 3.3 What works / What does not
Two plain lists. **Put the broken list first if it is long.** Being upfront about
wireless charging costs you nothing and buys you enormous goodwill. Hiding it
gets you 40 angry replies in week one.

### 3.4 Installation
Link to `INSTALL.md` but also inline the short version. People will not click.

### 3.5 Downloads
Filename, size, and **SHA-256 in the post itself**, not only on the mirror.

### 3.6 Changelog
### 3.7 Source code
### 3.8 Credits
### 3.9 Reporting bugs — demand `adb logcat -b all -d` and `adb bugreport`

---

## 4. Hosting the 5.8 GB ZIP

**GitHub Releases will not work.** The per-file limit is 2 GB and the ZIP is
around 5.8 GB. Do not plan around it.

Workable options:

| Host | Notes |
| --- | --- |
| SourceForge | Free, unlimited size, gives download stats, well accepted on XDA |
| AndroidFileHost | Purpose-built for this, but approval can be slow |
| Your own server | Full control, you pay the bandwidth |
| Mega / Google Drive | Tolerated but disliked — quota limits break downloads |

Whatever you pick, **publish the SHA-256 next to the link and in the OP**. It is
the only integrity check users have, because the flashable ZIP is not signed.

Consider also publishing a detached GPG signature of the checksum file:

```bash
sha256sum ImpulseROM_*.zip > SHA256SUMS
gpg --armor --detach-sign SHA256SUMS
```

Put your public key fingerprint in the OP. This is what lets people verify a
mirror did not tamper with the file.

---

## 5. GPL obligations — not optional

Impulse ROM is GPLv3 and the kernel is GPLv2. XDA enforces this, and so does
the licence.

You must:

1. **Publish the full source of your fork** before or at the same time as the
   binary. A public GitHub repo is fine. Link it in the OP.
2. **Publish kernel source** if you ship a modified kernel. You currently ship
   **ExtremeKRNL** built by ExtremeXT — link to its source repository rather
   than claiming it.
3. **Keep every upstream copyright header intact.** Do not strip them. This is
   already handled in the tree; keep it that way.

---

## 6. Credits block — copy this into the OP

```
Credits:
- Ocin4ever — EternityROM, which Impulse ROM is forked from
- Salvo Giangreco (@salvo_giangri) — the ROM build system this is built on
- ExtremeXT — ExtremeKRNL kernel
- rifsxd and the KernelSU-Next project — root solution included in this build
- Samsung — original firmware
```

Crediting upstream generously is not just a licence requirement. On XDA it is
the single biggest factor in whether a new ROM is treated as legitimate or as a
rip. A thread that says "based on EternityROM, thanks to Ocin4ever" reads as
honest work. One that pretends to be built from nothing reads as stolen.

Before you post, it is worth messaging Ocin4ever to say you have forked and
rebranded it. You are not obliged to, but it prevents the single most common
way these threads go wrong.

---

## 7. Disclose that root is included

This build ships **KernelSU-Next** (`com.rifsxd.ksunext`, v1.0.9). Say so in the
OP. Some users specifically want a root-free ROM, and shipping root silently
will be read as a security problem — reasonably so.

---

## 8. Screenshots

Post 5 to 8. About phone (showing One UI 8.5 / Android 16), home screen,
Settings, Quick Settings, and the Extra dim toggle since that is a real selling
point on this device. XDA renders images inline; use the attachment uploader
rather than an external host that will rot.

---

## 9. After posting

- Subscribe to your own thread.
- Answer the first 20 questions properly. Thread reputation is set in week one.
- Keep a running changelog in post #2, which you can edit forever.
- Never delete a download. People roll back.
