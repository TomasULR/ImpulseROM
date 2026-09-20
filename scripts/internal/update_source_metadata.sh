#!/usr/bin/env bash
#
# Copyright (C) 2026 EternityROM contributors
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

source "$SRC_DIR/scripts/utils/common_utils.sh" || exit 1

CONFIG_FILE="$OUT_DIR/config.sh"

if [[ "${SOURCE_METADATA_AUTODETECT:-false}" != "true" ]]; then
    exit 0
fi

if [ ! -f "$CONFIG_FILE" ]; then
    LOGE "File not found: ${CONFIG_FILE//$SRC_DIR\//}"
    exit 1
fi

SOURCE_MODEL="$(cut -d "/" -f 1 -s <<< "$SOURCE_FIRMWARE")"
SOURCE_CSC="$(cut -d "/" -f 2 -s <<< "$SOURCE_FIRMWARE")"
SOURCE_FIRMWARE_PATH="${SOURCE_MODEL}_${SOURCE_CSC}"
SOURCE_DIR="$FW_DIR/$SOURCE_FIRMWARE_PATH"
AUDIT_FILE="$OUT_DIR/source_metadata_${TARGET_SINGLE_SYSTEM_IMAGE}.txt"

if [ ! -d "$SOURCE_DIR" ]; then
    LOGW "Source firmware is not extracted yet: ${SOURCE_DIR//$SRC_DIR\//}"
    exit 0
fi

SYSTEM_PROP_FILES=(
    "$SOURCE_DIR/system/system/build.prop"
    "$SOURCE_DIR/system/build.prop"
)
VENDOR_PROP_FILES=(
    "$SOURCE_DIR/vendor/build.prop"
    "$SOURCE_DIR/vendor/default.prop"
)
PRODUCT_PROP_FILES=(
    "$SOURCE_DIR/product/etc/build.prop"
)
SYSTEM_EXT_PROP_FILES=(
    "$SOURCE_DIR/system_ext/etc/build.prop"
    "$SOURCE_DIR/system/system/system_ext/etc/build.prop"
)
FLOATING_FEATURE_FILES=(
    "$SOURCE_DIR/system/system/etc/floating_feature.xml"
    "$SOURCE_DIR/system/etc/floating_feature.xml"
    "$SOURCE_DIR/system_ext/etc/floating_feature.xml"
    "$SOURCE_DIR/system/system/system_ext/etc/floating_feature.xml"
    "$SOURCE_DIR/product/etc/floating_feature.xml"
)

GET_EXTRACTED_PROP()
{
    local PROP="$1"
    shift

    local FILE
    local VALUE
    for FILE in "$@"; do
        [ -f "$FILE" ] || continue
        VALUE="$(sed -n "s/^${PROP}=//p" "$FILE" | head -n 1)"
        if [ "$VALUE" ]; then
            echo "$VALUE"
            return 0
        fi
    done

    return 1
}

GET_FLOATING_FEATURE()
{
    local KEY="$1"

    local FILE
    local VALUE
    for FILE in "${FLOATING_FEATURE_FILES[@]}"; do
        [ -f "$FILE" ] || continue
        VALUE="$(
            sed -n \
                -e "s|.*<${KEY}>\\(.*\\)</${KEY}>.*|\\1|p" \
                -e "s|^${KEY}=||p" \
                "$FILE" | head -n 1
        )"
        if [ "$VALUE" ]; then
            echo "$VALUE"
            return 0
        fi
    done

    return 1
}

SET_CONFIG_VALUE()
{
    local KEY="$1"
    local VALUE="$2"
    local ESCAPED_VALUE

    [ "$VALUE" ] || return 0

    ESCAPED_VALUE="$(printf '%s' "$VALUE" | sed -e 's/[\/&]/\\&/g')"
    if grep -q "^${KEY}=" "$CONFIG_FILE"; then
        sed -i "s/^${KEY}=.*/${KEY}=\"${ESCAPED_VALUE}\"/" "$CONFIG_FILE"
    else
        echo "${KEY}=\"${VALUE}\"" >> "$CONFIG_FILE"
    fi
}

SET_CONFIG_FROM_PROP()
{
    local KEY="$1"
    local PROP="$2"
    shift 2

    local VALUE
    VALUE="$(GET_EXTRACTED_PROP "$PROP" "$@" || true)"
    SET_CONFIG_VALUE "$KEY" "$VALUE"
}

SET_CONFIG_FROM_FEATURE()
{
    local KEY="$1"
    shift

    local FEATURE
    local VALUE
    for FEATURE in "$@"; do
        VALUE="$(GET_FLOATING_FEATURE "$FEATURE" || true)"
        if [ "$VALUE" ]; then
            SET_CONFIG_VALUE "$KEY" "$VALUE"
            return 0
        fi
    done
}

SET_CONFIG_FROM_PATH_EXISTS()
{
    local KEY="$1"
    shift

    local RELATIVE_PATH
    for RELATIVE_PATH in "$@"; do
        if [ -e "$SOURCE_DIR/$RELATIVE_PATH" ]; then
            SET_CONFIG_VALUE "$KEY" "true"
            return 0
        fi
    done

    SET_CONFIG_VALUE "$KEY" "false"
}

SET_CONFIG_FROM_PROP "SOURCE_API_LEVEL" "ro.build.version.sdk" \
    "${SYSTEM_PROP_FILES[@]}" "${PRODUCT_PROP_FILES[@]}"
SET_CONFIG_FROM_PROP "SOURCE_PRODUCT_FIRST_API_LEVEL" "ro.product.first_api_level" \
    "${VENDOR_PROP_FILES[@]}" "${SYSTEM_PROP_FILES[@]}" "${PRODUCT_PROP_FILES[@]}"
SET_CONFIG_FROM_PROP "SOURCE_VNDK_VERSION" "ro.vndk.version" \
    "${VENDOR_PROP_FILES[@]}" "${SYSTEM_EXT_PROP_FILES[@]}" "${SYSTEM_PROP_FILES[@]}"

SOURCE_DEVICE="$(GET_EXTRACTED_PROP "ro.product.vendor.device" "${VENDOR_PROP_FILES[@]}" || true)"
[ "$SOURCE_DEVICE" ] || SOURCE_DEVICE="$(GET_EXTRACTED_PROP "ro.product.system.device" "${SYSTEM_PROP_FILES[@]}" || true)"
[ "$SOURCE_DEVICE" ] || SOURCE_DEVICE="$(GET_EXTRACTED_PROP "ro.build.product" "${SYSTEM_PROP_FILES[@]}" || true)"
SET_CONFIG_VALUE "SOURCE_CODENAME" "$SOURCE_DEVICE"

# This flag describes a standalone system_ext partition. A nested
# /system/system_ext directory is still part of the system image.
if [ -d "$SOURCE_DIR/system_ext" ]; then
    SET_CONFIG_VALUE "SOURCE_HAS_SYSTEM_EXT" "true"
else
    SET_CONFIG_VALUE "SOURCE_HAS_SYSTEM_EXT" "false"
fi

if [ -f "$SOURCE_DIR/os_partitions_metadata.txt" ]; then
    SET_CONFIG_VALUE "SOURCE_SUPER_GROUP_NAME" \
        "$(sed -n 's/^super_partition_group=//p' "$SOURCE_DIR/os_partitions_metadata.txt" | head -n 1)"
fi

SET_CONFIG_FROM_FEATURE "SOURCE_AUTO_BRIGHTNESS_TYPE" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_CONTROL_AUTO_BRIGHTNESS"
SET_CONFIG_FROM_FEATURE "SOURCE_DVFS_CONFIG_NAME" \
    "SEC_FLOATING_FEATURE_COMMON_CONFIG_DVFS_CONFIG_NAME" \
    "SEC_FLOATING_FEATURE_SYSTEM_CONFIG_DVFS_CONFIG_NAME"
SET_CONFIG_FROM_FEATURE "SOURCE_NFC_CHIP_VENDOR" \
    "SEC_FLOATING_FEATURE_NFC_CONFIG_CHIP_VENDOR"
SET_CONFIG_FROM_FEATURE "SOURCE_FP_SENSOR_CONFIG" \
    "SEC_FLOATING_FEATURE_FRAMEWORK_CONFIG_FINGERPRINT_FEATURES" \
    "SEC_FLOATING_FEATURE_BIOAUTH_CONFIG_FINGERPRINT_FEATURES"
SET_CONFIG_FROM_FEATURE "SOURCE_HFR_MODE" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_HFR_MODE"
SET_CONFIG_FROM_FEATURE "SOURCE_HFR_SUPPORTED_REFRESH_RATE" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_HFR_SUPPORTED_REFRESH_RATE"
SET_CONFIG_FROM_FEATURE "SOURCE_HFR_DEFAULT_REFRESH_RATE" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_HFR_DEFAULT_REFRESH_RATE"
SET_CONFIG_FROM_FEATURE "SOURCE_HFR_SEAMLESS_BRT" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_HFR_SEAMLESS_BRT"
SET_CONFIG_FROM_FEATURE "SOURCE_HFR_SEAMLESS_LUX" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_HFR_SEAMLESS_LUX"
SET_CONFIG_FROM_FEATURE "SOURCE_MDNIE_SUPPORTED_MODES" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_MDNIE_SUPPORTED_MODES"
SET_CONFIG_FROM_FEATURE "SOURCE_MDNIE_WEAKNESS_SOLUTION_FUNCTION" \
    "SEC_FLOATING_FEATURE_LCD_CONFIG_MDNIE_WEAKNESS_SOLUTION_FUNCTION"

SET_CONFIG_FROM_PATH_EXISTS "SOURCE_HAS_MASS_CAMERA_APP" \
    "system/system/priv-app/MassCameraApp" \
    "system/priv-app/MassCameraApp"
SET_CONFIG_FROM_PATH_EXISTS "SOURCE_IS_ESIM_SUPPORTED" \
    "system/system/etc/permissions/android.hardware.telephony.euicc.xml" \
    "system/etc/permissions/android.hardware.telephony.euicc.xml" \
    "product/etc/permissions/android.hardware.telephony.euicc.xml" \
    "product/priv-app/EuiccGoogle"
SET_CONFIG_FROM_PATH_EXISTS "SOURCE_SUPPORT_HOTSPOT_6GHZ" "product/overlay/SoftapOverlay6GHz"
SET_CONFIG_FROM_PATH_EXISTS "SOURCE_SUPPORT_HOTSPOT_DUALAP" "product/overlay/SoftapOverlayDualAp"
SET_CONFIG_FROM_PATH_EXISTS "SOURCE_SUPPORT_HOTSPOT_ENHANCED_OPEN" "product/overlay/SoftapOverlayOWE"

{
    echo "source_firmware=$SOURCE_FIRMWARE"
    echo "source_path=$SOURCE_DIR"
    echo "metadata_refreshed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    for KEY in \
        SOURCE_CODENAME \
        SOURCE_API_LEVEL \
        SOURCE_PRODUCT_FIRST_API_LEVEL \
        SOURCE_VNDK_VERSION \
        SOURCE_HAS_SYSTEM_EXT \
        SOURCE_SUPER_GROUP_NAME \
        SOURCE_AUTO_BRIGHTNESS_TYPE \
        SOURCE_DVFS_CONFIG_NAME \
        SOURCE_NFC_CHIP_VENDOR \
        SOURCE_FP_SENSOR_CONFIG \
        SOURCE_HAS_MASS_CAMERA_APP \
        SOURCE_HFR_MODE \
        SOURCE_HFR_SUPPORTED_REFRESH_RATE \
        SOURCE_HFR_DEFAULT_REFRESH_RATE \
        SOURCE_IS_ESIM_SUPPORTED \
        SOURCE_SUPPORT_HOTSPOT_6GHZ \
        SOURCE_SUPPORT_HOTSPOT_DUALAP \
        SOURCE_SUPPORT_HOTSPOT_ENHANCED_OPEN
    do
        grep "^${KEY}=" "$CONFIG_FILE" || true
    done
} > "$AUDIT_FILE"

LOG "- Refreshed source metadata from ${SOURCE_DIR//$SRC_DIR\//}"
