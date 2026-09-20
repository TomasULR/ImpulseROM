#!/usr/bin/env bash
#
# Copyright (C) 2025 Salvo Giangreco
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

set -e

# [
source "$SRC_DIR/scripts/utils/build_utils.sh" || exit 1

FORCE=false
BUILD_ROM=false
BUILD_ZIP=true
GITHUB_ACTIONS=${GITHUB_ACTIONS:-}

# Records framework patches that APPLY_PATCH kept at stock because they drifted
# against the current source (only when PATCH_DRIFT_POLICY=skip). This file is
# the rebase backlog for restoring those features after a stable boot.
export PATCH_DRIFT_REPORT="$OUT_DIR/skipped_patches.tsv"

START_TIME="$(date +%s)"

SOURCE_FIRMWARE_PATH="$(cut -d "/" -f 1 -s <<< "$SOURCE_FIRMWARE")_$(cut -d "/" -f 2 -s <<< "$SOURCE_FIRMWARE")"
TARGET_FIRMWARE_PATH="$(cut -d "/" -f 1 -s <<< "$TARGET_FIRMWARE")_$(cut -d "/" -f 2 -s <<< "$TARGET_FIRMWARE")"

# Module customizers run in scripts/internal/apply_modules.sh, which is a
# separate process. Keep the resolved firmware directory names available to
# device modules that must restore exact files from either extracted tree.
export SOURCE_FIRMWARE_PATH TARGET_FIRMWARE_PATH
export ENABLE_SCOPED_PLATFORM_APK_REBUILDS="${ENABLE_SCOPED_PLATFORM_APK_REBUILDS:-false}"

GET_REQUIRED_FIRMWARES()
{
    local EXTRA_FIRMWARES=()

    printf '%s\n' "$SOURCE_FIRMWARE"
    if [ -n "$SOURCE_EXTRA_FIRMWARES" ]; then
        IFS=':' read -r -a EXTRA_FIRMWARES <<< "$SOURCE_EXTRA_FIRMWARES"
        printf '%s\n' "${EXTRA_FIRMWARES[@]}"
    fi

    printf '%s\n' "$TARGET_FIRMWARE"
    EXTRA_FIRMWARES=()
    if [ -n "$TARGET_EXTRA_FIRMWARES" ]; then
        IFS=':' read -r -a EXTRA_FIRMWARES <<< "$TARGET_EXTRA_FIRMWARES"
        printf '%s\n' "${EXTRA_FIRMWARES[@]}"
    fi
}

GET_FIRMWARE_DIR_NAME()
{
    local FIRMWARE="$1"
    printf '%s_%s\n' \
        "$(cut -d "/" -f 1 -s <<< "$FIRMWARE")" \
        "$(cut -d "/" -f 2 -s <<< "$FIRMWARE")"
}

ALL_REQUIRED_FIRMWARE_MARKERS_EXIST()
{
    local BASE_DIR="$1"
    local MARKER_NAME="$2"
    local FIRMWARE
    local FIRMWARE_DIR

    while IFS= read -r FIRMWARE; do
        [ -n "$FIRMWARE" ] || continue
        FIRMWARE_DIR="$(GET_FIRMWARE_DIR_NAME "$FIRMWARE")"
        [ -f "$BASE_DIR/$FIRMWARE_DIR/$MARKER_NAME" ] || return 1
    done < <(GET_REQUIRED_FIRMWARES)

    return 0
}

VALIDATE_MULTILIB_FIRMWARE_INPUTS()
{
    [ -n "${MULTILIB_FIRMWARE:-}" ] || return 0

    local MULTILIB_FIRMWARE_PATH
    MULTILIB_FIRMWARE_PATH="$(GET_FIRMWARE_DIR_NAME "$MULTILIB_FIRMWARE")"

    python3 "$SRC_DIR/scripts/internal/validate_multilib_firmware.py" \
        "$FW_DIR/$MULTILIB_FIRMWARE_PATH" \
        "$FW_DIR/$SOURCE_FIRMWARE_PATH" \
        --json-output "$OUT_DIR/multilib_firmware_validation.json"
}

GET_WORK_DIR_HASH()
{
    local HASH_PATHS=(
        "$SRC_DIR/unica"
        "$SRC_DIR/platform/$TARGET_PLATFORM"
        "$SRC_DIR/prebuilts/samsung"
        "$SRC_DIR/scripts"
        "$SRC_DIR/target/$TARGET_CODENAME"
    )
    local FIRMWARE
    local HASH_FILE
    while IFS= read -r FIRMWARE; do
        [ -n "$FIRMWARE" ] || continue
        HASH_FILE="$FW_DIR/$(GET_FIRMWARE_DIR_NAME "$FIRMWARE")/.extracted"
        [ -f "$HASH_FILE" ] && HASH_PATHS+=("$HASH_FILE")
    done < <(GET_REQUIRED_FIRMWARES)

    {
        # Content and path of every regular build input. Python bytecode is a
        # host-side cache and must never make ROM cache keys machine-specific.
        find "${HASH_PATHS[@]}" \
            \( -type d -name __pycache__ -prune \) -o \
            \( -type f ! -name "*.pyc" ! -name "*.pyo" -print0 \) | \
            sort -z | xargs -0 -r sha1sum

        # sha1sum follows symlinks and ignores dangling ones, so hash their
        # declared targets explicitly as part of the filesystem contract.
        while IFS= read -r -d '' HASH_FILE; do
            printf 'symlink %s -> %s\n' \
                "$HASH_FILE" "$(readlink "$HASH_FILE")"
        done < <(
            find "${HASH_PATHS[@]}" \
                \( -type d -name __pycache__ -prune \) -o \
                \( -type l -print0 \) | sort -z
        )

        # A commit can change build identity without changing file contents.
        printf 'git-head %s\n' "$(git rev-parse HEAD)"
        printf 'rom-commit %s\n' "$ROM_COMMIT"
    } | sha1sum | cut -d " " -f 1
}

PREPARE_SCRIPT()
{
    while [ "$#" != 0 ]; do
        case "$1" in
            "-f" | "--force")
                FORCE=true
                ;;
            "--no-rom-zip")
                BUILD_ZIP=false
                ;;
            *)
                echo "Usage: make_rom [options]"
                echo " -f, --force : Force build"
                echo " --no-rom-zip : Do not build ROM zip"
                exit 1
                ;;
        esac

        shift
    done
}

PRINT_BUILD_OUTCOME()
{
    local EXIT_CODE="$?"
    local END_TIME
    local ESTIMATED

    END_TIME="$(date +%s)"
    ESTIMATED="$((END_TIME - START_TIME))"

    if [ "$EXIT_CODE" != "0" ]; then
        echo -n -e '\n\033[1;31m'"Build failed "
    else
        echo -n -e '\n\033[1;32m'"Build completed "
    fi
    echo -e "in $((ESTIMATED / 3600))hrs $(((ESTIMATED / 60) % 60))min $((ESTIMATED % 60))sec."'\033[0m\n'
}

PRINT_USAGE()
{
    echo "Usage: make_rom [options]" >&2
    echo " -f, --force : Force ROM build" >&2
    echo " --no-rom-zip : Do not build ROM zip" >&2
}
# ]

PREPARE_SCRIPT "$@"

if $FORCE; then
    BUILD_ROM=true
else
    if [ -f "$WORK_DIR/.completed" ]; then
        if [[ "$(cat "$WORK_DIR/.completed")" == "$(GET_WORK_DIR_HASH)" ]]; then
            LOGW "No changes have been detected in the build environment"
            BUILD_ROM=false
        else
            LOGW "Changes detected in the build environment"
            BUILD_ROM=true
        fi
    else
        BUILD_ROM=true
    fi
fi

trap 'PRINT_BUILD_OUTCOME' EXIT
trap 'echo' INT

if $BUILD_ROM; then
    [ -d "$APKTOOL_DIR" ] && rm -rf "$APKTOOL_DIR"
    [ -f "$WORK_DIR/.completed" ] && rm -f "$WORK_DIR/.completed"
    : > "$PATCH_DRIFT_REPORT"

    if ! ALL_REQUIRED_FIRMWARE_MARKERS_EXIST "$FW_DIR" ".extracted"; then
        if ! ALL_REQUIRED_FIRMWARE_MARKERS_EXIST "$ODIN_DIR" ".downloaded"; then
            LOG_STEP_IN true "Downloading required firmwares"
            "$SRC_DIR/scripts/download_fw.sh" || exit 1
            LOG_STEP_OUT
        fi
        LOG_STEP_IN true "Extracting required firmwares"
        "$SRC_DIR/scripts/extract_fw.sh" || exit 1
        LOG_STEP_OUT
    fi

    if [[ "${SOURCE_METADATA_AUTODETECT:-false}" == "true" ]]; then
        LOG_STEP_IN true "Refreshing source firmware metadata"
        bash "$SRC_DIR/scripts/internal/update_source_metadata.sh" || exit 1
        set -o allexport; source "$OUT_DIR/config.sh"; set +o allexport
        LOG_STEP_OUT
    fi

    if [ -n "${MULTILIB_FIRMWARE:-}" ]; then
        LOG_STEP_IN true "Validating API 36 multilib firmware inputs"
        VALIDATE_MULTILIB_FIRMWARE_INPUTS || exit 1
        LOG_STEP_OUT
    fi

    LOG_STEP_IN true "Creating work dir"
    "$SRC_DIR/scripts/internal/create_work_dir.sh" || exit 1
    LOG_STEP_OUT

    if [ -d "$SRC_DIR/unica/patches" ]; then
        LOG_STEP_IN true "Applying ROM patches"
        "$SRC_DIR/scripts/internal/apply_modules.sh" "$SRC_DIR/unica/patches" || exit 1
        LOG_STEP_OUT
    fi

    if [ -d "$SRC_DIR/platform/$TARGET_PLATFORM/patches" ]; then
        LOG_STEP_IN true "Applying platform patches"
        "$SRC_DIR/scripts/internal/apply_modules.sh" "$SRC_DIR/platform/$TARGET_PLATFORM/patches" || exit 1
        LOG_STEP_OUT
    fi
    if [ -d "$SRC_DIR/target/$TARGET_CODENAME/patches" ]; then
        LOG_STEP_IN true "Applying device patches"
        "$SRC_DIR/scripts/internal/apply_modules.sh" "$SRC_DIR/target/$TARGET_CODENAME/patches" || exit 1
        LOG_STEP_OUT
    fi

    if [ -d "$SRC_DIR/unica/mods" ]; then
        LOG_STEP_IN true "Applying ROM mods"
        "$SRC_DIR/scripts/internal/apply_modules.sh" "$SRC_DIR/unica/mods" || exit 1
        LOG_STEP_OUT
    fi

    if [ -d "$APKTOOL_DIR" ]; then
        LOG_STEP_IN true "Building APKs/JARs"

        APKTOOL_PARALLEL_JOBS="${APKTOOL_PARALLEL_JOBS:-2}"
        if ! [[ "$APKTOOL_PARALLEL_JOBS" =~ ^[0-9]+$ ]] || [ "$APKTOOL_PARALLEL_JOBS" -lt 1 ]; then
            LOGE "Invalid APKTOOL_PARALLEL_JOBS: $APKTOOL_PARALLEL_JOBS"
            exit 1
        fi

        APKTOOL_RUNNING_JOBS=0
        while IFS= read -r f; do
            f="${f/$APKTOOL_DIR\//}"
            PARTITION="$(cut -d "/" -f 1 -s <<< "$f")"
            if [[ "$PARTITION" == "system" ]]; then
                "$SRC_DIR/scripts/apktool.sh" b "system" "$f" &
            else
                "$SRC_DIR/scripts/apktool.sh" b "$PARTITION" "$(cut -d "/" -f 2- -s <<< "$f")" &
            fi

            APKTOOL_RUNNING_JOBS=$((APKTOOL_RUNNING_JOBS + 1))
            if [ "$APKTOOL_RUNNING_JOBS" -ge "$APKTOOL_PARALLEL_JOBS" ]; then
                wait -n || exit 1
                APKTOOL_RUNNING_JOBS=$((APKTOOL_RUNNING_JOBS - 1))
            fi
        done < <(find "$APKTOOL_DIR" -type d \( -name "*.apk" -o -name "*.jar" \))

        APKTOOL_WAIT_STATUS=0
        for pid in $(jobs -p); do
            wait "$pid" || APKTOOL_WAIT_STATUS=1
        done
        [ "$APKTOOL_WAIT_STATUS" -eq 0 ] || exit 1

        LOG_STEP_OUT
    fi

fi

if [ -s "$PATCH_DRIFT_REPORT" ]; then
    LOGW "$(wc -l < "$PATCH_DRIFT_REPORT") framework patch(es) were kept at stock because they drifted against the source:"
    while IFS=$'\t' read -r SKIP_PARTITION SKIP_FILE SKIP_PATCH; do
        LOGW "  /$SKIP_PARTITION/$SKIP_FILE  <-  $SKIP_PATCH"
    done < "$PATCH_DRIFT_REPORT"
    LOGW "These are the feature-restore backlog; see $PATCH_DRIFT_REPORT"
fi

CRITICAL_KNOX_GUARD_PATCH="target/d2s/patches/android16_compat/smali/system/framework/services.jar/0001-Disable-unsupported-KnoxGuard-service.patch"
if [ -s "$PATCH_DRIFT_REPORT" ] && \
        grep -Fq "$CRITICAL_KNOX_GUARD_PATCH" "$PATCH_DRIFT_REPORT"; then
    LOGE "Critical d2s KnoxGuard compatibility patch drifted; refusing to package"
    exit 1
fi

if [[ "$ENABLE_SCOPED_PLATFORM_APK_REBUILDS" == "true" && -s "$PATCH_DRIFT_REPORT" ]]; then
    CRITICAL_SCOPED_PATCHES=(
        "unica/patches/signature/0001-Allow-custom-platform-signature.patch"
        "unica/patches/product_feature/fingerprint/BiometricSetting.apk/0001-Set-FP_FEATURE_SENSOR_IS_OPTICAL-to-false.patch"
        "unica/patches/product_feature/fingerprint/SystemUI.apk/0001-Set-SECURITY_FINGERPRINT_IN_DISPLAY_OPTICAL-to-false.patch"
        "unica/patches/product_feature/mdnie/hw/EnvironmentAdaptiveDisplay.apk/0001-Fix-framework-resource-IDs-for-API-36.patch"
        "target/d2s/patches/android16_compat/smali/system/framework/services.jar/0002-Allow-Secure-Folder-on-unlocked-d2s.patch"
    )
    for CRITICAL_SCOPED_PATCH in "${CRITICAL_SCOPED_PATCHES[@]}"; do
        if grep -Fq "$CRITICAL_SCOPED_PATCH" "$PATCH_DRIFT_REPORT"; then
            LOGE "Critical d2s scoped-platform patch drifted; refusing to package: $CRITICAL_SCOPED_PATCH"
            exit 1
        fi
    done
fi

LOG_STEP_IN true "Validating assembled work dir"
WORK_VALIDATOR_ARGS=("$WORK_DIR")
if [ -n "${MULTILIB_FIRMWARE:-}" ]; then
    WORK_VALIDATOR_ARGS+=(
        --multilib-firmware-dir
        "$FW_DIR/$(GET_FIRMWARE_DIR_NAME "$MULTILIB_FIRMWARE")"
    )
fi
if [[ "$TARGET_SINGLE_SYSTEM_IMAGE" == "essi85" ]]; then
    WORK_VALIDATOR_ARGS+=(
        --source-firmware-dir
        "$FW_DIR/$SOURCE_FIRMWARE_PATH"
        --require-source-matched-core
    )
    if [[ "$ENABLE_SCOPED_PLATFORM_APK_REBUILDS" != "true" ]]; then
        WORK_VALIDATOR_ARGS+=(--require-source-matched-first-boot-apks)
    else
        ROM_PLATFORM_CERT="$SRC_DIR/security/aosp_platform.x509.pem"
        $ROM_IS_OFFICIAL && \
            ROM_PLATFORM_CERT="$SRC_DIR/security/impulse_platform.x509.pem"
        WORK_VALIDATOR_ARGS+=(
            --require-d2s-scoped-platform-apks
            --rom-platform-cert
            "$ROM_PLATFORM_CERT"
        )
    fi
fi
if [[ "$TARGET_CODENAME" == "d2s" && "$TARGET_SINGLE_SYSTEM_IMAGE" == "essi85" ]]; then
    WORK_VALIDATOR_ARGS+=(
        --target-firmware-dir
        "$FW_DIR/$TARGET_FIRMWARE_PATH"
        --require-d2s-android16-contracts
    )
fi
python3 "$SRC_DIR/scripts/internal/validate_work_dir.py" \
    "${WORK_VALIDATOR_ARGS[@]}" || exit 1
if [[ "$TARGET_CODENAME" == "d2s" && "$TARGET_SINGLE_SYSTEM_IMAGE" == "essi85" ]]; then
    python3 "$SRC_DIR/scripts/internal/validate_vintf_compat.py" \
        "$WORK_DIR" || exit 1

    python3 "$SRC_DIR/scripts/internal/validate_audio_contract.py" \
        "$WORK_DIR" \
        --source-firmware-dir "$FW_DIR/$SOURCE_FIRMWARE_PATH" \
        --multilib-firmware-dir \
        "$FW_DIR/$(GET_FIRMWARE_DIR_NAME "$MULTILIB_FIRMWARE")" \
        --target-firmware-dir "$FW_DIR/$TARGET_FIRMWARE_PATH" \
        --json-output "$OUT_DIR/audio_contract_validation.json" || exit 1

    ELF32_VALIDATOR_ARGS=(
        "$WORK_DIR"
        --multilib-firmware-dir
        "$FW_DIR/$(GET_FIRMWARE_DIR_NAME "$MULTILIB_FIRMWARE")"
    )
    while IFS= read -r ELF32_DLOPEN_ROOT; do
        ELF32_VALIDATOR_ARGS+=(
            --vendor-dlopen-root
            "${ELF32_DLOPEN_ROOT#"$WORK_DIR"/}"
        )
    done < <(
        {
            printf '%s\n' \
                "$WORK_DIR/vendor/lib/hw/android.hardware.audio@6.0-impl.so" \
                "$WORK_DIR/vendor/lib/hw/android.hardware.audio.effect@6.0-impl.so" \
                "$WORK_DIR/vendor/lib/hw/vendor.samsung.hardware.audio@1.0-impl.so"
            find "$WORK_DIR/vendor/lib/hw" -maxdepth 1 -type f \
                -name 'audio.*.so' -print
            find "$WORK_DIR/vendor/lib/soundfx" -maxdepth 1 -type f \
                -name '*.so' -print
        } | sort -u
    )
    python3 "$SRC_DIR/scripts/internal/validate_elf32_closure.py" \
        "${ELF32_VALIDATOR_ARGS[@]}" \
        --json "$OUT_DIR/elf32_closure_validation.json" || exit 1
    unset ELF32_VALIDATOR_ARGS ELF32_DLOPEN_ROOT

    ELF64_VALIDATOR_ARGS=(
        "$WORK_DIR"
        --bitness 64
        --multilib-firmware-dir
        "$FW_DIR/$(GET_FIRMWARE_DIR_NAME "$MULTILIB_FIRMWARE")"
    )
    for ELF64_DLOPEN_DIR in hw egl mediacas mediadrm omx soundfx; do
        while IFS= read -r ELF64_DLOPEN_ROOT; do
            ELF64_VALIDATOR_ARGS+=(
                --vendor-dlopen-root
                "${ELF64_DLOPEN_ROOT#"$WORK_DIR"/}"
            )
        done < <(
            find "$WORK_DIR/vendor/lib64/$ELF64_DLOPEN_DIR" -type f \
                -name '*.so' -print 2> /dev/null | sort
        )
    done
    python3 "$SRC_DIR/scripts/internal/validate_elf32_closure.py" \
        "${ELF64_VALIDATOR_ARGS[@]}" \
        --json "$OUT_DIR/elf64_closure_validation.json" || exit 1
    unset ELF64_VALIDATOR_ARGS ELF64_DLOPEN_DIR ELF64_DLOPEN_ROOT
fi
unset WORK_VALIDATOR_ARGS
LOG_STEP_OUT

if $BUILD_ROM; then
    echo -n "$(GET_WORK_DIR_HASH)" > "$WORK_DIR/.completed"
fi

if [ -n "$GITHUB_ACTIONS" ]; then
    bash "$SRC_DIR/scripts/cleanup.sh" fw
fi

if $BUILD_ZIP; then
    LOG_STEP_IN true "Creating zip"
    "$SRC_DIR/scripts/internal/build_flashable_zip.sh" || exit 1
    LOG_STEP_OUT
fi

exit 0
