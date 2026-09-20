LOG_STEP_IN "- Replacing camera blobs"
BLOBS_LIST="
system/lib64/libenn_wrapper_system.so
system/lib64/libpic_best.arcsoft.so
system/lib64/libdualcam_portraitlighting_gallery_360.so
system/lib64/libarcsoft_dualcam_portraitlighting.so
system/lib64/libdualcam_refocus_gallery_54.so
system/lib64/libhybrid_high_dynamic_range.arcsoft.so
system/lib64/libae_bracket_hdr.arcsoft.so
system/lib64/libface_recognition.arcsoft.so
system/lib64/libmf_bayer_enhance.arcsoft.so
system/lib64/libDualCamBokehCapture.camera.samsung.so
"
for blob in $BLOBS_LIST
do
    DELETE_FROM_WORK_DIR "system" "$blob" &
done

WAIT_FOR_BACKGROUND_JOBS || exit 1

BLOBS_LIST="
system/lib64/libPortraitDistortionCorrectionCali.arcsoft.so
system/lib64/libMultiFrameProcessing10.camera.samsung.so
system/lib64/libMultiFrameProcessing20.camera.samsung.so
system/lib64/libMultiFrameProcessing20Day.camera.samsung.so
system/lib64/libMultiFrameProcessing30.camera.samsung.so
system/lib64/libMultiFrameProcessing30Tuning.camera.samsung.so
system/lib64/vendor.samsung_slsi.hardware.iva@1.0.so
system/lib64/vendor.samsung_slsi.hardware.MultiFrameProcessing20@1.0.so
"
for blob in $BLOBS_LIST
do
    ADD_TO_WORK_DIR "$TARGET_FIRMWARE" "system" "$blob" 0 0 644 "u:object_r:system_lib_file:s0" &
done

WAIT_FOR_BACKGROUND_JOBS || exit 1

LOG_STEP_OUT

LOG_STEP_IN "- Removing HDR10+ check"
if [[ "$TARGET_SINGLE_SYSTEM_IMAGE" == "essi85" ]]; then
    # Never mix an Android 15 media framework library into the Android 16
    # process graph. The older pa3qxxx blob pulls libomafldrm.so and obsolete
    # Binder symbols into app_process64, preventing zygote from linking. The
    # API 36 donor implementation was confirmed live through system_server.
    STAGEFRIGHT="$WORK_DIR/system/system/lib64/libstagefright.so"
    if [ "$(sha256sum "$STAGEFRIGHT" | cut -d " " -f 1)" != \
            "6727f7136e0ca304f556fdb96bd9a877e616687a5c2bf3faaad7db7e79acd91c" ]; then
        ABORT "Unexpected essi85 API 36 libstagefright input"
    fi
    LOG "- Retaining the source API 36 libstagefright"

    # Samsung's reconfigEncoder4OtherApps passes a 512-byte fread count for a
    # 255-byte stack buffer and then appends a NUL byte at buffer[bytes_read].
    # Android 16 FORTIFY correctly aborts mediaserver when video recording
    # reaches that path. Limit the read to 254 bytes so the terminator also
    # remains inside the original buffer.
    HEX_PATCH "$STAGEFRIGHT" \
        "2100805202408052e30314aae41f8052f7430091" \
        "21008052c21f8052e30314aae41f8052f7430091" || \
        ABORT "Failed to bound Samsung video encoder fread"
    if [ "$(sha256sum "$STAGEFRIGHT" | cut -d " " -f 1)" != \
            "dd20c5a7b300f6b90c98d3dc1e1957d71a7ef9e59b0e0f58c41151d17b1c189d" ]; then
        ABORT "Unexpected patched essi85 API 36 libstagefright output"
    fi
else
    ADD_TO_WORK_DIR "pa3qxxx" "system" \
        "system/lib64/libstagefright.so" \
        0 0 644 "u:object_r:system_lib_file:s0"
    HEX_PATCH "$WORK_DIR/system/system/lib64/libstagefright.so" \
        "010140f9cf390594a0500034" "010140f91f2003d51f2003d5"
fi
unset STAGEFRIGHT

# Add prebuilt libs from other devices
BLOBS_LIST="
system/lib64/libeden_wrapper_system.so
system/lib64/libsnap_aidl.snap.samsung.so
"
for blob in $BLOBS_LIST
do
    ADD_TO_WORK_DIR "p3sxxx" "system" "$blob" 0 0 644 "u:object_r:system_lib_file:s0"
done
LOG_STEP_OUT

LOG_STEP_OUT "- Adding S21 (p3sxxx) SWISP models"
DELETE_FROM_WORK_DIR "vendor" "saiv/swisp_1.0"
ADD_TO_WORK_DIR "p3sxxx" "vendor" "saiv/swisp_1.0"

BLOBS_LIST="
system/lib64/libSwIsp_core.camera.samsung.so
system/lib64/libSwIsp_wrapper_v1.camera.samsung.so
"
for blob in $BLOBS_LIST
do
    ADD_TO_WORK_DIR "p3sxxx" "system" "$blob" 0 0 644 "u:object_r:system_lib_file:s0" &
done
LOG_STEP_OUT

LOG_STEP_IN "- Adding A26 (a26xxx) Polarr SDK blobs"
ADD_TO_WORK_DIR "a26xxx" "system" "system/etc/public.libraries-polarr.txt" 0 0 644 "u:object_r:system_file:s0"
ADD_TO_WORK_DIR "a26xxx" "system" "system/lib64/libBestComposition.polarr.so" 0 0 644 "u:object_r:system_lib_file:s0"
ADD_TO_WORK_DIR "a26xxx" "system" "system/lib64/libFeature.polarr.so" 0 0 644 "u:object_r:system_lib_file:s0"
ADD_TO_WORK_DIR "a26xxx" "system" "system/lib64/libTracking.polarr.so" 0 0 644 "u:object_r:system_lib_file:s0"
LOG_STEP_OUT

LOG_STEP_IN "- Cleaning SamsungCamera OAT"
DELETE_FROM_WORK_DIR "system" "system/priv-app/SamsungCamera/oat"
DELETE_FROM_WORK_DIR "system" "system/priv-app/SamsungCamera/SamsungCamera.apk.prof"
DELETE_FROM_WORK_DIR "system" "system/app/FilterProvider/oat"
LOG_STEP_OUT

LOG_STEP_IN "- Pinning the source-generation FilterProvider"
# The photo editor dies the moment its Filters tab loads:
#
#   FATAL EXCEPTION: Effect_Init_Thread  (com.sec.android.mimage.photoretouching)
#   java.lang.StringIndexOutOfBoundsException: length=22; index=44
#     at com.samsung.android.camera.filter.SemFilterManager.loadFilter
#
# SemFilterManager lives in the source One UI 8.5 secimaging.jar (byte-identical
# to the donor on a live device). loadFilter() queries
# content://com.samsung.android.provider.filterprovider/allfilters with a null
# projection and then strips package_name.length() + 1 characters off each
# filename. A device that shipped this ROM was running FilterProvider 7.0.12
# (targetSdk 34 - the Android 12 generation), which seeds a myfilter row with a
# bare filename: "myfilter_sample_05.sel" is 22 characters while package_name
# "com.samsung.android.provider.filterprovider" is 43, so substring(44) throws.
# The donor ships 9.5.18 (targetSdk 35); installing it live produced 13 rows
# with zero malformed filenames.
#
# The work dir is expected to carry the donor copy already, so this is belt and
# braces: it makes the provider generation deterministic instead of dependent on
# whatever an incremental work dir happens to hold. Both APKs are signed with
# the same Samsung Cert, so nothing else in the tree has to change.
DELETE_FROM_WORK_DIR "system" "system/app/FilterProvider/FilterProvider.apk"
ADD_TO_WORK_DIR "$FW_DIR/$SOURCE_FIRMWARE_PATH" "system" \
    "system/app/FilterProvider/FilterProvider.apk" 0 0 644 "u:object_r:system_file:s0"
LOG_STEP_OUT

LOG_STEP_IN "- Fixing AI Photo Editor"
cp -a --preserve=all \
    "$WORK_DIR/system/system/cameradata/portrait_data/single_bokeh_feature.json" \
    "$WORK_DIR/system/system/cameradata/portrait_data/nexus_bokeh_feature.json"
SET_METADATA "system" "system/cameradata/portrait_data/nexus_bokeh_feature.json" 0 0 644 "u:object_r:system_file:s0"
sed -i "s/MODEL_TYPE_INSTANCE_CAPTURE/MODEL_TYPE_OBJ_INSTANCE_CAPTURE/g" \
    "$WORK_DIR/system/system/cameradata/portrait_data/single_bokeh_feature.json"
sed -i \
    's/system\/cameradata\/portrait_data\/single_bokeh_feature.json/system\/cameradata\/portrait_data\/nexus_bokeh_feature.json\x00/g' \
    "$WORK_DIR/system/system/lib64/libPortraitSolution.camera.samsung.so"
LOG_STEP_OUT

LOG_STEP_IN "- Adding S21 (p3sxxx) SingleTake models"
DELETE_FROM_WORK_DIR "vendor" "etc/singletake"
ADD_TO_WORK_DIR "p3sxxx" "vendor" "etc/singletake"

BLOBS_LIST="
system/priv-app/SingleTakeService/SingleTakeService.apk
system/cameradata/singletake/service-feature.xml
"
for blob in $BLOBS_LIST
do
    ADD_TO_WORK_DIR "p3sxxx" "system" "$blob" 0 0 644 "u:object_r:system_file:s0" &
done

WAIT_FOR_BACKGROUND_JOBS || exit 1

if [[ "${KEEP_SIGNED_APKS_STOCK:-false}" == "true" && \
        "${ENABLE_SCOPED_PLATFORM_APK_REBUILDS:-false}" != "true" ]]; then
    # The module payload contains an intentionally stripped SamsungCamera that
    # the legacy pipeline expected to rebuild and re-sign. When the scoped
    # platform-signature bridge is disabled, restore the complete Samsung-
    # signed API 36 source APK instead.
    LOG "- Restoring source-signed SamsungCamera (scoped rebuild disabled)"
    ADD_TO_WORK_DIR "$FW_DIR/$SOURCE_FIRMWARE_PATH" "system" \
        "system/priv-app/SamsungCamera/SamsungCamera.apk"
else
    LOG "- Decompiling the standard EternityROM 5.5 SamsungCamera"
    DECODE_APK "system" "system/priv-app/SamsungCamera/SamsungCamera.apk"
fi

# Camera 14.1.01.17 declares extractNativeLibs=false, but its embedded arm64
# libraries are not page-aligned. Android therefore cannot mmap them from the
# signed APK and looks in the package's legacy nativeLibraryDir instead. Keep
# the genuine Samsung-signed APK byte-for-byte intact and provide exact copies
# of its native payload in that adjacent directory.
LOG "- Extracting standard SamsungCamera native libraries"
CAMERA_APK="$WORK_DIR/system/system/priv-app/SamsungCamera/SamsungCamera.apk"
CAMERA_LIB_DIR="$WORK_DIR/system/system/priv-app/SamsungCamera/lib/arm64"
CAMERA_NATIVE_LIBS="
libmpbase.so
libcamera_effect_processor_jni.so
libEventFinderResultConverter.camera.samsung.so
libdirectbuffer-jni.so
libSceneDetectorJNI.so
libimagexmpinjector.so
libhandgesture.arcsoft.so
libatomjpeg_panorama_enc.quram.so
libpanorama.arcsoft.so
libnode-jni.so
libc++_shared.so
libPanoramaInterface_arcsoft.so
libtype-converter.so
libnativeutils-jni.so
libarcore_sdk_c.so
libimageutils-jni.so
librenderscript-toolkit.so
libarcore_sdk_jni.so
libDiagMonKey.so
"

DELETE_FROM_WORK_DIR "system" "system/priv-app/SamsungCamera/lib"
mkdir -p "$CAMERA_LIB_DIR"
SET_METADATA "system" "system/priv-app/SamsungCamera/lib" \
    0 0 755 "u:object_r:system_file:s0"
SET_METADATA "system" "system/priv-app/SamsungCamera/lib/arm64" \
    0 0 755 "u:object_r:system_file:s0"

for library in $CAMERA_NATIVE_LIBS; do
    if ! unzip -q -j "$CAMERA_APK" "lib/arm64-v8a/$library" \
            -d "$CAMERA_LIB_DIR"; then
        ABORT "Missing SamsungCamera native library: $library"
    fi
    [ -s "$CAMERA_LIB_DIR/$library" ] || \
        ABORT "Empty SamsungCamera native library: $library"
    SET_METADATA "system" \
        "system/priv-app/SamsungCamera/lib/arm64/$library" \
        0 0 644 "u:object_r:system_file:s0"
done
unset CAMERA_APK CAMERA_LIB_DIR CAMERA_NATIVE_LIBS library

LOG_STEP_OUT
