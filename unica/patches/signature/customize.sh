SIGNATURE_TARGET="$APKTOOL_DIR/system/framework/services.jar/smali_classes2/com/android/server/pm/ScanPackageUtils.smali"

DECODE_APK "system" "system/framework/services.jar"
if [ -f "$SIGNATURE_TARGET" ]; then
    APPLY_PATCH "system" "system/framework/services.jar" "$MODPATH/0001-Allow-custom-platform-signature.patch"

    CERT_PREFIX="aosp"
    $ROM_IS_OFFICIAL && CERT_PREFIX="impulse"

    CERT_SIGNATURE=$(sed '/CERTIFICATE/d' "$SRC_DIR/security/${CERT_PREFIX}_platform.x509.pem" | tr -d '\n' | base64 -d | xxd -p -c 0)

    if ! grep -q "CONFIG_CUSTOM_PLATFORM_SIGNATURE" "$SIGNATURE_TARGET"; then
        LOGE "Custom platform signature marker missing after patch"
        exit 1
    fi
    sed -i "s|CONFIG_CUSTOM_PLATFORM_SIGNATURE|$CERT_SIGNATURE|g" "$SIGNATURE_TARGET"
else
    LOGW "\033[0;33m! ScanPackageUtils.smali not found; skipping platform signature compatibility patch\033[0m"
fi

unset SIGNATURE_TARGET CERT_PREFIX CERT_SIGNATURE
