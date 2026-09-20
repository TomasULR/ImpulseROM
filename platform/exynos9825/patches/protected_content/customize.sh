# Restore "Extra dim" (extreme screen dimming) and protected-content support on d2s.
#
# One UI 8.5 hides the Extra dim entry behind
# SecAccessibilityUtils.isSupportReduceBrightness(), which requires BOTH:
#   1. ro.surface_flinger.protected_contents to be true, and
#   2. ro.product.vendor.device to not prefix-match excludeDeviceNameSet,
#      which holds {"beyond", "d1", "d2"} -- and "d2s" matches "d2".
# SystemUI's ReduceBrightColorsTile repeats the same two checks for the
# Quick Settings tile. Samsung Accessibility repeats them once more in the
# Modes and Routines provider; without patching that provider, the action is
# shown as unavailable even though the ColorDisplayService backend works.
#
# (1) is a vendor prop that the r12s source firmware sets in vendor/build.prop
# but the d2s vendor partition never had, so the system half of this port looks
# for something its own vendor never declares. We restore it.
#
# (2) needs a smali edit. The upstream 0001-Remove-device-specific-checks.patch
# files are kept alongside as *.patch.disabled: they were cut against a One UI 7
# SecSettings where these classes lived in smali_classes4, and they rewrite
# control flow. Here the classes sit in smali_classes5 and the surrounding code
# reuses the registers those hunks overwrite, so instead we only rewrite the
# three string literals in place. Instruction count, register allocation and
# every branch target stay byte-for-byte as decoded.

LOG_STEP_IN "- Restoring protected content support"
SET_PROP "vendor" "ro.surface_flinger.protected_contents" "1"
LOG_STEP_OUT

# UNBLACKLIST_EXTRA_DIM <partition> <apk> <smali class file name>
# Neutralises the Note10/S10 entries in that class' excludeDeviceNameSet.
UNBLACKLIST_EXTRA_DIM()
{
    local PARTITION="$1"
    local APK="$2"
    local CLASS="$3"
    local ROOT="$APKTOOL_DIR/$PARTITION/${APK//system\//}"
    local TARGET

    TARGET="$(find "$ROOT" -type f -name "$CLASS" -print -quit 2>/dev/null || true)"
    if [ -z "$TARGET" ]; then
        LOGW "$CLASS not found under /$PARTITION/$APK; skipping Extra dim unblacklist"
        return 0
    fi

    python3 - "$TARGET" <<'PYEOF' || return 1
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    lines = fh.readlines()

# Only touch literals inside the method that seeds excludeDeviceNameSet, so an
# unrelated "d1"/"d2" string elsewhere in the class is never rewritten.
start = next(
    (i for i, l in enumerate(lines) if "excludeDeviceNameSet:Ljava/util/HashSet;" in l and "sput-object" in l),
    None,
)
if start is None:
    sys.exit("excludeDeviceNameSet initialiser not found in %s" % path)

end = next((i for i in range(start, len(lines)) if lines[i].startswith(".end method")), len(lines))

pattern = re.compile(r'^(\s*const-string(?:/jumbo)? v\d+, ")(beyond|d1|d2)(")\s*$')
changed = 0
for i in range(start, end):
    m = pattern.match(lines[i].rstrip("\n"))
    if m:
        lines[i] = "%simpulse-no-match-%s%s\n" % (m.group(1), m.group(2), m.group(3))
        changed += 1

# SecSettings carries all three; the SystemUI tile is allowed to carry fewer, so
# only an empty rewrite is treated as drift worth failing the build over.
if changed == 0:
    sys.exit("no excluded device names rewritten in %s" % path)

with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(lines)
print("  - unblacklisted %d device name(s) in %s" % (changed, path.rsplit("/", 1)[-1]))
PYEOF

    return 0
}

# Samsung Accessibility obfuscates its feature helper, so keep this separate
# from the named SecSettings/SystemUI classes. The exact current helper path is
# intentional: a donor update that moves or rewrites it must stop the build for
# review instead of accidentally changing an unrelated obfuscated class.
UNBLACKLIST_EXTRA_DIM_ROUTINES()
{
    local ROOT="$APKTOOL_DIR/system/priv-app/Accessibility/Accessibility.apk"
    local TARGET="$ROOT/smali/z7/g.smali"

    if [ ! -f "$TARGET" ]; then
        LOGE "Samsung Accessibility Extra dim helper not found: $TARGET"
        return 1
    fi

    python3 - "$TARGET" <<'PYEOF' || return 1
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    lines = fh.readlines()

text = "".join(lines)
required_markers = (
    '"ro.surface_flinger.protected_contents"',
    '"ro.product.vendor.device"',
    'Ljava/lang/String;->startsWith(Ljava/lang/String;)Z',
)
missing = [marker for marker in required_markers if marker not in text]
if missing:
    sys.exit("unexpected Samsung Accessibility helper in %s; missing %s" %
             (path, ", ".join(missing)))

pattern = re.compile(r'^(\s*const-string(?:/jumbo)? v\d+, ")(beyond|d1|d2)(")\s*$')
changed_names = []
for index, line in enumerate(lines):
    match = pattern.match(line.rstrip("\n"))
    if match:
        lines[index] = "%simpulse-no-match-%s%s\n" % (
            match.group(1), match.group(2), match.group(3)
        )
        changed_names.append(match.group(2))

if sorted(changed_names) != ["beyond", "d1", "d2"]:
    sys.exit("expected exactly beyond/d1/d2 in %s, changed %r" %
             (path, changed_names))

with open(path, "w", encoding="utf-8") as fh:
    fh.writelines(lines)
print("  - unblacklisted Modes and Routines Extra dim provider")
PYEOF
}

LOG_STEP_IN "- Unblacklisting Extra dim for d2s"

# SystemUI is one of the five APKs on apktool.sh's scoped platform-rebuild
# allowlist, so this edit survives into the package and the Quick Settings tile
# becomes available.
DECODE_APK "system_ext" "priv-app/SystemUI/SystemUI.apk" || exit 1
UNBLACKLIST_EXTRA_DIM "system_ext" "priv-app/SystemUI/SystemUI.apk" \
    "ReduceBrightColorsTile.smali" || exit 1

# This package owns the Extra dim action exposed to Modes and Routines. It is
# rebuilt through the same package-scoped platform-signature bridge as SystemUI.
DECODE_APK "system" "system/priv-app/Accessibility/Accessibility.apk" || exit 1
UNBLACKLIST_EXTRA_DIM_ROUTINES || exit 1

# SecSettings is NOT on that allowlist. With KEEP_SIGNED_APKS_STOCK=true (the
# container default) apktool.sh keeps it byte-identical to stock, so patching it
# would be silently discarded after a 122 MB decode. Rebuilding it would also
# flip its signature from Samsung Cert to the ROM platform key, which breaks a
# dirty flash for anyone upgrading in place.
#
# Set IMPULSE_REBUILD_SECSETTINGS=true (and add SecSettings to the allowlist in
# apktool.sh) to also surface the entry under
# Settings > Accessibility > Vision enhancements. Only worth doing for a release
# build that ships with a mandatory Format Data anyway. Until then the tile is
# the supported path, and the underlying secure setting
# (reduce_bright_colors_activated) works regardless.
if [[ "${IMPULSE_REBUILD_SECSETTINGS:-false}" == "true" ]]; then
    DECODE_APK "system" "system/priv-app/SecSettings/SecSettings.apk" || exit 1
    UNBLACKLIST_EXTRA_DIM "system" "system/priv-app/SecSettings/SecSettings.apk" \
        "SecAccessibilityUtils.smali" || exit 1
else
    LOG "- Skipping SecSettings (not on the scoped rebuild allowlist)"
fi

LOG_STEP_OUT
