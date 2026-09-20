from __future__ import annotations

import importlib.util
import base64
import hashlib
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "internal" / "validate_work_dir.py"
)
SPEC = importlib.util.spec_from_file_location("validate_work_dir", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def write_android_note_elf(path: Path, api_level: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 2
    header[5] = 1
    header[6] = 1
    note = struct.pack("<III", 8, 4, 1) + b"Android\0" + struct.pack(
        "<I", api_level
    )
    path.write_bytes(header + note)


class PropertyContextValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_contexts(self, relative_path: str, contents: str) -> None:
        path = self.work_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def validate(self) -> list[str]:
        errors, _, _ = VALIDATOR.validate_property_contexts(self.work_dir)
        return errors

    def write_vndk31_contract(self) -> None:
        vendor_prop = self.work_dir / "vendor/build.prop"
        vendor_prop.parent.mkdir(parents=True, exist_ok=True)
        vendor_prop.write_text("ro.vndk.version=31\n", encoding="utf-8")

        framework_manifest = (
            self.work_dir / "system/system/system_ext/etc/vintf/manifest.xml"
        )
        framework_manifest.parent.mkdir(parents=True, exist_ok=True)
        framework_manifest.write_text(
            '<manifest><vendor-ndk><version>31</version></vendor-ndk></manifest>\n',
            encoding="utf-8",
        )

        vendor_matrix = self.work_dir / "vendor/etc/vintf/compatibility_matrix.xml"
        vendor_matrix.parent.mkdir(parents=True, exist_ok=True)
        vendor_matrix.write_text(
            '<compatibility-matrix><vendor-ndk><version>31</version>'
            '</vendor-ndk></compatibility-matrix>\n',
            encoding="utf-8",
        )

        vndk_apex = (
            self.work_dir
            / "system/system/system_ext/apex/com.android.vndk.v31.apex"
        )
        vndk_apex.parent.mkdir(parents=True, exist_ok=True)
        vndk_apex.write_bytes(b"validated-vndk31")

    def test_allows_exact_and_prefix_in_the_same_file(self) -> None:
        self.write_contexts(
            "system/etc/selinux/plat_property_contexts",
            "persist.sys.theme u:object_r:theme_prop:s0 exact string\n"
            "persist.sys.theme u:object_r:theme_prop:s0\n",
        )
        self.assertEqual([], self.validate())

    def test_rejects_duplicate_prefix_from_split_policy(self) -> None:
        self.write_contexts(
            "system/system_ext/etc/selinux/system_ext_property_contexts",
            "init.svc.vendor.wvkprov_server_hal u:object_r:wvkprov_prop:s0\n",
        )
        self.write_contexts(
            "vendor/etc/selinux/vendor_property_contexts",
            "init.svc.vendor.wvkprov_server_hal "
            "u:object_r:vendor_wvkprov_prop:s0\n",
        )
        errors = self.validate()
        self.assertEqual(1, len(errors))
        self.assertIn("init.svc.vendor.wvkprov_server_hal", errors[0])

    def test_rejects_cross_partition_exact_prefix_overlap(self) -> None:
        self.write_contexts(
            "system/etc/selinux/plat_property_contexts",
            "ro.product.first_api_level u:object_r:build_vendor_prop:s0 exact int\n",
        )
        self.write_contexts(
            "system/system_ext/etc/selinux/system_ext_property_contexts",
            "ro.product.first_api_level u:object_r:domain_read_prop:s0\n",
        )
        errors = self.validate()
        self.assertEqual(1, len(errors))
        self.assertIn("multiple split-policy files", errors[0])

    def test_rejects_missing_context_files(self) -> None:
        errors = self.validate()
        self.assertEqual(1, len(errors))
        self.assertIn("no property-context files", errors[0])

    def test_rejects_elf32_vendor_without_runtime_entry_points(self) -> None:
        vendor_binary = self.work_dir / "vendor/bin/hw/camera-provider"
        vendor_binary.parent.mkdir(parents=True)
        vendor_binary.write_bytes(b"\x7fELF\x01" + b"\x00" * 32)

        errors, count = VALIDATOR.validate_multilib_runtime(self.work_dir)

        self.assertEqual(1, count)
        self.assertEqual(1, len(errors))
        self.assertIn("32-bit runtime entry points are missing or invalid", errors[0])

    def test_accepts_elf32_vendor_with_runtime_entry_points(self) -> None:
        vendor_binary = self.work_dir / "vendor/bin/hw/audio-service"
        vendor_binary.parent.mkdir(parents=True)
        vendor_binary.write_bytes(b"\x7fELF\x01" + b"\x00" * 32)
        for relative_path, target in VALIDATOR.RUNTIME_LINKS.items():
            path = self.work_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        self.write_vndk31_contract()

        errors, count = VALIDATOR.validate_multilib_runtime(self.work_dir)

        self.assertEqual(1, count)
        self.assertEqual([], errors)

    def test_rejects_wrong_runtime_symlink_target(self) -> None:
        vendor_binary = self.work_dir / "vendor/bin/hw/audio-service"
        vendor_binary.parent.mkdir(parents=True)
        vendor_binary.write_bytes(b"\x7fELF\x01" + b"\x00" * 32)
        for relative_path, target in VALIDATOR.RUNTIME_LINKS.items():
            path = self.work_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        (self.work_dir / "system/system/bin/linker").unlink()
        (self.work_dir / "system/system/bin/linker").symlink_to(
            "/missing/runtime/linker"
        )

        errors, count = VALIDATOR.validate_multilib_runtime(self.work_dir)

        self.assertEqual(1, count)
        self.assertEqual(1, len(errors))
        self.assertIn("points to /missing/runtime/linker", errors[0])

    def test_accepts_api36_platform_graphics_core(self) -> None:
        for relative in VALIDATOR.D2S_PLATFORM_NATIVE_API36_FILES:
            write_android_note_elf(self.work_dir / relative, 36)

        errors, count = VALIDATOR.validate_d2s_platform_native_api36(
            self.work_dir
        )

        self.assertEqual(len(VALIDATOR.D2S_PLATFORM_NATIVE_API36_FILES), count)
        self.assertEqual([], errors)

    def test_rejects_android15_platform_graphics_contamination(self) -> None:
        for relative in VALIDATOR.D2S_PLATFORM_NATIVE_API36_FILES:
            write_android_note_elf(self.work_dir / relative, 36)
        contaminated = VALIDATOR.D2S_PLATFORM_NATIVE_API36_FILES[-1]
        write_android_note_elf(self.work_dir / contaminated, 35)

        errors, _ = VALIDATOR.validate_d2s_platform_native_api36(self.work_dir)

        self.assertEqual(1, len(errors))
        self.assertIn(contaminated, errors[0])
        self.assertIn("[35]", errors[0])

    def test_accepts_bounded_stagefright_video_encoder_fread(self) -> None:
        path = self.work_dir / VALIDATOR.D2S_STAGEFRIGHT_VIDEO_ENCODER_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        contents = (
            b"prefix"
            + VALIDATOR.D2S_STAGEFRIGHT_VIDEO_ENCODER_SAFE_PATTERN
            + b"suffix"
        )
        path.write_bytes(contents)

        errors, count = VALIDATOR.validate_d2s_stagefright_video_encoder(
            self.work_dir, hashlib.sha256(contents).hexdigest()
        )

        self.assertEqual(1, count)
        self.assertEqual([], errors)

    def test_rejects_unsafe_stagefright_video_encoder_fread(self) -> None:
        path = self.work_dir / VALIDATOR.D2S_STAGEFRIGHT_VIDEO_ENCODER_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        contents = VALIDATOR.D2S_STAGEFRIGHT_VIDEO_ENCODER_UNSAFE_PATTERN
        path.write_bytes(contents)

        errors, _ = VALIDATOR.validate_d2s_stagefright_video_encoder(
            self.work_dir, hashlib.sha256(contents).hexdigest()
        )

        self.assertEqual(1, len(errors))
        self.assertIn("unsafe pattern count=1", errors[0])

    def test_rejects_competing_vndk_apex(self) -> None:
        vendor_binary = self.work_dir / "vendor/bin/hw/audio-service"
        vendor_binary.parent.mkdir(parents=True)
        vendor_binary.write_bytes(b"\x7fELF\x01" + b"\x00" * 32)
        for relative_path, target in VALIDATOR.RUNTIME_LINKS.items():
            path = self.work_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(target)
        self.write_vndk31_contract()
        competing = (
            self.work_dir
            / "system/system/system_ext/apex/com.android.vndk.v35.apex"
        )
        competing.write_bytes(b"wrong-vndk")

        errors, count = VALIDATOR.validate_multilib_runtime(self.work_dir)

        self.assertEqual(1, count)
        self.assertTrue(any("assembled VNDK APEX set" in error for error in errors))

    def test_tree_comparison_detects_changed_blob_and_symlink(self) -> None:
        source = self.work_dir / "source"
        assembled = self.work_dir / "assembled"
        source.mkdir()
        assembled.mkdir()
        (source / "libexample.so").write_bytes(b"expected")
        (assembled / "libexample.so").write_bytes(b"changed")
        (source / "libc.so").symlink_to("/expected/libc.so")
        (assembled / "libc.so").symlink_to("/wrong/libc.so")

        errors = VALIDATOR._compare_tree(source, assembled, "/system/lib")

        self.assertEqual(1, len(errors))
        self.assertIn("libexample.so", errors[0])
        self.assertIn("libc.so", errors[0])

    def write_source_matched_core(self) -> Path:
        source_firmware = self.work_dir / "source_firmware"
        source_system = source_firmware / "system/system"
        assembled_system = self.work_dir / "system/system"
        for relative in VALIDATOR.SOURCE_MATCHED_CORE_FILES:
            source = source_system / relative
            assembled = assembled_system / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            assembled.parent.mkdir(parents=True, exist_ok=True)
            contents = f"source:{relative}".encode()
            source.write_bytes(contents)
            assembled.write_bytes(contents)
        return source_firmware

    def test_accepts_source_matched_boot_core(self) -> None:
        source_firmware = self.write_source_matched_core()

        errors, count = VALIDATOR.validate_source_matched_core(
            self.work_dir, source_firmware
        )

        self.assertEqual(len(VALIDATOR.SOURCE_MATCHED_CORE_FILES), count)
        self.assertEqual([], errors)

    def test_rejects_cross_version_vold_replacement(self) -> None:
        source_firmware = self.write_source_matched_core()
        (self.work_dir / "system/system/bin/vold").write_bytes(
            b"android-15-vold"
        )

        errors, _ = VALIDATOR.validate_source_matched_core(
            self.work_dir, source_firmware
        )

        self.assertEqual(1, len(errors))
        self.assertIn("boot-critical /system/bin/vold", errors[0])
        self.assertIn("source firmware", errors[0])

    def write_source_matched_first_boot_apks(self) -> Path:
        source_firmware = self.work_dir / "source_firmware"
        source_system = source_firmware / "system/system"
        assembled_system = self.work_dir / "system/system"
        for relative in VALIDATOR.SOURCE_MATCHED_FIRST_BOOT_APKS:
            source = source_system / relative
            assembled = assembled_system / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            assembled.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"complete-samsung-signed-apk")
            assembled.write_bytes(b"complete-samsung-signed-apk")
        return source_firmware

    def test_accepts_source_matched_first_boot_apk(self) -> None:
        source_firmware = self.write_source_matched_first_boot_apks()

        errors, count = VALIDATOR.validate_source_matched_first_boot_apks(
            self.work_dir, source_firmware
        )

        self.assertEqual(len(VALIDATOR.SOURCE_MATCHED_FIRST_BOOT_APKS), count)
        self.assertEqual([], errors)

    def test_rejects_stripped_first_boot_camera_apk(self) -> None:
        source_firmware = self.write_source_matched_first_boot_apks()
        camera = (
            self.work_dir
            / "system/system/priv-app/SamsungCamera/SamsungCamera.apk"
        )
        camera.write_bytes(b"stripped-module-payload")

        errors, _ = VALIDATOR.validate_source_matched_first_boot_apks(
            self.work_dir, source_firmware
        )

        self.assertEqual(1, len(errors))
        self.assertIn("source-signed /system/priv-app/SamsungCamera", errors[0])

    def write_scoped_platform_apks(self) -> tuple[Path, Path]:
        certificate_der = b"test-rom-platform-certificate-der"
        certificate = self.work_dir / "platform.x509.pem"
        certificate.write_text(
            "-----BEGIN CERTIFICATE-----\n"
            + base64.b64encode(certificate_der).decode()
            + "\n-----END CERTIFICATE-----\n",
            encoding="ascii",
        )
        for package_name, relative in VALIDATOR.D2S_SCOPED_PLATFORM_APKS.items():
            apk = self.work_dir / relative
            apk.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("AndroidManifest.xml", b"manifest")
                archive.writestr("classes.dex", b"dex\n035\0patched")
                archive.writestr(
                    "META-INF/CERT.RSA", b"pkcs7" + certificate_der
                )
        services = self.work_dir / VALIDATOR.D2S_SCOPED_SIGNATURE_SERVICE
        services.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(services, "w") as archive:
            archive.writestr(
                "classes.dex", b"dex\n035\0" + certificate_der.hex().encode()
            )
        source_firmware = self.work_dir / "scoped_source_firmware"
        camera = self.work_dir / VALIDATOR.D2S_STANDARD_CAMERA_PATH
        source_camera = (
            source_firmware
            / "system/system/priv-app/SamsungCamera/SamsungCamera.apk"
        )
        native_payloads = {
            name: f"native:{name}".encode()
            for name in VALIDATOR.D2S_STANDARD_CAMERA_NATIVE_LIBRARIES
        }
        for apk in (camera, source_camera):
            apk.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr(
                    "AndroidManifest.xml",
                    b"manifest:" + VALIDATOR.D2S_STANDARD_CAMERA_VERSION,
                )
                archive.writestr("classes.dex", b"dex\n035\0camera")
                archive.writestr("META-INF/CERT.RSA", b"same-samsung-cert")
                for name, payload in native_payloads.items():
                    archive.writestr(f"lib/arm64-v8a/{name}", payload)
        native_dir = self.work_dir / VALIDATOR.D2S_STANDARD_CAMERA_NATIVE_DIR
        native_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in native_payloads.items():
            (native_dir / name).write_bytes(payload)
        return certificate, source_firmware

    def test_accepts_scoped_platform_apks_and_signature_bridge(self) -> None:
        certificate, source_firmware = self.write_scoped_platform_apks()

        errors, count = VALIDATOR.validate_d2s_scoped_platform_apks(
            self.work_dir, certificate
        )
        camera_errors, camera_count = VALIDATOR.validate_d2s_standard_camera(
            self.work_dir, source_firmware
        )

        self.assertEqual(len(VALIDATOR.D2S_SCOPED_PLATFORM_APKS), count)
        self.assertEqual([], errors)
        self.assertEqual(1, camera_count)
        self.assertEqual([], camera_errors)

    def test_rejects_scoped_platform_apk_signed_by_wrong_key(self) -> None:
        certificate, _ = self.write_scoped_platform_apks()
        apk = self.work_dir / VALIDATOR.D2S_SCOPED_PLATFORM_APKS[
            "com.samsung.android.sead"
        ]
        with zipfile.ZipFile(apk, "a") as archive:
            archive.writestr("META-INF/CERT.RSA", b"wrong-certificate")

        errors, _ = VALIDATOR.validate_d2s_scoped_platform_apks(
            self.work_dir, certificate
        )

        self.assertTrue(any("not signed" in error for error in errors))

    def test_rejects_standard_camera_with_non_samsung_signer(self) -> None:
        _, source_firmware = self.write_scoped_platform_apks()
        camera = self.work_dir / VALIDATOR.D2S_STANDARD_CAMERA_PATH
        with zipfile.ZipFile(camera, "a") as archive:
            archive.writestr("META-INF/CERT.RSA", b"wrong-camera-certificate")

        errors, _ = VALIDATOR.validate_d2s_standard_camera(
            self.work_dir, source_firmware
        )

        self.assertTrue(any("signer does not match" in error for error in errors))

    def test_rejects_standard_camera_without_adjacent_native_library(self) -> None:
        _, source_firmware = self.write_scoped_platform_apks()
        missing = VALIDATOR.D2S_STANDARD_CAMERA_NATIVE_LIBRARIES[0]
        (self.work_dir / VALIDATOR.D2S_STANDARD_CAMERA_NATIVE_DIR / missing).unlink()

        errors, _ = VALIDATOR.validate_d2s_standard_camera(
            self.work_dir, source_firmware
        )

        self.assertTrue(
            any("adjacent native library set" in error for error in errors)
        )

    def test_rejects_modified_adjacent_camera_native_library(self) -> None:
        _, source_firmware = self.write_scoped_platform_apks()
        modified = VALIDATOR.D2S_STANDARD_CAMERA_NATIVE_LIBRARIES[0]
        (
            self.work_dir / VALIDATOR.D2S_STANDARD_CAMERA_NATIVE_DIR / modified
        ).write_bytes(b"modified-native-payload")

        errors, _ = VALIDATOR.validate_d2s_standard_camera(
            self.work_dir, source_firmware
        )

        self.assertTrue(
            any("differs from signed APK" in error for error in errors)
        )

    def write_target_fcm_contract(self) -> Path:
        target_firmware = self.work_dir / "target_firmware"
        vendor_manifest = self.work_dir / "vendor/etc/vintf/manifest.xml"
        vendor_manifest.parent.mkdir(parents=True, exist_ok=True)
        vendor_manifest.write_text(
            '<manifest version="4.0" type="device" target-level="3"/>\n',
            encoding="utf-8",
        )
        contents = (
            '<compatibility-matrix version="9.0" type="framework" level="3"/>\n'
        )
        for root in (
            self.work_dir / "system/system",
            target_firmware / "system/system",
        ):
            for level in VALIDATOR.D2S_LEGACY_FCM_LEVELS:
                matrix = root / f"etc/vintf/compatibility_matrix.{level}.xml"
                matrix.parent.mkdir(parents=True, exist_ok=True)
                matrix.write_text(
                    contents.replace('level="3"', f'level="{level}"'),
                    encoding="utf-8",
                )
        for relative in VALIDATOR.D2S_HIDL_HEALTH_FILES:
            source = target_firmware / "vendor" / relative
            assembled = self.work_dir / "vendor" / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            assembled.parent.mkdir(parents=True, exist_ok=True)
            contents = f"health:{relative}".encode()
            source.write_bytes(contents)
            assembled.write_bytes(contents)
        return target_firmware

    def test_accepts_real_target_fcm_matrix(self) -> None:
        target_firmware = self.write_target_fcm_contract()

        errors, level = VALIDATOR.validate_target_fcm_contract(
            self.work_dir, target_firmware
        )

        self.assertEqual("3", level)
        self.assertEqual([], errors)

    def test_rejects_wrong_target_fcm_matrix(self) -> None:
        target_firmware = self.write_target_fcm_contract()
        matrix = (
            self.work_dir
            / "system/system/etc/vintf/compatibility_matrix.3.xml"
        )
        matrix.write_text(
            '<compatibility-matrix version="9.0" type="framework" level="5"/>\n',
            encoding="utf-8",
        )

        errors, _ = VALIDATOR.validate_target_fcm_contract(
            self.work_dir, target_firmware
        )

        self.assertTrue(any("expected 3" in error for error in errors))
        self.assertTrue(any("hash differs" in error for error in errors))

    def test_rejects_legacy_four_field_sysfs_ueventd_rule(self) -> None:
        rules = self.work_dir / "vendor/ueventd.rc"
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(
            "/sys/kernel/clat/xlat_addrs 0660 clat clat\n",
            encoding="utf-8",
        )

        errors, count = VALIDATOR.validate_modern_ueventd_rules(self.work_dir)

        self.assertEqual(1, count)
        self.assertEqual(1, len(errors))
        self.assertIn("has 4 fields", errors[0])

    def test_accepts_android16_sysfs_ueventd_rule(self) -> None:
        rules = self.work_dir / "vendor/ueventd.rc"
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(
            "/sys/kernel/clat xlat_addrs 0660 clat clat\n",
            encoding="utf-8",
        )

        errors, count = VALIDATOR.validate_modern_ueventd_rules(self.work_dir)

        self.assertEqual(1, count)
        self.assertEqual([], errors)

    def test_checked_in_d2s_trustzone_ueventd_is_android16_compatible(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "target/d2s/patches/trustzone/vendor/ueventd.rc"
        )
        rules = self.work_dir / "vendor/ueventd.rc"
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_bytes(source.read_bytes())

        errors, count = VALIDATOR.validate_modern_ueventd_rules(self.work_dir)

        self.assertGreater(count, 0)
        self.assertEqual([], errors)

    def write_netbpfload_compat(self) -> dict[str, str]:
        compat_bin = (
            self.work_dir / "system/system/etc/netbpfload_compat/bin"
        )
        hashes: dict[str, str] = {}
        for relative in VALIDATOR.D2S_NETBPFLOAD_COMPAT_FILES:
            path = compat_bin / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            contents = f"compat:{relative}".encode()
            if relative == "netbpfload":
                contents += VALIDATOR.D2S_NETBPFLOAD_PATCH_TO
            path.write_bytes(contents)
            hashes[relative] = hashlib.sha256(contents).hexdigest()

        init_rc = self.work_dir / "system/system/etc/init/hw/init.rc"
        init_rc.parent.mkdir(parents=True, exist_ok=True)
        init_rc.write_text(
            "on load-bpf-programs\n"
            f"    {VALIDATOR.D2S_NETBPFLOAD_BIND_MOUNT}\n"
            "    exec_start bpfloader\n",
            encoding="utf-8",
        )

        contexts = self.work_dir / "configs/file_context-system"
        contexts.parent.mkdir(parents=True, exist_ok=True)
        contexts.write_text(
            "".join(
                f"/system/etc/netbpfload_compat/bin/{relative} {label}\n"
                for relative, label in (
                    VALIDATOR.D2S_NETBPFLOAD_COMPAT_LABELS.items()
                )
            ),
            encoding="utf-8",
        )
        fs_config = self.work_dir / "configs/fs_config-system"
        fs_config.write_text(
            "".join(
                "system/etc/netbpfload_compat/bin/"
                f"{relative} {uid} {gid} {mode} capabilities=0x0\n"
                for relative, (uid, gid, mode) in (
                    VALIDATOR.D2S_NETBPFLOAD_COMPAT_METADATA.items()
                )
            ),
            encoding="utf-8",
        )
        return hashes

    def test_accepts_validated_netbpfload_compatibility_layer(self) -> None:
        hashes = self.write_netbpfload_compat()

        errors, count = VALIDATOR.validate_d2s_netbpfload_compat(
            self.work_dir, hashes
        )

        self.assertEqual(len(hashes), count)
        self.assertEqual([], errors)

    def test_rejects_unpatched_netbpfload_and_late_bind_mount(self) -> None:
        hashes = self.write_netbpfload_compat()
        loader = (
            self.work_dir
            / "system/system/etc/netbpfload_compat/bin/netbpfload"
        )
        contents = loader.read_bytes().replace(
            VALIDATOR.D2S_NETBPFLOAD_PATCH_TO,
            VALIDATOR.D2S_NETBPFLOAD_PATCH_FROM,
        )
        loader.write_bytes(contents)
        hashes["netbpfload"] = hashlib.sha256(contents).hexdigest()
        init_rc = self.work_dir / "system/system/etc/init/hw/init.rc"
        init_rc.write_text(
            "on load-bpf-programs\n"
            "    exec_start bpfloader\n"
            f"    {VALIDATOR.D2S_NETBPFLOAD_BIND_MOUNT}\n",
            encoding="utf-8",
        )

        errors, _ = VALIDATOR.validate_d2s_netbpfload_compat(
            self.work_dir, hashes
        )

        self.assertTrue(any("still contains" in error for error in errors))
        self.assertTrue(any("immediately precede" in error for error in errors))

    def test_rejects_flattened_clat_metadata(self) -> None:
        hashes = self.write_netbpfload_compat()
        fs_config = self.work_dir / "configs/fs_config-system"
        fs_config.write_text(
            fs_config.read_text(encoding="utf-8").replace(
                "for-system/clatd 1029 1029 6755",
                "for-system/clatd 0 2000 755",
            ),
            encoding="utf-8",
        )

        errors, _ = VALIDATOR.validate_d2s_netbpfload_compat(
            self.work_dir, hashes
        )

        self.assertTrue(any("for-system/clatd" in error for error in errors))

    def test_accepts_early_d2s_aconfig_metadata_mount(self) -> None:
        init_rc = self.work_dir / "system/system/etc/init/aconfigd.rc"
        init_rc.parent.mkdir(parents=True, exist_ok=True)
        init_rc.write_text(
            "on early-init\n"
            "    # d2s compatibility mount must precede aconfigd commands.\n"
            f"    {VALIDATOR.D2S_ACONFIG_METADATA_MOUNT}\n"
            "    mkdir /metadata/aconfig 0775 root system\n",
            encoding="utf-8",
        )

        errors, count = VALIDATOR.validate_d2s_aconfig_compat(self.work_dir)

        self.assertEqual(1, count)
        self.assertEqual([], errors)

    def test_rejects_late_d2s_aconfig_metadata_mount(self) -> None:
        init_rc = self.work_dir / "system/system/etc/init/aconfigd.rc"
        init_rc.parent.mkdir(parents=True, exist_ok=True)
        init_rc.write_text(
            "on early-init\n"
            "    mkdir /metadata/aconfig 0775 root system\n"
            f"    {VALIDATOR.D2S_ACONFIG_METADATA_MOUNT}\n",
            encoding="utf-8",
        )

        errors, _ = VALIDATOR.validate_d2s_aconfig_compat(self.work_dir)

        self.assertTrue(any("first Aconfig" in error for error in errors))

    def test_rejects_legacy_bluetooth_apex_on_android16(self) -> None:
        legacy = (
            self.work_dir
            / VALIDATOR.D2S_FORBIDDEN_LEGACY_APEXES[0]
        )
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"android15 bluetooth")

        errors, count = VALIDATOR.validate_d2s_legacy_apex_absence(
            self.work_dir
        )

        self.assertEqual(1, count)
        self.assertTrue(any("com.android.btservices.apex" in e for e in errors))

    def test_rejects_unsupported_knox_matrix_consumer_and_requirement(self) -> None:
        fabric = (
            self.work_dir
            / VALIDATOR.D2S_UNSUPPORTED_KNOX_MATRIX_PATHS[0]
        )
        fabric.parent.mkdir(parents=True, exist_ok=True)
        fabric.write_bytes(b"fabric crypto")
        matrix = (
            self.work_dir
            / "system/system/etc/vintf/compatibility_matrix.device.xml"
        )
        matrix.parent.mkdir(parents=True, exist_ok=True)
        matrix.write_text(
            f"<compatibility-matrix>{VALIDATOR.D2S_FKEYMASTER_INTERFACE}"
            f"{VALIDATOR.D2S_KNOX_GUARD_INTERFACE}"
            "</compatibility-matrix>",
            encoding="utf-8",
        )
        kg_client = (
            self.work_dir
            / VALIDATOR.D2S_UNSUPPORTED_KNOX_GUARD_PATHS[0]
        )
        kg_client.parent.mkdir(parents=True, exist_ok=True)
        kg_client.write_bytes(b"kg client")
        for relative in VALIDATOR.D2S_KNOX_GUARD_CONFIGS:
            config = self.work_dir / relative
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(
                '<package name="com.samsung.android.kgclient"/>\n',
                encoding="utf-8",
            )

        errors, count = VALIDATOR.validate_d2s_knox_matrix_absence(
            self.work_dir
        )

        self.assertEqual(
            len(VALIDATOR.D2S_UNSUPPORTED_KNOX_MATRIX_PATHS)
            + len(VALIDATOR.D2S_UNSUPPORTED_KNOX_GUARD_PATHS)
            + len(VALIDATOR.D2S_KNOX_GUARD_CONFIGS)
            + 2,
            count,
        )
        self.assertTrue(any("fabric_crypto" in e for e in errors))
        self.assertTrue(any("Fkeymaster" in e for e in errors))
        self.assertTrue(any("KnoxGuard component" in e for e in errors))
        self.assertTrue(any("KnoxGuard remains required" in e for e in errors))
        self.assertTrue(any("stale KnoxGuard" in e for e in errors))

    def test_accepts_absent_unsupported_knox_consumers(self) -> None:
        matrix = (
            self.work_dir
            / "system/system/etc/vintf/compatibility_matrix.device.xml"
        )
        matrix.parent.mkdir(parents=True, exist_ok=True)
        matrix.write_text("<compatibility-matrix/>\n", encoding="utf-8")
        for relative in VALIDATOR.D2S_KNOX_GUARD_CONFIGS:
            config = self.work_dir / relative
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text("<config/>\n", encoding="utf-8")

        errors, _ = VALIDATOR.validate_d2s_knox_matrix_absence(self.work_dir)

        self.assertEqual([], errors)


class ApkSignatureValidationTests(unittest.TestCase):
    def test_rejects_payload_failure_even_when_certificate_is_present(self):
        result = VALIDATOR.subprocess.CompletedProcess(
            [], 1, "DOES NOT VERIFY\n", "ERROR: signed resource missing\n"
        )
        with mock.patch.object(VALIDATOR.subprocess, "run", return_value=result):
            errors = VALIDATOR.validate_apk_signature(Path("Camera.apk"), "apksigner")
        self.assertEqual(1, len(errors))
        self.assertIn("signed resource missing", errors[0])

    def test_missing_verifier_is_a_build_failure(self):
        with mock.patch.object(VALIDATOR.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertTrue(VALIDATOR.validate_apk_signature(Path("Camera.apk"), "missing"))

    def test_verifier_timeout_is_a_build_failure(self):
        with mock.patch.object(
            VALIDATOR.subprocess, "run",
            side_effect=VALIDATOR.subprocess.TimeoutExpired("apksigner", 120),
        ):
            self.assertTrue(VALIDATOR.validate_apk_signature(Path("Camera.apk"), "apksigner"))

    def test_accepts_successful_cryptographic_verification(self):
        result = VALIDATOR.subprocess.CompletedProcess([], 0, "Verifies\n", "")
        with mock.patch.object(VALIDATOR.subprocess, "run", return_value=result):
            self.assertEqual([], VALIDATOR.validate_apk_signature(Path("Camera.apk"), "apksigner"))


if __name__ == "__main__":
    unittest.main()
