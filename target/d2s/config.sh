#
# Copyright (C) 2024 BlackMesa123
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

# Device configuration file for Galaxy N10+ (Exynos) (d2s)
TARGET_NAME="Galaxy Note10+ (Exynos)"
TARGET_CODENAME="d2s"
TARGET_ASSERT_MODEL=("SM-N975F")
TARGET_PLATFORM="exynos9825"
TARGET_FIRMWARE="SM-N975F/BTU/358780109886445" # Some CSCs didn't received august 2023 update and since we don't use target's CSC we don't care about it
TARGET_EXTRA_FIRMWARES=("")
TARGET_API_LEVEL=31
TARGET_PRODUCT_FIRST_API_LEVEL=28
TARGET_VNDK_VERSION=31
# The fstab.exynos9825 mnt_point for "system" literally reads /system, but
# init's own boot log ("init: Switching root to '/system'") proves this
# ramdisk's init binary performs a genuine switch_root into the system
# partition regardless of that field, matching true system-as-root behavior.
# A flat (non-root) system.img broke that switch_root outright ("Unable to
# move mount at '/dev': No such file or directory" -> immediate kernel
# panic), while the original nested (system-as-root) image let switch_root
# and every partition mount succeed. Keep system-as-root for d2s; a second,
# separate defect (a post-mount hang before SELinux/property loading) is
# still open and unrelated to this setting.
TARGET_SYSTEM_AS_ROOT=true
TARGET_SINGLE_SYSTEM_IMAGE="essi85"
TARGET_OS_FILE_SYSTEM="erofs"
TARGET_SUPER_PARTITION_SIZE=0
TARGET_SUPER_GROUP_NAME="none"
TARGET_SUPER_GROUP_SIZE=0
TARGET_HAS_SYSTEM_EXT=false
TARGET_BOOT_DEVICE_PATH="/dev/block/by-name"
# Verified from TWRP resize2fs output after the EternityROM repartition. These
# are physical partition ceilings, not desired filesystem sizes.
TARGET_SYSTEM_PARTITION_SIZE=9437184000
TARGET_PRISM_PARTITION_SIZE=734003200
TARGET_OPTICS_PARTITION_SIZE=31457280

# SEC Product Feature
TARGET_AUDIO_SUPPORT_ACH_RINGTONE=false
TARGET_AUDIO_SUPPORT_VIRTUAL_VIBRATION=true
TARGET_AUTO_BRIGHTNESS_TYPE="4"
TARGET_DISPLAY_CUTOUT_TYPE="center"
TARGET_DVFS_CONFIG_NAME="dvfs_policy_makalu_xx"
TARGET_FP_SENSOR_CONFIG="google_touch_display_ultrasonic"
TARGET_HAS_HW_MDNIE=true
TARGET_HAS_MASS_CAMERA_APP=false
TARGET_HAS_QHD_DISPLAY=true
TARGET_HFR_DEFAULT_REFRESH_RATE="60"
TARGET_HFR_MODE="0"
TARGET_HFR_SEAMLESS_BRT="none"
TARGET_HFR_SEAMLESS_LUX="none"
TARGET_HFR_SUPPORTED_REFRESH_RATE="60"
TARGET_IS_ESIM_SUPPORTED=false
TARGET_MDNIE_SUPPORTED_MODES="65303"
TARGET_MDNIE_WEAKNESS_SOLUTION_FUNCTION="3"
TARGET_NFC_CHIP_VENDOR="SLSI"
TARGET_SUPPORT_HOTSPOT_6GHZ=false
TARGET_SUPPORT_HOTSPOT_DUALAP=false
TARGET_SUPPORT_HOTSPOT_ENHANCED_OPEN=false
TARGET_SUPPORT_HOTSPOT_WIFI_6=true
TARGET_SUPPORT_HOTSPOT_WPA3=false
TARGET_SUPPORT_WIFI_7=false
