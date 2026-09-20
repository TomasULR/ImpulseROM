# d2s API 36 Native ABI Closure

This report records the offline native-linker audit used to select the
Android 16 multilib compatibility source for the One UI 8.5 d2s port. It is a
build gate and a baseline for comparing the linker configuration generated on
the device after first boot.

## Audited inputs

```text
Target vendor: alpha3 d2s vendor image (N975F Android 12 hardware stack)
Multilib:      SM-S711B/EUX
Build:         S711BXXSGGZF2/S711BOXMGGZF2/S711BXXSGGZF2
Android:       16 / API 36 / One UI 8.5
VNDK:          31
```

The S711B snapshot supplies the complete `/system/lib` tree, runtime and i18n
APEX packages, the bootstrap linker, and the VNDK31 APEX. It is not used as a
replacement vendor, modem, bootloader, TrustZone, or kernel.

## Alpha3 latent failure

Alpha3 contained eight executable vendor services with
`PT_INTERP=/system/bin/linker`, but its system image had no such interpreter.
Its runtime and i18n APEX packages were arm64-only and `/system/lib` contained
only 16 ARM32 ELF objects. The eight processes therefore could not have
started even after the earlier init property-context abort was fixed:

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

## Recursive dependency result

The audit follows every `DT_NEEDED` edge while preserving Android linker
namespace order: vendor-local providers first, VNDK31 `vndkcore`/`vndksp`
providers next, then permitted system LLNDK/runtime exports.

| Process | Loaded ELF | `DT_NEEDED` edges | Missing | Namespace-blocked |
| --- | ---: | ---: | ---: | ---: |
| boringssl self-test | 7 | 15 | 0 | 0 |
| Widevine provisioning | 16 | 47 | 0 | 0 |
| camera provider | 64 | 603 | 0 | 0 |
| audio service | 22 | 93 | 0 | 0 |
| IVA service | 33 | 171 | 0 | 0 |
| OMX service | 266 | 2,556 | 0 | 0 |
| Widevine DRM | 31 | 179 | 0 | 0 |
| CAS service | 28 | 153 | 0 | 0 |

The closure uses 35 VNDK31 libraries, the runtime `libc.so`, `libdl.so`, and
`libm.so`, plus these permitted system exports:

```text
libEGL.so
libGLESv2.so
libGLESv3.so
libbinder_ndk.so
liblog.so
libmediandk.so
libnativewindow.so
libvndksupport.so
```

There are 53 duplicate basenames across vendor, system, and VNDK. A validator
that searches only by basename can therefore produce a false pass. The final
work directory must preserve `ro.vndk.version=31`, the VNDK31 APEX, and the
vendor-first namespace route.

## Versioned symbols

The audit checked 17,012 versioned imports:

- 16,998 resolved with the exact requested symbol version;
- 0 were unresolved;
- 14 resolved only because the API 36 provider exports the same unversioned
  base symbol.

The 14 fallback warnings are limited to:

```text
libui.so -> libsync.so:
  sync_file_info, sync_file_info_free, sync_merge, sync_wait

libstagefright_bufferqueue_helper_vendor.so -> libEGL.so:
  eglClientWaitSyncKHR, eglDestroySyncKHR, eglGetError

libmediadrm.so -> libmediametrics.so:
  mediametrics_create, mediametrics_delete, mediametrics_selfRecord,
  mediametrics_setCString, mediametrics_setInt32, mediametrics_setInt64,
  mediametrics_setUid
```

These are warnings rather than offline missing-symbol failures. The dynamic
linker during boot is the final authority.

## Required assembled-image gates

Before packaging, the work directory must prove all of the following:

- the runtime, i18n, VNDK31, bootstrap linker, and `/system/lib` payloads are
  byte-identical to the selected GZF2 extraction;
- `/system/bin/linker` and the bionic entry points are exact symlinks into the
  runtime APEX, not dangling paths;
- `vendor/build.prop` declares `ro.vndk.version=31`;
- the framework and vendor VINTF files both select vendor NDK version 31;
- no second `com.android.vndk.v*.apex` can compete with VNDK31;
- all property-context files merge without duplicate exact or prefix entries.

After first boot, capture `/linkerconfig/ld.config.txt`,
`/apex/apex-info-list.xml`, and the mounted runtime/VNDK paths. The generated
vendor namespace must route the 35 audited libraries to VNDK31, the eight
system exports to the system namespace, and bionic to the runtime APEX.
