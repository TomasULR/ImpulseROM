LOG_STEP_IN "- Adding Multi-User Support"
SET_PROP "system" "fw.max_users" "8"
SET_PROP "system" "fw.show_multiuserui" "1"
LOG_STEP_OUT

# ro.build.2ndbrand is always "false"
LOG_STEP_IN "- Disabling ASKS"
sed -i "s/ro.build.official.release/ro.build.2ndbrand/g" "$APKTOOL_DIR/system/framework/services.jar/smali/com/android/server/asks/ASKSManagerService.smali"
LOG_STEP_OUT
