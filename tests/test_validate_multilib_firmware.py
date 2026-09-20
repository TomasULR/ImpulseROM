from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "internal"
    / "validate_multilib_firmware.py"
)
SPEC = importlib.util.spec_from_file_location("validate_multilib_firmware", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def write_elf(
    path: Path, bits: int, machine: int, android_api: int | None = 36
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 1 if bits == 32 else 2
    header[5] = 1  # little endian
    header[6] = 1  # ELF version
    header[16:18] = struct.pack("<H", 3)  # ET_DYN
    header[18:20] = struct.pack("<H", machine)
    contents = bytes(header)
    if android_api is not None:
        contents += (
            struct.pack("<III", 8, 4, 1)
            + b"Android\0"
            + struct.pack("<I", android_api)
        )
    path.write_bytes(contents)


def encode_manifest(name: str, version: int = 1) -> bytes:
    encoded_name = name.encode("utf-8")
    return bytes((0x0A, len(encoded_name))) + encoded_name + bytes((0x10, version))


def write_build_prop(
    path: Path,
    sdk: str = "36",
    release: str = "16",
    model: str = "SM-S711B",
    build_id: str = "S711BXXSGGZF2",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"ro.build.version.sdk={sdk}\n"
        f"ro.build.version.release={release}\n"
        f"ro.product.system.model={model}\n"
        f"ro.system.build.fingerprint=samsung/fixture/device:{release}/BUILD/"
        f"{build_id}:user/release-keys\n"
        f"ro.build.description=fixture-user {release} BUILD {build_id} "
        "release-keys\n",
        encoding="utf-8",
    )


class SyntheticFirmware:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.candidate = root / "SM-S711B_EUX"
        self.donor = root / "SM-S721B_EUX"
        self.inspections: dict[str, VALIDATOR.ApexInspection] = {}
        self.symbols: dict[Path, set[str]] = {}
        self._create_firmware_trees()
        self._create_apex_fixtures()

    def _create_firmware_trees(self) -> None:
        for firmware, marker, model in (
            (
                self.candidate,
                VALIDATOR.EXPECTED_CANDIDATE_BUILD,
                VALIDATOR.EXPECTED_CANDIDATE_MODEL,
            ),
            (
                self.donor,
                VALIDATOR.EXPECTED_DONOR_BUILD,
                VALIDATOR.EXPECTED_DONOR_MODEL,
            ),
        ):
            firmware.mkdir(parents=True)
            (firmware / ".extracted").write_text(marker, encoding="utf-8")
            write_build_prop(
                firmware / "system/system/build.prop",
                model=model,
                build_id=marker.split("/", 1)[0],
            )

        vendor_prop = self.candidate / "vendor/build.prop"
        vendor_prop.parent.mkdir(parents=True)
        vendor_prop.write_text(
            "ro.vendor.product.cpu.abilist32=armeabi-v7a,armeabi\n",
            encoding="utf-8",
        )

        system_lib = self.candidate / "system/system/lib"
        write_elf(system_lib / "libexample.so", 32, VALIDATOR.EM_ARM)
        for name in VALIDATOR.BOOTSTRAP_LIBRARIES:
            write_elf(system_lib / "bootstrap" / name, 32, VALIDATOR.EM_ARM)
        existing_elfs = 1 + len(VALIDATOR.BOOTSTRAP_LIBRARIES)
        for index in range(VALIDATOR.MIN_SYSTEM_LIB_ELF_COUNT - existing_elfs):
            write_elf(
                system_lib / "fixture" / f"libfixture{index:04d}.so",
                32,
                VALIDATOR.EM_ARM,
            )
        linker_dir = self.candidate / "system/system/bin/bootstrap"
        write_elf(linker_dir / "linker", 32, VALIDATOR.EM_ARM)
        os.symlink("linker", linker_dir / "linker_asan")

        for firmware in (self.candidate, self.donor):
            apex_dir = firmware / "system/system/apex"
            apex_dir.mkdir(parents=True)
            (apex_dir / VALIDATOR.RUNTIME_APEX).write_bytes(b"synthetic")
            (apex_dir / VALIDATOR.I18N_APEX).write_bytes(b"synthetic")
        vndk_dir = self.candidate / "system_ext/apex"
        vndk_dir.mkdir(parents=True)
        (vndk_dir / VALIDATOR.VNDK31_APEX).write_bytes(b"synthetic")

    def _inspection(
        self, label: str, apex_name: str, payload_root: Path
    ) -> VALIDATOR.ApexInspection:
        manifest = encode_manifest(apex_name)
        payload_root.mkdir(parents=True, exist_ok=True)
        (payload_root / "apex_manifest.pb").write_bytes(manifest)
        return VALIDATOR.ApexInspection(
            archive=self.root / f"{label}.apex",
            zip_ok=True,
            zip_detail="synthetic ZIP CRC passed",
            avb_ok=True,
            avb_detail="synthetic AVB passed",
            avb_key_ok=True,
            avb_key_detail="synthetic embedded key matches",
            payload_ok=True,
            payload_detail="synthetic payload",
            pubkey_sha256="same-platform-key",
            manifest=VALIDATOR.ApexManifestIdentity(apex_name, 1),
            manifest_sha256="synthetic-manifest",
            manifest_bytes=manifest,
            payload_root=payload_root,
        )

    def _create_runtime_payload(self, root: Path, include_32: bool) -> None:
        if include_32:
            for relative in VALIDATOR.RUNTIME_32_ELFS:
                write_elf(root / relative, 32, VALIDATOR.EM_ARM)
            for relative, target in VALIDATOR.RUNTIME_SYMLINKS.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(target, path)
        for relative in VALIDATOR.RUNTIME_64_ELFS:
            write_elf(root / relative, 64, VALIDATOR.EM_AARCH64)

    def _create_i18n_payload(self, root: Path, include_32: bool) -> None:
        if include_32:
            for name in VALIDATOR.I18N_LIBRARIES:
                write_elf(root / "lib" / name, 32, VALIDATOR.EM_ARM)
        for name in VALIDATOR.I18N_LIBRARIES:
            write_elf(root / "lib64" / name, 64, VALIDATOR.EM_AARCH64)
        for relative, target in VALIDATOR.I18N_SYMLINKS.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, path)
        for relative in VALIDATOR.I18N_DATA_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"non-empty synthetic i18n data")

    def _create_vndk_payload(self, root: Path) -> None:
        common_paths = [
            "libc++.so",
            "libbinder.so",
            "libutils.so",
            "libbase.so",
            "libhidlbase.so",
            "libui.so",
            "hw/android.hidl.memory@1.0-impl.so",
        ]
        common_paths.extend(
            f"libfixture{index:04d}.so"
            for index in range(131 - len(common_paths))
        )
        for directory, bits, machine in (
            ("lib", 32, VALIDATOR.EM_ARM),
            ("lib64", 64, VALIDATOR.EM_AARCH64),
        ):
            for relative in common_paths:
                write_elf(root / directory / relative, bits, machine, android_api=31)
            sanitizer_arch = "arm" if directory == "lib" else "aarch64"
            for stem in ("scudo", "scudo_minimal", "ubsan_standalone"):
                write_elf(
                    root
                    / directory
                    / f"libclang_rt.{stem}-{sanitizer_arch}-android.so",
                    bits,
                    machine,
                    android_api=29,
                )

        available_names = [Path(path).name for path in common_paths]
        entries_by_list = {
            "etc/llndk.libraries.31.txt": [
                f"libexternal{index:02d}.so" for index in range(23)
            ],
            "etc/vndkcore.libraries.31.txt": available_names[:99],
            "etc/vndkprivate.libraries.31.txt": available_names[:5],
            "etc/vndkproduct.libraries.31.txt": available_names[:73],
            "etc/vndksp.libraries.31.txt": available_names[:38],
        }
        for relative, entries in entries_by_list.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(entries) + "\n", encoding="utf-8")

    def _create_apex_fixtures(self) -> None:
        candidate_runtime_root = self.root / "payloads/candidate.runtime"
        donor_runtime_root = self.root / "payloads/donor.runtime"
        candidate_i18n_root = self.root / "payloads/candidate.i18n"
        donor_i18n_root = self.root / "payloads/donor.i18n"
        candidate_vndk_root = self.root / "payloads/candidate.vndk31"

        self._create_runtime_payload(candidate_runtime_root, include_32=True)
        self._create_runtime_payload(donor_runtime_root, include_32=False)
        self._create_i18n_payload(candidate_i18n_root, include_32=True)
        self._create_i18n_payload(donor_i18n_root, include_32=False)
        self._create_vndk_payload(candidate_vndk_root)

        self.inspections = {
            "candidate.runtime": self._inspection(
                "candidate.runtime", "com.android.runtime", candidate_runtime_root
            ),
            "donor.runtime": self._inspection(
                "donor.runtime", "com.android.runtime", donor_runtime_root
            ),
            "candidate.i18n": self._inspection(
                "candidate.i18n", "com.android.i18n", candidate_i18n_root
            ),
            "donor.i18n": self._inspection(
                "donor.i18n", "com.android.i18n", donor_i18n_root
            ),
            "candidate.vndk31": self._inspection(
                "candidate.vndk31", "com.android.vndk.v31", candidate_vndk_root
            ),
        }

        for inspection in self.inspections.values():
            if not inspection.payload_root:
                continue
            for path in inspection.payload_root.rglob("*.so"):
                if path.is_file() and not path.is_symlink():
                    self.symbols[path] = {"base_symbol"}

    def apex_factory(
        self,
        _path: Path,
        label: str,
        _work_dir: Path,
        _toolchain: VALIDATOR.Toolchain,
    ) -> VALIDATOR.ApexInspection:
        return self.inspections[label]

    def symbol_reader(
        self, path: Path, _toolchain: VALIDATOR.Toolchain
    ) -> set[str]:
        return self.symbols[path]

    def validate(self) -> VALIDATOR.ValidationReport:
        return VALIDATOR.validate_firmware(
            self.candidate,
            self.donor,
            toolchain=VALIDATOR.Toolchain(None, None, None),
            apex_factory=self.apex_factory,
            symbol_reader=self.symbol_reader,
        )


class MultilibFirmwareValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.fixture = SyntheticFirmware(Path(self.temporary_directory.name))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def check(self, report: VALIDATOR.ValidationReport, check_id: str):
        matches = [check for check in report.checks if check.check_id == check_id]
        self.assertEqual(1, len(matches), check_id)
        return matches[0]

    def test_accepts_complete_api36_multilib_firmware(self) -> None:
        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        payload = json.loads(report.to_json())
        self.assertTrue(payload["ok"])
        self.assertEqual(0, payload["summary"]["failed"])
        self.assertTrue(self.check(report, "candidate.runtime.elf32").ok)
        self.assertTrue(self.check(report, "runtime.elf64_symbol_superset").ok)

    def test_rejects_wrong_api_and_release(self) -> None:
        write_build_prop(
            self.fixture.candidate / "system/system/build.prop",
            sdk="35",
            release="15",
        )

        report = self.fixture.validate()

        check = self.check(report, "candidate.api_release")
        self.assertFalse(check.ok)
        self.assertIn("sdk=35, release=15", check.detail)

    def test_rejects_wrong_firmware_build_and_model(self) -> None:
        (self.fixture.candidate / ".extracted").write_text(
            "S711BXXUFEYG1/S711BOXMFEYG1/S711BXXUFEYG1", encoding="utf-8"
        )
        write_build_prop(
            self.fixture.candidate / "system/system/build.prop",
            model="SM-S721B",
        )

        report = self.fixture.validate()

        self.assertFalse(self.check(report, "candidate.firmware_build").ok)
        self.assertFalse(self.check(report, "candidate.firmware_model").ok)

    def test_rejects_build_prop_from_different_candidate_build(self) -> None:
        write_build_prop(
            self.fixture.candidate / "system/system/build.prop",
            build_id="S711BXXUFEYG1",
        )

        report = self.fixture.validate()

        check = self.check(report, "candidate.content_build")
        self.assertFalse(check.ok)
        self.assertIn("S711BXXSGGZF2", check.detail)

    def test_rejects_candidate_and_donor_same_tree(self) -> None:
        report = VALIDATOR.validate_firmware(
            self.fixture.candidate,
            self.fixture.candidate,
            toolchain=VALIDATOR.Toolchain(None, None, None),
            apex_factory=self.fixture.apex_factory,
            symbol_reader=self.fixture.symbol_reader,
        )

        self.assertFalse(self.check(report, "firmware.distinct").ok)

    def test_rejects_candidate_from_wrong_firmware_spec_directory(self) -> None:
        report = VALIDATOR.validate_firmware(
            self.fixture.candidate,
            self.fixture.donor,
            expected_candidate_spec="SM-S711B/INS/355195301615976",
            toolchain=VALIDATOR.Toolchain(None, None, None),
            apex_factory=self.fixture.apex_factory,
            symbol_reader=self.fixture.symbol_reader,
        )

        check = self.check(report, "candidate.firmware_spec")
        self.assertFalse(check.ok)
        self.assertIn("SM-S711B/INS", check.detail)

    def test_rejects_api35_android_notes_in_32bit_layer(self) -> None:
        write_elf(
            self.fixture.candidate / "system/system/lib/fixture/libfixture0000.so",
            32,
            VALIDATOR.EM_ARM,
            android_api=35,
        )
        write_elf(
            self.fixture.candidate / "system/system/lib/bootstrap/libc.so",
            32,
            VALIDATOR.EM_ARM,
            android_api=35,
        )
        runtime = self.fixture.inspections["candidate.runtime"]
        assert runtime.payload_root
        write_elf(
            runtime.payload_root / "lib/bionic/libc.so",
            32,
            VALIDATOR.EM_ARM,
            android_api=35,
        )

        report = self.fixture.validate()

        self.assertFalse(self.check(report, "candidate.system_lib_api_notes").ok)
        self.assertFalse(self.check(report, "candidate.bootstrap_api_notes").ok)
        self.assertFalse(self.check(report, "candidate.runtime.api36_notes").ok)

    def test_rejects_non_arm_abilist32(self) -> None:
        (self.fixture.candidate / "vendor/build.prop").write_text(
            "ro.vendor.product.cpu.abilist32=x86\n", encoding="utf-8"
        )

        report = self.fixture.validate()

        check = self.check(report, "candidate.abilist32")
        self.assertFalse(check.ok)
        self.assertIn("non-ARM", check.detail)

    def test_rejects_non_arm32_bootstrap_linker(self) -> None:
        write_elf(
            self.fixture.candidate / "system/system/bin/bootstrap/linker",
            64,
            VALIDATOR.EM_AARCH64,
        )

        report = self.fixture.validate()

        check = self.check(report, "candidate.bootstrap")
        self.assertFalse(check.ok)
        self.assertIn("ELF64 AArch64", check.detail)

    def test_rejects_missing_runtime_32bit_bionic(self) -> None:
        runtime = self.fixture.inspections["candidate.runtime"]
        assert runtime.payload_root
        (runtime.payload_root / "lib/bionic/libc.so").unlink()

        report = self.fixture.validate()

        check = self.check(report, "candidate.runtime.elf32")
        self.assertFalse(check.ok)
        self.assertIn("lib/bionic/libc.so: missing", check.detail)

    def test_rejects_missing_runtime_system_symlink(self) -> None:
        runtime = self.fixture.inspections["candidate.runtime"]
        assert runtime.payload_root
        (runtime.payload_root / "lib/libunwindstack.so").unlink()

        report = self.fixture.validate()

        check = self.check(report, "candidate.runtime.linker_symlinks")
        self.assertFalse(check.ok)
        self.assertIn("lib/libunwindstack.so", check.detail)

    def test_rejects_empty_i18n_data_and_missing_symlink(self) -> None:
        i18n = self.fixture.inspections["candidate.i18n"]
        assert i18n.payload_root
        (i18n.payload_root / "etc/icu/icudt76l.dat").write_bytes(b"")
        (i18n.payload_root / "lib64/libbase.so").unlink()

        report = self.fixture.validate()

        self.assertFalse(self.check(report, "candidate.i18n.data").ok)
        self.assertFalse(self.check(report, "candidate.i18n.symlinks").ok)

    def test_rejects_incomplete_vndk_recursive_path_set(self) -> None:
        vndk = self.fixture.inspections["candidate.vndk31"]
        assert vndk.payload_root
        (vndk.payload_root / "lib/hw/android.hidl.memory@1.0-impl.so").unlink()

        report = self.fixture.validate()

        self.assertFalse(self.check(report, "candidate.vndk31.elf32").ok)
        self.assertFalse(self.check(report, "candidate.vndk31.path_symmetry").ok)

    def test_rejects_vndk_library_list_count_regression(self) -> None:
        vndk = self.fixture.inspections["candidate.vndk31"]
        assert vndk.payload_root
        list_path = vndk.payload_root / "etc/vndkcore.libraries.31.txt"
        entries = list_path.read_text(encoding="utf-8").splitlines()
        list_path.write_text("\n".join(entries[:-1]) + "\n", encoding="utf-8")

        report = self.fixture.validate()

        check = self.check(report, "candidate.vndk31.library_lists")
        self.assertFalse(check.ok)
        self.assertIn("98 entries, expected 99", check.detail)

    def test_missing_readelf_is_reported_without_traceback(self) -> None:
        report = VALIDATOR.validate_firmware(
            self.fixture.candidate,
            self.fixture.donor,
            toolchain=VALIDATOR.Toolchain(None, None, "/missing/readelf"),
            apex_factory=self.fixture.apex_factory,
        )

        check = self.check(report, "runtime.elf64_symbol_superset")
        self.assertFalse(check.ok)
        self.assertIn("could not execute", check.detail)

    def test_rejects_zip_avb_key_and_manifest_mismatch(self) -> None:
        runtime = self.fixture.inspections["candidate.runtime"]
        runtime.zip_ok = False
        runtime.zip_detail = "CRC failed"
        runtime.avb_ok = False
        runtime.avb_detail = "hashtree mismatch"
        runtime.avb_key_ok = False
        runtime.avb_key_detail = "embedded AVB key mismatch"
        runtime.pubkey_sha256 = "unexpected-key"
        runtime.manifest = VALIDATOR.ApexManifestIdentity(
            "com.android.runtime", 2
        )

        report = self.fixture.validate()

        self.assertFalse(self.check(report, "candidate.runtime.zip_crc").ok)
        self.assertFalse(self.check(report, "candidate.runtime.avb").ok)
        self.assertFalse(self.check(report, "candidate.runtime.avb_pubkey").ok)
        self.assertFalse(self.check(report, "runtime.pubkey_match").ok)
        self.assertFalse(self.check(report, "runtime.manifest_identity_match").ok)

    def test_rejects_64bit_exported_symbol_regression(self) -> None:
        donor = self.fixture.inspections["donor.runtime"]
        assert donor.payload_root
        donor_libc = donor.payload_root / "lib64/bionic/libc.so"
        self.fixture.symbols[donor_libc] = {"base_symbol", "new_api_symbol"}

        report = self.fixture.validate()

        check = self.check(report, "runtime.elf64_symbol_superset")
        self.assertFalse(check.ok)
        self.assertIn("new_api_symbol", check.detail)


class ValidatorPrimitiveTest(unittest.TestCase):
    def test_reads_android_nt_version_note(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            elf = Path(temporary) / "libc.so"
            write_elf(elf, 32, VALIDATOR.EM_ARM, android_api=35)

            self.assertEqual({35}, VALIDATOR.read_android_api_levels(elf))

    def test_decodes_apex_manifest_identity(self) -> None:
        manifest = VALIDATOR.parse_apex_manifest(
            encode_manifest("com.android.runtime", version=7)
        )

        self.assertEqual("com.android.runtime", manifest.name)
        self.assertEqual(7, manifest.version)

    def test_detects_corrupt_zip_member_crc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "fixture.apex"
            marker = b"UNIQUE_CRC_PAYLOAD_0123456789"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("apex_payload.img", marker)
            ok, _detail = VALIDATOR.verify_zip_crc(archive_path)
            self.assertTrue(ok)

            contents = bytearray(archive_path.read_bytes())
            offset = contents.index(marker)
            contents[offset] ^= 0xFF
            archive_path.write_bytes(contents)

            ok, detail = VALIDATOR.verify_zip_crc(archive_path)
            self.assertFalse(ok)
            self.assertIn("CRC failed", detail)

    def test_rejects_duplicate_critical_apex_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "duplicate.apex"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(archive_path, "w") as archive:
                    archive.writestr("apex_payload.img", b"payload")
                    archive.writestr("apex_pubkey", b"first")
                    archive.writestr("apex_pubkey", b"second")
                    archive.writestr(
                        "apex_manifest.pb", encode_manifest("com.android.runtime")
                    )

            ok, detail = VALIDATOR.verify_zip_crc(archive_path)

            self.assertFalse(ok)
            self.assertIn("duplicate critical APEX members", detail)
            self.assertIn("apex_pubkey", detail)

    def test_parses_defined_dynamic_symbols(self) -> None:
        output = """
Symbol table '.dynsym' contains 4 entries:
   Num:    Value          Size Type    Bind   Vis      Ndx Name
     1: 0000000000001000    16 FUNC    GLOBAL DEFAULT   13 exported@@LIBC (2)
     2: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND missing
     3: 0000000000001010     8 FUNC    WEAK   DEFAULT   13 weak_symbol
"""

        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, stdout=output, stderr="")

        toolchain = VALIDATOR.Toolchain(None, None, "readelf", runner=runner)
        symbols = VALIDATOR.exported_symbols(Path("synthetic.so"), toolchain)

        self.assertEqual({"exported@@LIBC", "weak_symbol"}, symbols)

    def test_apex_inspector_matches_embedded_avb_key_without_key_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "fixture.apex"
            pubkey = b"synthetic-avb-public-key"
            manifest = encode_manifest("com.android.runtime")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("apex_payload.img", b"synthetic-payload")
                archive.writestr("apex_pubkey", pubkey)
                archive.writestr("apex_manifest.pb", manifest)

            commands: list[list[str]] = []

            def runner(args, **_kwargs):
                command = list(args)
                commands.append(command)
                if "verify_image" in command:
                    return subprocess.CompletedProcess(command, 0, "verified", "")
                if "info_image" in command:
                    digest = hashlib.sha1(pubkey).hexdigest()
                    return subprocess.CompletedProcess(
                        command, 0, f"Public key (sha1): {digest}\n", ""
                    )
                if command[0] == "debugfs":
                    destination = Path(command[2].removeprefix("rdump / "))
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / "apex_manifest.pb").write_bytes(manifest)
                    return subprocess.CompletedProcess(command, 0, "", "")
                raise AssertionError(command)

            inspection = VALIDATOR.inspect_apex(
                archive_path,
                "fixture",
                root / "work",
                VALIDATOR.Toolchain("avbtool", "debugfs", None, runner=runner),
            )

            self.assertTrue(inspection.zip_ok)
            self.assertTrue(inspection.avb_ok)
            self.assertTrue(inspection.avb_key_ok)
            self.assertTrue(inspection.payload_ok)
            self.assertFalse(any("--key" in command for command in commands))

    def test_apex_inspector_rejects_embedded_avb_key_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "fixture.apex"
            manifest = encode_manifest("com.android.runtime")
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("apex_payload.img", b"synthetic-payload")
                archive.writestr("apex_pubkey", b"outer-key")
                archive.writestr("apex_manifest.pb", manifest)

            def runner(args, **_kwargs):
                command = list(args)
                if "verify_image" in command:
                    return subprocess.CompletedProcess(command, 0, "verified", "")
                if "info_image" in command:
                    return subprocess.CompletedProcess(
                        command, 0, f"Public key (sha1): {'0' * 40}\n", ""
                    )
                if command[0] == "debugfs":
                    destination = Path(command[2].removeprefix("rdump / "))
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / "apex_manifest.pb").write_bytes(manifest)
                    return subprocess.CompletedProcess(command, 0, "", "")
                raise AssertionError(command)

            inspection = VALIDATOR.inspect_apex(
                archive_path,
                "fixture",
                root / "work",
                VALIDATOR.Toolchain("avbtool", "debugfs", None, runner=runner),
            )

            self.assertTrue(inspection.avb_ok)
            self.assertFalse(inspection.avb_key_ok)
            self.assertIn("payload key sha1=000000", inspection.avb_key_detail)


if __name__ == "__main__":
    unittest.main()
