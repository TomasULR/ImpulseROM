if [ ! -f "$WORK_DIR/system/system/lib64/libbluetooth_jni.so" ]; then
    BT_APEX="$WORK_DIR/system/system/apex/com.android.btservices.apex"
    if [ ! -f "$BT_APEX" ]; then
        BT_APEX="$WORK_DIR/system/system/apex/com.android.bt.apex"
    fi
    [ -f "$BT_APEX" ] || ABORT "Bluetooth APEX not found"

    LOG_STEP_IN "- Extracting libbluetooth_jni.so from $(basename "$BT_APEX")"

    [ -d "$TMP_DIR" ] && EVAL "rm -rf \"$TMP_DIR\""
    mkdir -p "$TMP_DIR"

    EVAL "unzip -j \"$BT_APEX\" \"apex_payload.img\" -d \"$TMP_DIR\""

    if ! sudo -n true &> /dev/null; then
        LOG "\033[0;33m! Asking user for sudo password\033[0m"
        if ! sudo -v 2> /dev/null; then
            ABORT "Root permissions are required to unpack APEX image"
        fi
    fi

    mkdir -p "$TMP_DIR/tmp_out"
    EVAL "sudo mount -o ro \"$TMP_DIR/apex_payload.img\" \"$TMP_DIR/tmp_out\""
    EVAL "sudo cat \"$TMP_DIR/tmp_out/lib64/libbluetooth_jni.so\" > \"$WORK_DIR/system/system/lib64/libbluetooth_jni.so\""

    EVAL "sudo umount \"$TMP_DIR/tmp_out\""
    rm -rf "$TMP_DIR"

    SET_METADATA "system" "system/lib64/libbluetooth_jni.so" 0 0 644 "u:object_r:system_lib_file:s0"

    LOG_STEP_OUT
fi

BT_LIB="$WORK_DIR/system/system/lib64/libbluetooth_jni.so"
BT_HEX="$(xxd -p "$BT_LIB" | tr -d ' \n')"
BT_PATCHED=false
BT_PATCHES=(
    "480500352800805228cb1e39|2a0000142800805228cb1e39"
    "4805003528008052284b1e39|2a00001428008052284b1e39"
    "28ab5e394805003528008052|28ab5e392a00001428008052"
    "280b5d394805003528008052|280b5d392a00001428008052"
    "97753948050037360080|9775392a000014360080"
    "97773948050037360080|9777392a000014360080"
    "3a009048050037330080|3a00902a000014330080"
    "f6713948050037330080|f671392a000014330080"
    "f6733948050037330080|f673392a000014330080"
    "76743948050037330080|7674392a000014330080"
)

for BT_PATCH in "${BT_PATCHES[@]}"; do
    BT_FROM="${BT_PATCH%%|*}"
    BT_TO="${BT_PATCH##*|}"

    if grep -q "$BT_TO" <<< "$BT_HEX"; then
        LOG "\033[0;33m! Bluetooth library already patched\033[0m"
        BT_PATCHED=true
        break
    elif grep -q "$BT_FROM" <<< "$BT_HEX"; then
        HEX_PATCH "$BT_LIB" "$BT_FROM" "$BT_TO"
        BT_PATCHED=true
        break
    fi
done

if ! $BT_PATCHED; then
    LOGW "\033[0;31m! No Bluetooth Library Patcher pattern matched, skipping\033[0m"
fi

unset BT_LIB BT_HEX BT_PATCHED BT_PATCHES BT_PATCH BT_FROM BT_TO
