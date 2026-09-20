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

# [
source "$SRC_DIR/scripts/utils/build_utils.sh" || exit 1

FRAMEWORK_DIR="$TOOLS_DIR/apktool/framework"
FRAMEWORK_TAG="$(GET_PROP "system" "ro.build.version.incremental")"

FORCE=false
PARTITION=""
FILE=""

INPUT_FILE=""
OUTPUT_PATH=""
ARGS=""
DEX_INVENTORY_TOOL="$SRC_DIR/scripts/internal/dex_inventory.py"

THREAD_COUNT=$(awk -v max="$(nproc)" '/MemTotal/ {
  tc = int(($2 + 1048575) / 2097152);
  print (tc < 1 ? 1 : (tc > max ? max : tc));
}' /proc/meminfo)

[ -n "$GITHUB_ACTIONS" ] && THREAD_COUNT=1
[ -n "${APKTOOL_THREAD_COUNT:-}" ] && THREAD_COUNT="$APKTOOL_THREAD_COUNT"

if ! [[ "$THREAD_COUNT" =~ ^[0-9]+$ ]] || [ "$THREAD_COUNT" -lt 1 ]; then
    LOGE "Invalid APKTOOL_THREAD_COUNT: $THREAD_COUNT"
    exit 1
fi

WAIT_FOR_BACKGROUND_JOBS()
{
    local STATUS=0
    local PID

    for PID in $(jobs -p); do
        wait "$PID" || STATUS=1
    done

    return "$STATUS"
}

GET_DEX_CACHE_DIR()
{
    echo "$OUTPUT_PATH/../.$(basename "$OUTPUT_PATH").dex_cache"
}

GET_DEX_MAP_FILE()
{
    echo "$(GET_DEX_CACHE_DIR)/logical_dex_map.tsv"
}

GET_DEX_INVENTORY_DIR()
{
    echo "$(GET_DEX_CACHE_DIR)/inventories"
}

GET_DEX_SENTINEL_FILE()
{
    echo "$SRC_DIR/scripts/internal/dex_sentinels/$PARTITION/$FILE.txt"
}

GET_DEX_SENTINEL_MAP_FILE()
{
    echo "$(GET_DEX_CACHE_DIR)/sentinel_map.tsv"
}

GET_DEX_ALLOWED_ADDITIONS_FILE()
{
    echo "$SRC_DIR/scripts/internal/dex_allowed_additions/$PARTITION/$FILE.tsv"
}

SNAPSHOT_DEX_INVENTORIES()
{
    local SENTINEL_FILE
    local -a CMD=(
        python3 "$DEX_INVENTORY_TOOL" snapshot
        --artifact "$INPUT_FILE"
        --map "$(GET_DEX_MAP_FILE)"
        --manifest-dir "$(GET_DEX_INVENTORY_DIR)"
    )

    SENTINEL_FILE="$(GET_DEX_SENTINEL_FILE)"
    if [ -f "$SENTINEL_FILE" ]; then
        CMD+=(
            --sentinels "$SENTINEL_FILE"
            --sentinel-output "$(GET_DEX_SENTINEL_MAP_FILE)"
        )
    fi

    "${CMD[@]}"
}

VERIFY_DEX_INVENTORIES()
{
    local ARTIFACT="$1"
    local LABEL="$2"
    local ALLOWED_ADDITIONS
    local SENTINEL_MAP
    local -a CMD=(
        python3 "$DEX_INVENTORY_TOOL" verify
        --artifact "$ARTIFACT"
        --map "$(GET_DEX_MAP_FILE)"
        --manifest-dir "$(GET_DEX_INVENTORY_DIR)"
        --label "$LABEL"
    )

    SENTINEL_MAP="$(GET_DEX_SENTINEL_MAP_FILE)"
    if [ -f "$SENTINEL_MAP" ]; then
        CMD+=(--sentinel-map "$SENTINEL_MAP")
    fi

    ALLOWED_ADDITIONS="$(GET_DEX_ALLOWED_ADDITIONS_FILE)"
    if [ -f "$ALLOWED_ADDITIONS" ]; then
        CMD+=(
            --source-artifact "$INPUT_FILE"
            --allowed-additions "$ALLOWED_ADDITIONS"
        )
    fi

    "${CMD[@]}"
}

GET_SMALI_TREE_HASH()
{
    find "$1" -type f -name "*.smali" -print0 | sort -z | xargs -0 sha1sum | sha1sum | cut -d " " -f 1
}

GET_DECODED_HASH_FILE()
{
    echo "$OUTPUT_PATH/../.$(basename "$OUTPUT_PATH").decoded_hash"
}

# Content hash of the whole decoded tree (smali, resources, assets, manifest,
# original META-INF) excluding transient reassembled *.dex and build/dist dirs.
# Lets BUILD tell whether a customization step actually changed the package.
GET_APKTOOL_TREE_HASH()
{
    find "$OUTPUT_PATH" -type f ! -name "*.dex" \
        ! -path "$OUTPUT_PATH/build/*" ! -path "$OUTPUT_PATH/dist/*" -print0 \
        | sort -z | xargs -0 sha1sum | sha1sum | cut -d " " -f 1
}

ASSEMBLE_SMALI_DIR()
{
    local DEX_API_LEVEL="$1"
    local DEX_OUTPUT="$2"
    local SMALI_DIR="$3"
    local ASSEMBLY_LOG
    local DEX_CACHE_DIR
    local HASH_FILE
    local JUMBO_DIR
    local ORIGINAL_DEX

    DEX_CACHE_DIR="$(GET_DEX_CACHE_DIR)"
    HASH_FILE="$DEX_CACHE_DIR/$(basename "$SMALI_DIR").sha1"
    ORIGINAL_DEX="$DEX_CACHE_DIR/$(basename "$DEX_OUTPUT")"

    # DEX 041 may store multiple logical dex files inside one physical
    # classes.dex entry. Restoring that physical container for the first
    # smali tree and assembling the remaining trees as classes2.dex would
    # duplicate one logical dex and silently retain unpatched bytecode.
    # Reassemble every logical unit when the input used a DEX container.
    if [ ! -f "$DEX_CACHE_DIR/dex_container_v41" ] && \
            [ -f "$ORIGINAL_DEX" ] && [ -f "$HASH_FILE" ] && \
            [[ "$(GET_SMALI_TREE_HASH "$SMALI_DIR")" == "$(cat "$HASH_FILE")" ]]; then
        LOG "- Restoring unchanged $(basename "$DEX_OUTPUT") for ${INPUT_FILE//$WORK_DIR/}"
        cp -f "$ORIGINAL_DEX" "$DEX_OUTPUT"
        return 0
    fi

    ASSEMBLY_LOG="$(mktemp "$DEX_CACHE_DIR/.assemble.$(basename "$SMALI_DIR").XXXXXX")" || return 1
    if smali a -a "$DEX_API_LEVEL" -j "$THREAD_COUNT" \
            -o "$DEX_OUTPUT" "$SMALI_DIR" > "$ASSEMBLY_LOG" 2>&1; then
        rm -f "$ASSEMBLY_LOG"
        return 0
    fi

    # Never treat an arbitrary assembler failure as a jumbo-string issue. The
    # retry is allowed only when smali explicitly prescribes const-string/jumbo,
    # and it operates on a disposable copy so the decoded source is immutable.
    if ! python3 "$DEX_INVENTORY_TOOL" needs-jumbo-retry "$ASSEMBLY_LOG"; then
        LOGE "smali assemble failed for ${SMALI_DIR//$APKTOOL_DIR\//}"
        sed 's/^/  /' "$ASSEMBLY_LOG" >&2
        rm -f "$DEX_OUTPUT" "$ASSEMBLY_LOG"
        return 1
    fi

    LOGW "Retrying proven string-index overflow with jumbo opcodes for ${SMALI_DIR//$APKTOOL_DIR\//}"
    JUMBO_DIR="$(mktemp -d "$DEX_CACHE_DIR/.jumbo.$(basename "$SMALI_DIR").XXXXXX")" || {
        rm -f "$DEX_OUTPUT" "$ASSEMBLY_LOG"
        return 1
    }
    if ! cp -a "$SMALI_DIR/." "$JUMBO_DIR/"; then
        rm -rf "$JUMBO_DIR"
        rm -f "$DEX_OUTPUT" "$ASSEMBLY_LOG"
        return 1
    fi
    while IFS= read -r -d '' f; do
        perl -pi -e 's/^(\s*)const-string(\s)/$1const-string\/jumbo$2/' "$f"
    done < <(find "$JUMBO_DIR" -type f -name "*.smali" -print0)

    rm -f "$DEX_OUTPUT"
    if smali a -a "$DEX_API_LEVEL" -j "$THREAD_COUNT" \
            -o "$DEX_OUTPUT" "$JUMBO_DIR" > "$ASSEMBLY_LOG" 2>&1; then
        rm -rf "$JUMBO_DIR"
        rm -f "$ASSEMBLY_LOG"
        return 0
    fi

    LOGE "smali jumbo retry failed for ${SMALI_DIR//$APKTOOL_DIR\//}"
    sed 's/^/  /' "$ASSEMBLY_LOG" >&2
    rm -rf "$JUMBO_DIR"
    rm -f "$DEX_OUTPUT" "$ASSEMBLY_LOG"
    return 1
}

GET_LOGICAL_DEX_ENTRIES()
{
    local ALL_ENTRIES
    local PHYSICAL_DEX

    ALL_ENTRIES="$(baksmali list dex "$INPUT_FILE")" || return 1

    # Preserve Android's classes.dex, classes2.dex, ... load order. Each
    # physical DEX 041 entry can itself contain /2, /3, ... logical units.
    while IFS= read -r PHYSICAL_DEX; do
        [ "$PHYSICAL_DEX" ] || continue
        printf '%s\n' "$PHYSICAL_DEX"
        while IFS= read -r ENTRY; do
            [[ "$ENTRY" == "$PHYSICAL_DEX/"* ]] || continue
            printf '%s\n' "$ENTRY"
        done < <(printf '%s\n' "$ALL_ENTRIES") | sort -t/ -k2,2n
    done < <(
        find "$OUTPUT_PATH" -maxdepth 1 -type f \
            -regextype posix-extended -regex '.*/classes([0-9]+)?\.dex' \
            -printf '%f\n' | sort -V
    )
}

BUILD()
{
    if [ ! -d "$OUTPUT_PATH" ]; then
        LOGE "Folder not found: ${OUTPUT_PATH//$SRC_DIR\//}"
        exit 1
    fi

    local DECODED_HASH_FILE
    DECODED_HASH_FILE="$(GET_DECODED_HASH_FILE)"

    # Signature safety. Re-signing a platform APK with the ROM key (a different
    # cert than Samsung's platform signature) normally loses platform/signature
    # permissions. Keep every signed APK byte-identical to stock except the
    # exact, preinstalled paths covered by the package+path-scoped Android 16
    # signature bridge in unica/patches/signature.
    #
    # Static product RROs are also deliberate exceptions. They do not receive
    # platform/signature permissions, and Android authorizes them through the
    # product overlay policy. Both generated d2s RROs below were rebuilt with
    # the ROM key and accepted by the API 36 idmap2 binary against the live
    # alpha12 framework/SystemUI without --ignore-overlayable. If these are
    # kept stock, all Note10+ display geometry and brightness resources are
    # silently discarded and the donor S24 FE cutout/corner mask remains live.
    if [[ "${KEEP_SIGNED_APKS_STOCK:-false}" == "true" ]] && \
            [[ "$INPUT_FILE" == *".apk" ]]; then
        case "${INPUT_FILE//$WORK_DIR/}" in
            /product/overlay/framework-res__r12sxxx__auto_generated_rro_product.apk|\
            /product/overlay/SystemUI__r12sxxx__auto_generated_rro_product.apk)
                LOG "- Rebuilding policy-authorized product RRO: ${INPUT_FILE//$WORK_DIR/}"
                ;;
            /system/system/priv-app/BiometricSetting/BiometricSetting.apk|\
            /system/system/priv-app/Accessibility/Accessibility.apk|\
            /system/system/system_ext/priv-app/SystemUI/SystemUI.apk|\
            /system/system/priv-app/EnvironmentAdaptiveDisplay/EnvironmentAdaptiveDisplay.apk|\
            /system/system/priv-app/SamsungCamera/SamsungCamera.apk)
                if [[ "${ENABLE_SCOPED_PLATFORM_APK_REBUILDS:-false}" != "true" ]]; then
                    LOG "- Keeping scoped platform APK at stock (compat bridge disabled): ${INPUT_FILE//$WORK_DIR/}"
                    rm -rf "$OUTPUT_PATH" "$(GET_DEX_CACHE_DIR)" "$DECODED_HASH_FILE"
                    return 0
                fi
                LOG "- Rebuilding signature-bridged platform APK: ${INPUT_FILE//$WORK_DIR/}"
                ;;
            *)
                LOG "- Keeping signed APK at stock: ${INPUT_FILE//$WORK_DIR/}"
                rm -rf "$OUTPUT_PATH" "$(GET_DEX_CACHE_DIR)" "$DECODED_HASH_FILE"
                return 0
                ;;
        esac
    fi

    # A file is only decoded so a customization step can change it. When every
    # such step was skipped (e.g. a drifted patch kept at stock), the tree is
    # byte-identical to the decode output, so rebuilding would only strip the
    # original signature and re-zip/re-sign an unchanged file for nothing. Keep
    # the original untouched.
    if [ -f "$DECODED_HASH_FILE" ] && \
            [[ "$(GET_APKTOOL_TREE_HASH)" == "$(cat "$DECODED_HASH_FILE")" ]]; then
        LOG "- Unchanged after decode, keeping original ${INPUT_FILE//$WORK_DIR/}"
        rm -rf "$OUTPUT_PATH" "$(GET_DEX_CACHE_DIR)" "$DECODED_HASH_FILE"
        return 0
    fi

    LOG "- Building ${INPUT_FILE//$WORK_DIR/}"

    # DEX format version might not be matching minSdkVersion, currently we handle
    # baksmali manually as apktool will by default use minSdkVersion when available
    # instead of the actual DEX format version used in the input apk
    if [ -d "$OUTPUT_PATH/smali" ]; then
        local ACTUAL_SMALI_COUNT
        local DEX_API_LEVEL
        local DEX_INDEX
        local DEX_MAP_FILE
        local DEX_FILENAME
        local DEX_CACHE_DIR
        local DEX_SOURCE_ENTRY
        local EXPECTED_SMALI_COUNT
        local SMALI_DIR
        local SMALI_NAME

        DEX_CACHE_DIR="$(GET_DEX_CACHE_DIR)"
        DEX_MAP_FILE="$(GET_DEX_MAP_FILE)"
        if [ ! -f "$DEX_MAP_FILE" ]; then
            LOGE "Logical DEX map missing for ${INPUT_FILE//$WORK_DIR/}"
            exit 1
        fi
        python3 "$DEX_INVENTORY_TOOL" validate-map --map "$DEX_MAP_FILE" || exit 1

        EXPECTED_SMALI_COUNT="$(($(wc -l < "$DEX_MAP_FILE") - 1))"
        ACTUAL_SMALI_COUNT="$(find "$OUTPUT_PATH" -maxdepth 1 -type d -name 'smali*' | wc -l)"
        if [[ "$ACTUAL_SMALI_COUNT" -ne "$EXPECTED_SMALI_COUNT" ]]; then
            LOGE "Logical smali-tree count mismatch for ${INPUT_FILE//$WORK_DIR/}: decoded=$ACTUAL_SMALI_COUNT expected=$EXPECTED_SMALI_COUNT"
            exit 1
        fi

        while IFS=$'\t' read -r DEX_INDEX DEX_SOURCE_ENTRY SMALI_NAME DEX_FILENAME; do
            [[ "$DEX_INDEX" == "index" ]] && continue
            SMALI_DIR="$OUTPUT_PATH/$SMALI_NAME"
            if [ ! -d "$SMALI_DIR" ]; then
                LOGE "Logical DEX $DEX_INDEX smali tree missing: ${SMALI_DIR//$APKTOOL_DIR/}"
                exit 1
            fi

            DEX_API_LEVEL="$(cat "$DEX_CACHE_DIR/$SMALI_NAME.api" 2> /dev/null)"
            [ "$DEX_API_LEVEL" ] || DEX_API_LEVEL="$(cat "$OUTPUT_PATH/../dex_api_version" 2> /dev/null)"

            # https://github.com/google/smali/blob/3.0.9/dexlib2/src/main/java/com/android/tools/smali/dexlib2/VersionMap.java#L55-L79
            if ! [[ "$DEX_API_LEVEL" =~ ^[0-9]+$ ]] || \
                    [[ "$DEX_API_LEVEL" -lt 1 ]] || [[ "$DEX_API_LEVEL" -gt 35 ]]; then
                LOGE "Unvalid DEX API level: $DEX_API_LEVEL"
                exit 1
            fi

            ASSEMBLE_SMALI_DIR "$DEX_API_LEVEL" \
                "$OUTPUT_PATH/$DEX_FILENAME" "$SMALI_DIR" &
        done < "$DEX_MAP_FILE"

        WAIT_FOR_BACKGROUND_JOBS || exit 1
        VERIFY_DEX_INVENTORIES "$OUTPUT_PATH" \
            "assembled ${INPUT_FILE//$WORK_DIR/}" || exit 1
    fi

    # Copy original META-INF
    mkdir -p "$OUTPUT_PATH/build/apk"
    cp -a "$OUTPUT_PATH/original/META-INF" "$OUTPUT_PATH/build/apk/META-INF"

    EVAL "apktool b -j \"$THREAD_COUNT\" -p \"$FRAMEWORK_DIR\" \"$OUTPUT_PATH\"" || exit 1

    find "$OUTPUT_PATH" -maxdepth 1 -type f -name "*.dex" -delete

    local FILE_NAME
    FILE_NAME="$(basename "$INPUT_FILE")"

    if [[ "$INPUT_FILE" == *".apk" ]]; then
        local CERT_PREFIX="aosp"
        $ROM_IS_OFFICIAL && CERT_PREFIX="impulse"

        LOG "- Signing ${INPUT_FILE//$WORK_DIR/}"
        EVAL "signapk \"$SRC_DIR/security/${CERT_PREFIX}_platform.x509.pem\" \"$SRC_DIR/security/${CERT_PREFIX}_platform.pk8\" \"$OUTPUT_PATH/dist/$FILE_NAME\" \"$OUTPUT_PATH/dist/temp.apk\"" || exit 1
        mv -f "$OUTPUT_PATH/dist/temp.apk" "$OUTPUT_PATH/dist/$FILE_NAME"
    else
        LOG "- Zipaligning ${INPUT_FILE//$WORK_DIR/}"
        EVAL "zipalign -p 4 \"$OUTPUT_PATH/dist/$FILE_NAME\" \"$OUTPUT_PATH/dist/temp\"" || exit 1
        mv -f "$OUTPUT_PATH/dist/temp" "$OUTPUT_PATH/dist/$FILE_NAME"
    fi

    # Verify the exact signed/zipaligned archive that will replace the source,
    # not apktool's intermediate ZIP.
    if [ -f "$(GET_DEX_MAP_FILE)" ]; then
        VERIFY_DEX_INVENTORIES "$OUTPUT_PATH/dist/$FILE_NAME" \
            "final packaged ${INPUT_FILE//$WORK_DIR/}" || exit 1
    fi

    mkdir -p "$(dirname "$INPUT_FILE")"
    mv -f "$OUTPUT_PATH/dist/$FILE_NAME" "$INPUT_FILE"
    rm -rf "$OUTPUT_PATH/build" && rm -rf "$OUTPUT_PATH/dist"

    if [ -d "${INPUT_FILE%/*}/oat" ]; then
        DELETE_FROM_WORK_DIR "$PARTITION" "${FILE%/*}/oat"
    fi
    if [ -f "${INPUT_FILE%/*}/$FILE_NAME.prof" ]; then
        DELETE_FROM_WORK_DIR "$PARTITION" "${FILE%/*}/$FILE_NAME.prof"
    fi
    if [ -f "${INPUT_FILE%/*}/$FILE_NAME.bprof" ]; then
        DELETE_FROM_WORK_DIR "$PARTITION" "${FILE%/*}/$FILE_NAME.bprof"
    fi
}

DECODE()
{
    if [ ! -f "$INPUT_FILE" ]; then
        LOGE "File not found: ${INPUT_FILE//$WORK_DIR/}"
        exit 1
    elif [ -d "$OUTPUT_PATH" ]; then
        if $FORCE; then
            rm -rf "$OUTPUT_PATH"
        else
            LOGE "Output directory already exists (${OUTPUT_PATH//$SRC_DIR\//}). Use --force flag if you want to overwrite it."
            exit 1
        fi
    fi

    if [[ "$(READ_BYTES_AT "$INPUT_FILE" "0" "4")" != "04034b50" ]]; then
        LOGE "File not valid: ${INPUT_FILE//$WORK_DIR/}"
        exit 1
    fi

    LOG "- Decoding ${INPUT_FILE//$WORK_DIR/}"

    # Decode APK with --no-debug-info, which will disassemble DEX file with the following flags:
    # - Disabled synthetic accessors comments
    # - Disabled debug info
    # - Use .locals directive instead of the .registers one
    # - Use a sequential numbering scheme for labels
    EVAL "apktool d -b -j \"$THREAD_COUNT\" -o \"$OUTPUT_PATH\" -p \"$FRAMEWORK_DIR\" -t \"$FRAMEWORK_TAG\" -s \"$INPUT_FILE\"" || exit 1

    # DEX format version might not be matching minSdkVersion, currently we handle
    # baksmali manually as apktool will by default use minSdkVersion when available
    # instead of the actual DEX format version used in the input apk
    if [ -f "$OUTPUT_PATH/classes.dex" ]; then
        local DEX_API_LEVEL
        local DEX_CACHE_DIR
        local DEX_ENTRY
        local DEX_INDEX=0
        local DEX_MAP_FILE
        local DEX_OUTPUT
        local DEX_PHYSICAL_FILE
        local EXPECTED_CLASS_COUNT
        local INVENTORY_FILE
        local SMALI_CLASS_COUNT
        local SMALI_DIR
        local SMALI_OUT

        DEX_CACHE_DIR="$(GET_DEX_CACHE_DIR)"
        DEX_MAP_FILE="$(GET_DEX_MAP_FILE)"
        rm -rf "$DEX_CACHE_DIR"
        mkdir -p "$DEX_CACHE_DIR"
        printf 'index\tsource_entry\tsmali_dir\toutput_dex\n' > "$DEX_MAP_FILE"

        while IFS= read -r DEX_ENTRY; do
            [ "$DEX_ENTRY" ] || continue
            DEX_INDEX=$((DEX_INDEX + 1))
            if [[ "$DEX_INDEX" -eq 1 ]]; then
                SMALI_OUT="smali"
                DEX_OUTPUT="classes.dex"
            else
                SMALI_OUT="smali_classes$DEX_INDEX"
                DEX_OUTPUT="classes$DEX_INDEX.dex"
            fi
            printf '%s\t%s\t%s\t%s\n' \
                "$DEX_INDEX" "$DEX_ENTRY" "$SMALI_OUT" "$DEX_OUTPUT" \
                >> "$DEX_MAP_FILE"
        done < <(GET_LOGICAL_DEX_ENTRIES)

        if [[ "$DEX_INDEX" -lt 1 ]]; then
            LOGE "No logical DEX entries found in ${INPUT_FILE//$WORK_DIR/}"
            exit 1
        fi
        python3 "$DEX_INVENTORY_TOOL" validate-map --map "$DEX_MAP_FILE" || exit 1
        echo -n "$DEX_INDEX" > "$DEX_CACHE_DIR/logical_dex_count"

        while IFS=$'\t' read -r DEX_INDEX DEX_ENTRY SMALI_OUT DEX_OUTPUT; do
            [[ "$DEX_INDEX" == "index" ]] && continue
            DEX_PHYSICAL_FILE="$OUTPUT_PATH/${DEX_ENTRY%%/*}"
            DEX_API_LEVEL="$(DEX_TO_API "$DEX_PHYSICAL_FILE")"
            [ "$DEX_API_LEVEL" ] || exit 1
            echo -n "$DEX_API_LEVEL" > "$OUTPUT_PATH/../dex_api_version"

            cp -f "$DEX_PHYSICAL_FILE" "$DEX_CACHE_DIR/$(basename "$DEX_PHYSICAL_FILE")"
            echo -n "$DEX_API_LEVEL" > "$DEX_CACHE_DIR/$SMALI_OUT.api"
            if [[ "$DEX_ENTRY" == */* ]] || \
                    [[ "$(READ_BYTES_AT "$DEX_PHYSICAL_FILE" "6" "1")" == "31" ]]; then
                touch "$DEX_CACHE_DIR/dex_container_v41"
            fi

            # Disassemble DEX file with the following flags:
            # - Disabled synthetic accessors comments
            # - Disabled debug info
            # - Use .locals directive instead of the .registers one
            # - Use a sequential numbering scheme for labels
            baksmali d -a "$DEX_API_LEVEL" --ac false --di false \
                -j "$THREAD_COUNT" -l -o "$OUTPUT_PATH/$SMALI_OUT" \
                --sl "$INPUT_FILE/$DEX_ENTRY" &
        done < "$DEX_MAP_FILE"

        WAIT_FOR_BACKGROUND_JOBS || exit 1
        SNAPSHOT_DEX_INVENTORIES || exit 1

        while IFS=$'\t' read -r DEX_INDEX DEX_ENTRY SMALI_OUT DEX_OUTPUT; do
            [[ "$DEX_INDEX" == "index" ]] && continue
            SMALI_DIR="$OUTPUT_PATH/$SMALI_OUT"
            INVENTORY_FILE="$(GET_DEX_INVENTORY_DIR)/logical-$DEX_INDEX.inventory.tsv"
            EXPECTED_CLASS_COUNT="$(awk -F '\t' '$1 == "classes" { print $2 }' "$INVENTORY_FILE")"
            SMALI_CLASS_COUNT="$(find "$SMALI_DIR" -type f -name '*.smali' | wc -l)"
            if [[ "$EXPECTED_CLASS_COUNT" -ne "$SMALI_CLASS_COUNT" ]]; then
                LOGE "DEX decode class-count mismatch for ${SMALI_DIR//$APKTOOL_DIR/}: smali=$SMALI_CLASS_COUNT source=$EXPECTED_CLASS_COUNT"
                exit 1
            fi
            GET_SMALI_TREE_HASH "$SMALI_DIR" > "$DEX_CACHE_DIR/$SMALI_OUT.sha1"
        done < "$DEX_MAP_FILE"

        find "$OUTPUT_PATH" -maxdepth 1 -type f -name "*.dex" -delete
    fi

    # https://github.com/iBotPeaches/Apktool/issues/3615
    if [[ "$INPUT_FILE" == *"framework.jar" ]]; then
        if unzip -l "$INPUT_FILE" | grep -q "debian.mime.types"; then
            unzip -q "$INPUT_FILE" "res/*" -d "$OUTPUT_PATH/unknown"
        fi
    fi

    # Baseline for BUILD's unchanged detection: hash the pristine decode output so
    # a later build can tell whether any customization actually touched this file.
    GET_APKTOOL_TREE_HASH > "$(GET_DECODED_HASH_FILE)"
}

# https://github.com/google/smali/blob/3.0.9/dexlib2/src/main/java/com/android/tools/smali/dexlib2/VersionMap.java#L36-L53
DEX_TO_API()
{
    local DEX_FILE="$1"

    local DEX_VERSION
    DEX_VERSION="$(READ_BYTES_AT "$DEX_FILE" "6" "1")"

    local API
    case "$DEX_VERSION" in
        "35")
            API="23"
            ;;
        "37")
            API="25"
            ;;
        "38")
            API="27"
            ;;
        "39")
            API="29"
            ;;
        # READ_BYTES_AT returns the hexadecimal value of the last ASCII digit
        # in the DEX magic. Android 14 dex040 therefore yields 0x30, while
        # Android 15/16 dex041 yields 0x31. This smali writer emits an invalid
        # 112-byte v041 header at API 35 (v041 requires 120 bytes and container
        # fields). API 34 emits a valid standalone v040 DEX and successfully
        # round-trips the v041 instruction set used by the Samsung API 36
        # framework, so container units are deliberately normalized to v040.
        "30")
            API="34"
            ;;
        "31")
            API="34"
            ;;
        *)
            LOGE "Unknown DEX format version ($DEX_VERSION) found in ${DEX_FILE//$APKTOOL_DIR\//}"
            ;;
    esac

    echo "$API"
}

PREPARE_SCRIPT()
{
    if [[ "$#" == 0 ]]; then
        PRINT_USAGE
        exit 1
    fi

    ACTION="$1"
    if [[ "$ACTION" != "decode" ]] && [[ "$ACTION" != "d" ]] && \
            [[ "$ACTION" != "build" ]] && [[ "$ACTION" != "b" ]]; then
        PRINT_USAGE
        exit 1
    fi

    shift

    if [[ "$1" == "--force" ]] || [[ "$1" == "-f" ]]; then
        FORCE=true
        shift
    fi

    PARTITION="$1"
    if [ ! "$PARTITION" ]; then
        PRINT_USAGE
        exit 1
    elif ! IS_VALID_PARTITION_NAME "$PARTITION"; then
        LOGE "\"$PARTITION\" is not a valid partition name"
        exit 1
    fi

    shift

    if [ ! "$1" ]; then
        PRINT_USAGE
        exit 1
    fi

    FILE="$1"
    while [[ "${FILE:0:1}" == "/" ]]; do
        FILE="${FILE:1}"
    done

    local FILE_PATH="$WORK_DIR"
    case "$PARTITION" in
        "system_ext")
            if $TARGET_HAS_SYSTEM_EXT; then
                FILE_PATH+="/system_ext"
            else
                FILE_PATH+="/system/system/system_ext"
            fi
            ;;
        *)
            FILE_PATH+="/$PARTITION"
            ;;
    esac
    FILE_PATH+="/$FILE"
    INPUT_FILE="$FILE_PATH"
    OUTPUT_PATH="$APKTOOL_DIR/$PARTITION/${FILE//system\//}"
}

PRINT_USAGE()
{
    echo "Usage: apktool d[ecode]/b[uild] [options] <partition> <file>" >&2
    echo " -f, --force : Force delete output directory" >&2
}
# ]

ACTION=""

PREPARE_SCRIPT "$@"

if [ ! "$FRAMEWORK_TAG" ]; then
    LOGE "Work dir needs to be set up before using this script"
    exit 1
elif [ ! -f "$FRAMEWORK_DIR/1-$FRAMEWORK_TAG.apk" ]; then
    LOGW "framework-res.apk for \"$FRAMEWORK_TAG\" not found, installing"
    EVAL "apktool if -p \"$FRAMEWORK_DIR\" -t \"$FRAMEWORK_TAG\" \"$WORK_DIR/system/system/framework/framework-res.apk\"" || exit 1
fi

case "$ACTION" in
    "d" | "decode")
        DECODE
        ;;
    "b" | "build")
        BUILD
        ;;
esac

exit 0
