# Samsung Notes is absent from the donor image. Do not enable the legacy
# module's unpinned downloads of unrelated apps for this device.
if [[ "$TARGET_CODENAME" != "d2s" ]]; then
    ABORT "Impulse bundled apps are only validated for d2s" || return 1
fi

NOTES_VERSION="4.4.45.37"
NOTES_SHA256="daed1eff8c8ee9dfb8afe2771e39e893a8808f3230d6d522a8aa647db09b8667"
NOTES_CACHE="$OUT_DIR/downloads/SamsungNotes-$NOTES_VERSION.apk"
mkdir -p "$(dirname "$NOTES_CACHE")"
if [[ ! -f "$NOTES_CACHE" ]]; then
    NOTES_URL="$(GET_GALAXY_STORE_DOWNLOAD_URL "com.samsung.android.app.notes")" || return 1
    [[ "$NOTES_URL" == https://* ]] || { ABORT "Notes requires an HTTPS download"; return 1; }
    DOWNLOAD_FILE "$NOTES_URL" "$NOTES_CACHE.part" || return 1
    if ! printf '%s  %s\n' "$NOTES_SHA256" "$NOTES_CACHE.part" | sha256sum --check --strict -; then
        ABORT "Samsung Store no longer serves the pinned Notes version; supply the verified $NOTES_CACHE" || return 1
    fi
    mv "$NOTES_CACHE.part" "$NOTES_CACHE"
fi
printf '%s  %s\n' "$NOTES_SHA256" "$NOTES_CACHE" | sha256sum --check --strict - || return 1
"${APKSIGNER:-apksigner}" verify "$NOTES_CACHE" || return 1

# Keep Samsung's signature and install as a regular system app, like the
# stock d2s Notes40 package. Store updates remain possible; no data is reset.
NOTES_INPUT="$OUT_DIR/notes-input"
mkdir -p "$NOTES_INPUT/system/app/Notes40"
cp "$NOTES_CACHE" "$NOTES_INPUT/system/app/Notes40/Notes40.apk"
ADD_TO_WORK_DIR "$NOTES_INPUT" "system" "system/app/Notes40/Notes40.apk" \
    0 0 644 "u:object_r:system_file:s0" || return 1
# PackageManager does not unpack JNI payloads into a read-only system app's
# directory. Supply the primary ABI next to the unchanged signed APK.
mkdir -p "$NOTES_INPUT/system/app/Notes40/lib/arm64"
unzip -o -q -j "$NOTES_CACHE" 'lib/arm64-v8a/*.so' \
    -d "$NOTES_INPUT/system/app/Notes40/lib/arm64" || return 1
for NOTES_LIB in "$NOTES_INPUT/system/app/Notes40/lib/arm64/"*.so; do
    [[ -s "$NOTES_LIB" ]] || { ABORT "Missing Notes arm64 native payload"; return 1; }
    ADD_TO_WORK_DIR "$NOTES_INPUT" "system" \
        "system/app/Notes40/lib/arm64/$(basename "$NOTES_LIB")" \
        0 0 644 "u:object_r:system_file:s0" || return 1
done
unset NOTES_VERSION NOTES_SHA256 NOTES_CACHE NOTES_URL NOTES_INPUT NOTES_LIB
