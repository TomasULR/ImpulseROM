# [
EXTREMEKRNL_REPO="https://github.com/Ocin4ever/ExtremeKernel/releases"
# The latest alpha4 device log proves this ramdisk reaches Android 16
# second-stage init, loads SELinux, and starts core services. Keep v2.0 pinned
# because it is the newest verified d2s release; do not change the kernel to
# chase a userspace service failure without new kernel evidence.
EXTREMEKRNL_VERSION="v2.0"
KERNELSU_MANAGER_APK="https://github.com/KernelSU-Next/KernelSU-Next/releases/download/v1.0.9/KernelSU_Next_v1.0.9_12797-release.apk"
KERNELSU_MANAGER_SHA256="0013c41c9aeda2699f8a8af840839eb495f89bce7264b5c8fa42152b4c8d9a1e"

REPLACE_KERNEL_BINARIES()
{
    [ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR"
    mkdir -p "$TMP_DIR"

    if ! $DEBUG; then
        ZIP_LINK="$EXTREMEKRNL_REPO/download/$EXTREMEKRNL_VERSION/ExtremeKRNL-Nexus-${TARGET_CODENAME}.zip"
        case "$TARGET_CODENAME" in
            d1)
                ZIP_SHA256="a022b5d6a762ec43c1633c0991c0aaa9affc50cbf5616b6f90f321a0ec222ab4"
                ;;
            d2s)
                ZIP_SHA256="91309ca7b6bce0edd99734b798ef23faf1e0eb2bd34d3055917e39309894eaba"
                ;;
            *)
                LOGE "No pinned ExtremeKRNL checksum for $TARGET_CODENAME"
                exit 1
                ;;
        esac
    else
        ZIP_LINK="$EXTREMEKRNL_REPO/download/debug/ExtremeKRNL-Nexus-${TARGET_CODENAME}.zip"
    fi
    LOG "Downloading $(basename "$ZIP_LINK")"
    curl --fail --location --silent --show-error --retry 5 \
        --output "$TMP_DIR/krnl.zip" "$ZIP_LINK" || exit 1
    if ! $DEBUG; then
        printf '%s  %s\n' "$ZIP_SHA256" "$TMP_DIR/krnl.zip" | \
            sha256sum --check --strict - || exit 1
    fi

    LOG "Extracting kernel binaries"
    echo $WORK_DIR
    rm -f "$WORK_DIR/kernel/"*.img
    unzip -q -j "$TMP_DIR/krnl.zip" \
        "files/boot.img" "files/dtbo.img" "files/dtb.img" \
        -d "$WORK_DIR/kernel"

    rm -rf "$TMP_DIR"
}

ADD_MANAGER_APK_TO_PRELOAD()
{
    # https://github.com/tiann/KernelSU/issues/886
    local APK_PATH="system/preload/KernelSU-Next/com.rifsxd.ksunext-mesa==/base.apk"

    LOG "Adding KernelSU-Next.apk to preload apps"
    mkdir -p "$WORK_DIR/system/$(dirname "$APK_PATH")"
    curl --fail --location --silent --show-error --retry 5 \
        --output "$WORK_DIR/system/$APK_PATH" "$KERNELSU_MANAGER_APK" || exit 1
    printf '%s  %s\n' "$KERNELSU_MANAGER_SHA256" "$WORK_DIR/system/$APK_PATH" | \
        sha256sum --check --strict - || exit 1

    sed -i "/system\/preload/d" "$WORK_DIR/configs/fs_config-system" \
        && sed -i "/system\/preload/d" "$WORK_DIR/configs/file_context-system"
    while read -r i; do
        FILE="$(echo -n "$i"| sed "s.$WORK_DIR/system/..")"
        [ -d "$i" ] && echo "$FILE 0 0 755 capabilities=0x0" >> "$WORK_DIR/configs/fs_config-system"
        [ -f "$i" ] && echo "$FILE 0 0 644 capabilities=0x0" >> "$WORK_DIR/configs/fs_config-system"
        FILE="$(echo -n "$FILE" | sed 's/\./\\./g')"
        echo "/$FILE u:object_r:system_file:s0" >> "$WORK_DIR/configs/file_context-system"
    done <<< "$(find "$WORK_DIR/system/system/preload")"

    rm -f "$WORK_DIR/system/system/etc/vpl_apks_count_list.txt"
    while read -r i; do
        FILE="$(echo "$i" | sed "s.$WORK_DIR/system..")"
        echo "$FILE" >> "$WORK_DIR/system/system/etc/vpl_apks_count_list.txt"
    done <<< "$(find "$WORK_DIR/system/system/preload" -name "*.apk" | sort)"
}
# ]

REPLACE_KERNEL_BINARIES
if [[ "${INCLUDE_KERNELSU_MANAGER:-false}" == "true" ]]; then
    ADD_MANAGER_APK_TO_PRELOAD
else
    LOG "KernelSU Manager preload disabled for boot-minimal build"
fi
