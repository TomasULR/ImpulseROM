# SET_CSC_FEATURE_CONFIG "<config>" "<value>"
# Sets the supplied config to the desidered value.
# "-d" or "--delete" can be passed as value to delete the config.
SET_CSC_FEATURE_CONFIG()
{
    local CONFIG="$1"
    local VALUE="$2"

    if grep -q "$CONFIG" "$FILE"; then
        if [[ "$VALUE" == "-d" ]] || [[ "$VALUE" == "--delete" ]]; then
            sed -i "/$CONFIG/d" "$FILE"
        else
            sed -i "/$CONFIG/c\    <$CONFIG>$VALUE<\/$CONFIG>" "$FILE"
        fi
    elif [[ "$VALUE" != "-d" ]] && [[ "$VALUE" != "--delete" ]]; then
        if ! grep -q "Added by " "$FILE"; then
            sed -i "/<\/FeatureSet>/i \    <!-- Added by unica/mods/csc/customize.sh -->" "$FILE"
        fi
        sed -i "/<\/FeatureSet>/i \    <$CONFIG>$VALUE</$CONFIG>" "$FILE"
    fi

    return 0
}

LOG "- Patching CSC model"
SOURCE_MODEL=$(echo -n "$SOURCE_FIRMWARE" | cut -d "/" -f 1)
TARGET_MODEL=$(echo -n "$TARGET_FIRMWARE" | cut -d "/" -f 1)
find "$WORK_DIR/optics" -type f -exec sed -i "s/SAOMC_SM-S938B/SAOMC_${TARGET_MODEL}/g" {} +

LOG_STEP_IN "- Patching CSC Features"
while read -r FILE; do
    (
        LOG "- Decoding $FILE"
        ! grep -q 'CscFeature' "$FILE" && EVAL "$TOOLS_DIR/bin/cscdecoder --decode --in-place \"$FILE\""

        LOG_STEP_IN "- Applying CSC Tweaks"
        if $SOURCE_IS_ESIM_SUPPORTED && ! $TARGET_IS_ESIM_SUPPORTED; then
            SET_CSC_FEATURE_CONFIG "CscFeature_RIL_SupportEsim" "FALSE"
            SET_CSC_FEATURE_CONFIG "CscFeature_SetupWizard_SupportEsimAsPrimary" --delete
        fi

        SET_CSC_FEATURE_CONFIG "CscFeature_VoiceCall_ConfigRecording" "RecordingAllowed"
        SET_CSC_FEATURE_CONFIG "CscFeature_Setting_SupportRealTimeNetworkSpeed" "TRUE"
        SET_CSC_FEATURE_CONFIG "CscFeature_Setting_EnableHwVersionDisplay" "TRUE"
        SET_CSC_FEATURE_CONFIG "CscFeature_Setting_SupportMenuSmartTutor" "FALSE"
        SET_CSC_FEATURE_CONFIG "CscFeature_Setting_ConfigLongPressType" 1
        SET_CSC_FEATURE_CONFIG "CscFeature_Common_DisableBixby" --delete
        LOG_STEP_OUT

        LOG "- Encoding $FILE"
        EVAL "$TOOLS_DIR/bin/cscdecoder --encode --in-place \"$FILE\""
    ) &
done <<< "$(find "$WORK_DIR/optics" -type f -name "cscfeature.xml")"

WAIT_FOR_BACKGROUND_JOBS || exit 1
LOG_STEP_OUT

LOG_STEP_IN "- Patching APKs for network speed monitoring"

DECODE_APK "system" "system/priv-app/SecSettings/SecSettings.apk"
DECODE_APK "system_ext" "priv-app/SystemUI/SystemUI.apk"

PATCH_NETWORK_SPEED_FEATURE_REF()
{
    local REL_PATH="$1"
    local TARGET_FILE="$APKTOOL_DIR/$REL_PATH"

    if [ ! -f "$TARGET_FILE" ]; then
        local APK_PATH="${REL_PATH%%.apk/*}.apk"
        local AFTER_APK="${REL_PATH#*.apk/}"
        local SMALI_SUFFIX="${AFTER_APK#*/}"
        local FOUND_FILE

        FOUND_FILE=$(find "$APKTOOL_DIR/$APK_PATH" -path "*/$SMALI_SUFFIX" -print -quit 2>/dev/null || true)
        if [ -z "$FOUND_FILE" ]; then
            LOGW "APKTOOL file not found: /$REL_PATH; skipping network speed feature ref patch"
            return 0
        fi

        TARGET_FILE="$FOUND_FILE"
    fi

    sed -i "s/CscFeature_Common_SupportZProjectFunctionInGlobal/CscFeature_Setting_SupportRealTimeNetworkSpeed/g" "$TARGET_FILE"
}

FTP="
system/priv-app/SecSettings/SecSettings.apk/smali_classes4/com/samsung/android/settings/eternal/provider/items/NotificationsItem.smali
system/priv-app/SecSettings/SecSettings.apk/smali_classes4/com/samsung/android/settings/notification/ConfigureNotificationMoreSettings\$1.smali
system/priv-app/SecSettings/SecSettings.apk/smali_classes4/com/samsung/android/settings/notification/StatusBarNetworkSpeedController.smali
system_ext/priv-app/SystemUI/SystemUI.apk/smali/com/android/systemui/Rune.smali
system_ext/priv-app/SystemUI/SystemUI.apk/smali/com/android/systemui/QpRune.smali
"
for f in $FTP; do
    PATCH_NETWORK_SPEED_FEATURE_REF "$f"
done
LOG_STEP_OUT
