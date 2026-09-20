TARGET_COMPAT_SOURCE="$FW_DIR/$TARGET_FIRMWARE_PATH"
# The port boots at native 1440x3040. Stock d2s supplies 420 for its
# lower-resolution mode and ro.sf.init.lcd_density=560 for native resolution.
# The API 36 donor does not apply that legacy initialization, leaving a tiny
# UI on a clean install. Use the target's native-resolution density without
# overriding any user's persisted display-size preference in /data.
TARGET_NATIVE_DENSITY="$(sed -n 's/^ro.sf.init.lcd_density=//p' \
    "$TARGET_COMPAT_SOURCE/vendor/build.prop")"
if [[ "$TARGET_NATIVE_DENSITY" != "560" ]]; then
    ABORT "Unexpected d2s native display density: $TARGET_NATIVE_DENSITY"
fi
SET_PROP "vendor" "ro.sf.lcd_density" "$TARGET_NATIVE_DENSITY"
unset TARGET_NATIVE_DENSITY

TARGET_FCM_LEVEL="$(sed -n 's/.*target-level="\([^"]*\)".*/\1/p' \
    "$TARGET_COMPAT_SOURCE/vendor/etc/vintf/manifest.xml" | head -n 1)"

if [[ "$TARGET_FCM_LEVEL" != "3" ]]; then
    ABORT "Unexpected d2s target FCM level: ${TARGET_FCM_LEVEL:-missing}"
fi

for TARGET_FCM_MATRIX_LEVEL in 3 4; do
    TARGET_FCM_MATRIX="system/etc/vintf/compatibility_matrix.$TARGET_FCM_MATRIX_LEVEL.xml"
    if [ ! -f "$TARGET_COMPAT_SOURCE/system/$TARGET_FCM_MATRIX" ]; then
        ABORT "Target firmware is missing $TARGET_FCM_MATRIX"
    fi

    LOG "- Restoring d2s framework compatibility matrix level $TARGET_FCM_MATRIX_LEVEL"
    ADD_TO_WORK_DIR "$TARGET_COMPAT_SOURCE" "system" "$TARGET_FCM_MATRIX" \
        0 0 644 "u:object_r:system_file:s0"
done

# The source's Knox Matrix daemon hard-requires Samsung's modern Fkeymaster
# AIDL HAL. Exynos9825 exposes its older Keymaster implementation and cannot
# register that proprietary service. Keeping the consumer produces a permanent
# fabric_crypto abort/restart loop, so remove this self-contained unsupported
# feature and its now-untruthful framework requirement without replacing any
# boot-critical DeKnox blobs.
LOG "- Removing unsupported Knox Matrix/Fkeymaster consumers"
for KNOX_MATRIX_FILE in \
    "system/bin/fabric_crypto" \
    "system/etc/init/fabric_crypto.rc" \
    "system/etc/permissions/FabricCryptoLib.xml" \
    "system/etc/permissions/privapp-permissions-com.samsung.android.kmxservice.xml" \
    "system/etc/vintf/manifest/fabric_crypto_manifest.xml" \
    "system/framework/FabricCryptoLib.jar" \
    "system/lib64/com.samsung.security.fabric.cryptod-V1-cpp.so" \
    "system/lib64/vendor.samsung.hardware.security.fkeymaster-V1-cpp.so" \
    "system/lib64/vendor.samsung.hardware.security.fkeymaster-V1-ndk.so" \
    "system/priv-app/KmxService"
do
    DELETE_FROM_WORK_DIR "system" "$KNOX_MATRIX_FILE"
done

FKEYMASTER_MATRIX="$WORK_DIR/system/system/etc/vintf/compatibility_matrix.device.xml"
FKEYMASTER_MATRIX_COUNT="$(grep -c \
    '<name>vendor.samsung.hardware.security.fkeymaster</name>' \
    "$FKEYMASTER_MATRIX")"
if [ "$FKEYMASTER_MATRIX_COUNT" != "1" ]; then
    ABORT "Expected one framework Fkeymaster requirement, found $FKEYMASTER_MATRIX_COUNT"
fi
sed -i '/^[[:space:]]*<hal format="aidl">[[:space:]]*$/ {
    :fkeymaster_hal
    N
    /<\/hal>/!b fkeymaster_hal
    /<name>vendor\.samsung\.hardware\.security\.fkeymaster<\/name>/d
}' "$FKEYMASTER_MATRIX"

# The API 36 KnoxGuard framework and client require a modern AIDL KG provider
# and matching TEE application. Neither exists in the Exynos9825 target
# firmware. On this device the unavailable provider returns TA state Error and
# the framework fail-safe installs a remote lock despite device_locked=0. The
# accompanying SystemServer patch prevents that unsupported consumer from
# starting; remove its package and declarative references too. Keep the dormant
# multilib client libraries because they are part of the validated API 36 ABI
# snapshot and may still satisfy link-time dependencies outside KnoxGuard.
# Persistent KG state in /data and every hardware-backed security partition are
# deliberately left untouched.
LOG "- Removing unsupported Android 16 KnoxGuard consumer"
for KNOX_GUARD_FILE in \
    "system/etc/permissions/privapp-permissions-com.samsung.android.kgclient.xml" \
    "system/etc/permissions/signature-permissions-com.samsung.android.kgclient.xml" \
    "system/priv-app/KnoxGuard"
do
    DELETE_FROM_WORK_DIR "system" "$KNOX_GUARD_FILE"
done

KNOX_GUARD_MATRIX_COUNT="$(grep -c \
    '<name>vendor.samsung.hardware.tlc.kg</name>' \
    "$FKEYMASTER_MATRIX")"
if [ "$KNOX_GUARD_MATRIX_COUNT" != "1" ]; then
    ABORT "Expected one framework KnoxGuard requirement, found $KNOX_GUARD_MATRIX_COUNT"
fi
sed -i \
    -e '/vendor\/samsung\/interfaces\/tlc\/kg\/2\.0\/aidl\/vendor\.samsung\.hardware\.tlc\.kg-matrix\.xml/d' \
    -e '/^[[:space:]]*<hal format="aidl">[[:space:]]*$/ {
        :knoxguard_hal
        N
        /<\/hal>/!b knoxguard_hal
        /<name>vendor\.samsung\.hardware\.tlc\.kg<\/name>/d
    }' \
    "$FKEYMASTER_MATRIX"

KNOX_GUARD_CONFIGS=(
    "system/etc/broadcast_allowlist.xml"
    "system/etc/deviceidle/reviewed_allowlist.xml"
    "system/etc/irremovable_list.txt"
    "system/etc/permissions/platform.xml"
    "system/etc/sysconfig/allowed-system-preload-apps.xml"
    "system/etc/sysconfig/required-packages.xml"
    "system/etc/sysconfig/safe-mode-allow-list.xml"
)
for KNOX_GUARD_CONFIG in "${KNOX_GUARD_CONFIGS[@]}"; do
    KNOX_GUARD_CONFIG_PATH="$WORK_DIR/system/$KNOX_GUARD_CONFIG"
    if [ ! -f "$KNOX_GUARD_CONFIG_PATH" ]; then
        ABORT "KnoxGuard declarative config is missing: $KNOX_GUARD_CONFIG"
    fi
    KNOX_GUARD_CONFIG_COUNT="$(grep -c 'com.samsung.android.kgclient' \
        "$KNOX_GUARD_CONFIG_PATH")"
    if [ "$KNOX_GUARD_CONFIG_COUNT" -lt 1 ]; then
        ABORT "Expected KnoxGuard reference in $KNOX_GUARD_CONFIG"
    fi
    sed -i '/com\.samsung\.android\.kgclient/d' "$KNOX_GUARD_CONFIG_PATH"
done

# Secure Folder must not key its availability to the obsolete ICCC property.
# The d2s services.jar patch below handles the actual SAK/DRK results while
# keeping KnoxGuard and every hardware-backed security partition untouched.
SET_PROP "system" "ro.config.iccc_version" --delete

# Current Android releases keep generated Aconfig maps below /metadata. The
# Exynos9825 partition layout predates that partition, leaving the read-only
# system-root mount point as the only /metadata path. Supply a small ephemeral
# backing store before aconfigd's own early-init action. The maps are rebuilt
# from signed system/APEX inputs on every boot, so persistence is unnecessary;
# /data and every user file remain untouched.
ACONFIG_INIT_RC="$WORK_DIR/system/system/etc/init/aconfigd.rc"
ACONFIG_EARLY_INIT_COUNT="$(grep -c '^on early-init$' "$ACONFIG_INIT_RC")"
if [ "$ACONFIG_EARLY_INIT_COUNT" != "1" ]; then
    ABORT "Expected one Aconfig early-init action, found $ACONFIG_EARLY_INIT_COUNT"
fi
sed -i '/^on early-init$/a\
    # d2s: emulate the missing modern metadata partition for generated flags.\
    mount tmpfs tmpfs /metadata nodev noexec nosuid mode=0775,uid=0,gid=1000,size=64m' \
    "$ACONFIG_INIT_RC"

# The API 33 vendor adaptation adds the AIDL health service needed by current
# framework code, but it also deleted the truthful HIDL 2.1 service required by
# the d2s FCM3 contract. The two binder interfaces have different formats and
# can coexist; retain both instead of weakening or falsifying the matrix.
LOG "- Restoring the d2s HIDL health compatibility service"
for TARGET_HEALTH_FILE in \
    "bin/hw/android.hardware.health@2.1-service-samsung" \
    "etc/init/android.hardware.health@2.1-service-samsung.rc" \
    "etc/vintf/manifest/android.hardware.health@2.1-samsung.xml" \
    "lib/android.hardware.health@2.1.so" \
    "lib64/android.hardware.health@2.1.so"
do
    ADD_TO_WORK_DIR "$TARGET_COMPAT_SOURCE" "vendor" "$TARGET_HEALTH_FILE"
done

# One UI 8.5/API 36 libaudiohal no longer ships a HIDL 5.0 client adapter. The
# d2s vendor manifest and passthrough implementations were still 5.0, so
# audioserver could not create either IDevicesFactory or IEffectsFactory. Keep
# the device-specific Exynos9825 legacy C HAL, mixer and effects untouched, but
# expose them through the generic Android 12/VNDK31 HIDL 6.0 wrappers from the
# same multilib firmware that supplies this build's 32-bit runtime.
LOG_STEP_IN "- Installing the d2s HIDL audio 6.0 compatibility bridge"
if [ -z "${MULTILIB_FIRMWARE:-}" ]; then
    ABORT "MULTILIB_FIRMWARE is required for the d2s audio bridge"
fi

AUDIO_BRIDGE_SOURCE="$FW_DIR/$(cut -d "/" -f 1 -s <<< "$MULTILIB_FIRMWARE")_$(cut -d "/" -f 2 -s <<< "$MULTILIB_FIRMWARE")"
AUDIO_BRIDGE_MARKER="S711BXXSGGZF2/S711BOXMGGZF2/S711BXXSGGZF2"
if [ "$(cat "$AUDIO_BRIDGE_SOURCE/.extracted" 2> /dev/null)" != \
        "$AUDIO_BRIDGE_MARKER" ]; then
    ABORT "Unexpected d2s audio bridge firmware in $AUDIO_BRIDGE_SOURCE"
fi

while read -r AUDIO_BRIDGE_SHA256 AUDIO_BRIDGE_FILE; do
    [ -n "$AUDIO_BRIDGE_FILE" ] || continue
    AUDIO_BRIDGE_INPUT="$AUDIO_BRIDGE_SOURCE/vendor/$AUDIO_BRIDGE_FILE"
    if [ ! -f "$AUDIO_BRIDGE_INPUT" ]; then
        ABORT "Audio bridge input is missing: $AUDIO_BRIDGE_INPUT"
    fi
    if [ "$(sha256sum "$AUDIO_BRIDGE_INPUT" | cut -d " " -f 1)" != \
            "$AUDIO_BRIDGE_SHA256" ]; then
        ABORT "Audio bridge input hash changed: $AUDIO_BRIDGE_FILE"
    fi

    ADD_TO_WORK_DIR "$AUDIO_BRIDGE_SOURCE" "vendor" "$AUDIO_BRIDGE_FILE" || \
        ABORT "Failed to install audio bridge file: $AUDIO_BRIDGE_FILE"
    if [ "$(sha256sum "$WORK_DIR/vendor/$AUDIO_BRIDGE_FILE" | cut -d " " -f 1)" != \
            "$AUDIO_BRIDGE_SHA256" ]; then
        ABORT "Installed audio bridge hash mismatch: $AUDIO_BRIDGE_FILE"
    fi
done <<'EOF'
57092f6b3e4af8877d4e23bd32aea197f3b5df9bb7c61f74d3ce3f99ca16aeef lib/hw/android.hardware.audio@6.0-impl.so
0c76d753d51005140b6d029923a53ab8c3b0a559c5536288ddecfd45f3ba275b lib/hw/android.hardware.audio.effect@6.0-impl.so
109bfdee3c58e6b7d297523aeb4b71b4d6782be843855c21aa6da191b1c50e20 lib/android.hardware.audio.common@6.0.so
73cf8256fb62e128cd47b3e1ae2c5013c6c0ca6c4495ac3b93d22476a1de8606 lib/android.hardware.audio.common@6.0-util.so
1f336b8025d87ff702d489d35c4fac1468263530b90102af74e3c713c35656c5 lib/android.hardware.audio@6.0.so
53a08a73458bfc64a0612f8e4fcd4cf63d91121872da1238c8ceb9b726ddf4d5 lib/android.hardware.audio@6.0-util.so
1c8fef364f95e9142ff0f43ab1f76a8278fcd17752383a36765f2d62e0e5ceb1 lib/android.hardware.audio.effect@6.0.so
e606e14965234e9e81d761a530b4b8ccacc66853d029087fce9a93f70de00f6a lib/android.hardware.audio.effect@6.0-util.so
8a34942d275bc565cdbd811755cc15aaa7fc8d75f891678fe2db10378644054e lib/soundfx/libswspatializer.so
444f4f4bf395eed954eab0f7a6396be1e34a0884a6ceccd0efe337cf1899d15f lib/spatializer-aidl-cpp.so
b5bf81305153f730f34f99e3162511817c66ac491ba760c9f06d80c23c56b798 lib64/soundfx/libswspatializer.so
57b159e54bdba0727617481ad891933a51090d0325aefe5c0e7e657d10f6d633 lib64/spatializer-aidl-cpp.so
EOF

AUDIO_MANIFEST="$WORK_DIR/vendor/etc/vintf/manifest.xml"
sed -i \
    -e '/<name>android.hardware.audio<\/name>/,/<\/hal>/ { s/<version>5\.0<\/version>/<version>6.0<\/version>/; s/@5\.0::IDevicesFactory/@6.0::IDevicesFactory/; }' \
    -e '/<name>android.hardware.audio.effect<\/name>/,/<\/hal>/ { s/<version>5\.0<\/version>/<version>6.0<\/version>/; s/@5\.0::IEffectsFactory/@6.0::IEffectsFactory/; }' \
    "$AUDIO_MANIFEST"
LOG_STEP_OUT

# Android 16 25Q4's Tethering APEX refuses every kernel older than 5.10 before
# it attempts to load a single BPF object. The d2s kernel exposes the backported
# network-BPF baseline as 5.4.186, so the hard gate reboots with status 7 even
# though all earlier Android U and Q2 gates pass. Keep the reported version
# truthful for the loader's later per-object compatibility decisions and bypass
# only the new unconditional 25Q4 refusal.
#
# Modifying the compressed APEX would invalidate both of its signatures. Extract
# its complete bin directory into /system instead, patch one exact instruction,
# and bind-mount that directory over the original after APEXd has activated it.
# Executing through the original /apex path preserves the Tethering linker
# namespace. All inputs and the one output are hash-pinned so source drift fails
# the build rather than silently producing an unsafe patch.
LOG_STEP_IN "- Installing the d2s Android 16 NetBpfLoad compatibility layer"
BPF_APEX="$WORK_DIR/system/system/apex/com.google.android.tethering_compressed.apex"
BPF_COMPAT_ROOT="$WORK_DIR/system/system/etc/netbpfload_compat"
BPF_COMPAT_BIN="$BPF_COMPAT_ROOT/bin"
mkdir -p "$TMP_DIR"
BPF_TMP_ROOT="$(mktemp -d "$TMP_DIR/netbpfload-compat.XXXXXX")"

if [ ! -f "$BPF_APEX" ]; then
    ABORT "Tethering compressed APEX is missing: $BPF_APEX"
fi
if ! command -v debugfs > /dev/null; then
    ABORT "debugfs is required to extract the Tethering APEX payload"
fi

mkdir -p "$BPF_COMPAT_BIN/for-system"
EVAL "unzip -j \"$BPF_APEX\" original_apex -d \"$BPF_TMP_ROOT\""
EVAL "unzip -j \"$BPF_TMP_ROOT/original_apex\" apex_payload.img -d \"$BPF_TMP_ROOT\""

while read -r BPF_INPUT_SHA256 BPF_INPUT_PATH BPF_INPUT_UID \
        BPF_INPUT_GID BPF_INPUT_MODE BPF_INPUT_LABEL; do
    [ -n "$BPF_INPUT_PATH" ] || continue
    BPF_OUTPUT="$BPF_COMPAT_BIN/$BPF_INPUT_PATH"
    EVAL "debugfs -R \"dump -p /bin/$BPF_INPUT_PATH $BPF_OUTPUT\" \"$BPF_TMP_ROOT/apex_payload.img\""
    if [ "$(sha256sum "$BPF_OUTPUT" | cut -d " " -f 1)" != \
            "$BPF_INPUT_SHA256" ]; then
        ABORT "Tethering APEX input hash changed: /bin/$BPF_INPUT_PATH"
    fi
    SET_METADATA "system" "system/etc/netbpfload_compat/bin/$BPF_INPUT_PATH" \
        "$BPF_INPUT_UID" "$BPF_INPUT_GID" "$BPF_INPUT_MODE" \
        "$BPF_INPUT_LABEL"
done <<'EOF'
ca878a914a6f436a5af846d2353dbe44bccf592c527d5b03ac5e6db8e8857b9e ethtool 0 2000 755 u:object_r:system_file:s0
a8cb1311b422a1bc9b0065d73e6e615b61207d331fd42950e8e4da210c46c528 for-system/clatd 1029 1029 6755 u:object_r:clatd_exec:s0
7b77a7ac01d01b6787544f2a01a77f4fd929ec6da0625c6f413764e8622ff2a2 netbpfload 0 0 750 u:object_r:bpfloader_exec:s0
954fd201f94dc49e2d40d9ef90b6d032b177ddf6c85083a5953ebcb915cc0b70 ot-daemon 0 2000 755 u:object_r:ot_daemon_exec:s0
EOF

SET_METADATA "system" "system/etc/netbpfload_compat" \
    0 2000 755 "u:object_r:system_file:s0"
SET_METADATA "system" "system/etc/netbpfload_compat/bin" \
    0 2000 755 "u:object_r:system_file:s0"
SET_METADATA "system" "system/etc/netbpfload_compat/bin/for-system" \
    1029 1000 750 "u:object_r:system_file:s0"

BPF_LOADER="$BPF_COMPAT_BIN/netbpfload"
BPF_FROM="280200546808009008614439c8010036"
BPF_TO="2802005468080090086144390e000014"
BPF_MATCH_COUNT="$(xxd -p "$BPF_LOADER" | tr -d ' \n' | grep -o "$BPF_FROM" | wc -l)"
if [ "$BPF_MATCH_COUNT" != "1" ]; then
    ABORT "Expected one Android 25Q4 NetBpfLoad kernel gate, found $BPF_MATCH_COUNT"
fi
HEX_PATCH "$BPF_LOADER" "$BPF_FROM" "$BPF_TO" || \
    ABORT "Failed to patch the Android 25Q4 NetBpfLoad kernel gate"
if [ "$(sha256sum "$BPF_LOADER" | cut -d " " -f 1)" != \
        "a3507cc9cdf11c7eb4301d71a596a1fb64bc774aefc7185f6a237b8a4435a448" ]; then
    ABORT "Patched NetBpfLoad hash mismatch"
fi

BPF_INIT_RC="$WORK_DIR/system/system/etc/init/hw/init.rc"
BPF_TRIGGER_COUNT="$(grep -c '^[[:space:]]*exec_start bpfloader[[:space:]]*$' "$BPF_INIT_RC")"
if [ "$BPF_TRIGGER_COUNT" != "1" ]; then
    ABORT "Expected one load-bpf-programs bpfloader start, found $BPF_TRIGGER_COUNT"
fi
sed -i '/^[[:space:]]*exec_start bpfloader[[:space:]]*$/i\
    # d2s: retain the APEX path/namespace while bypassing only its 5.10 hard gate.\
    mount none /system/etc/netbpfload_compat/bin /apex/com.android.tethering/bin bind' \
    "$BPF_INIT_RC"

rm -f "$BPF_TMP_ROOT/original_apex" "$BPF_TMP_ROOT/apex_payload.img"
rmdir "$BPF_TMP_ROOT"
LOG_STEP_OUT

LOG "- Updating legacy d2s ueventd sysfs rules"
sed -i \
    -e 's|^/sys/kernel/clat/xlat_v4_addrs[[:space:]].*|/sys/kernel/clat xlat_v4_addrs 0660 clat clat|' \
    -e 's|^/sys/kernel/clat/xlat_addrs[[:space:]].*|/sys/kernel/clat xlat_addrs 0660 clat clat|' \
    -e 's|^/sys/kernel/clat/xlat_plat[[:space:]].*|/sys/kernel/clat xlat_plat 0660 clat clat|' \
    -e '/^\/sys\/bus\/iio\/devices\/iio:device\*[[:space:]][[:space:]]*0664[[:space:]][[:space:]]*system[[:space:]][[:space:]]*radio[[:space:]]*$/d' \
    "$WORK_DIR/vendor/ueventd.rc"

unset TARGET_COMPAT_SOURCE TARGET_FCM_LEVEL TARGET_FCM_MATRIX
unset TARGET_FCM_MATRIX_LEVEL TARGET_HEALTH_FILE
unset KNOX_MATRIX_FILE FKEYMASTER_MATRIX FKEYMASTER_MATRIX_COUNT
unset KNOX_GUARD_FILE KNOX_GUARD_MATRIX_COUNT
unset KNOX_GUARD_CONFIG KNOX_GUARD_CONFIGS KNOX_GUARD_CONFIG_PATH
unset KNOX_GUARD_CONFIG_COUNT
unset ACONFIG_INIT_RC ACONFIG_EARLY_INIT_COUNT
unset AUDIO_BRIDGE_SOURCE AUDIO_BRIDGE_MARKER AUDIO_BRIDGE_SHA256
unset AUDIO_BRIDGE_FILE AUDIO_BRIDGE_INPUT AUDIO_MANIFEST
unset BPF_APEX BPF_COMPAT_ROOT BPF_COMPAT_BIN BPF_TMP_ROOT
unset BPF_INPUT_SHA256 BPF_INPUT_PATH BPF_INPUT_UID BPF_INPUT_GID
unset BPF_INPUT_MODE BPF_INPUT_LABEL BPF_OUTPUT
unset BPF_LOADER BPF_FROM BPF_TO BPF_MATCH_COUNT
unset BPF_INIT_RC BPF_TRIGGER_COUNT
