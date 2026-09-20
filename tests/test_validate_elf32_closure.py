from __future__ import annotations

import hashlib
import importlib.util
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "internal"
    / "validate_elf32_closure.py"
)
SPEC = importlib.util.spec_from_file_location("validate_elf32_closure", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def write_elf32(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 1
    header[5] = 1
    header[6] = 1
    header[16:18] = struct.pack("<H", 3)
    header[18:20] = struct.pack("<H", VALIDATOR.EM_ARM)
    path.write_bytes(header)


def write_elf64(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = 2
    header[5] = 1
    header[6] = 1
    header[16:18] = struct.pack("<H", 3)
    header[18:20] = struct.pack("<H", VALIDATOR.EM_AARCH64)
    path.write_bytes(header)


def apex_manifest(name: str, version: int = 1) -> bytes:
    encoded = name.encode("utf-8")
    if len(encoded) >= 128 or not 0 <= version < 128:
        raise ValueError("test helper only supports one-byte protobuf varints")
    return b"\x0a" + bytes((len(encoded),)) + encoded + b"\x10" + bytes((version,))


class FakeElfToolchain:
    def __init__(self, bitness: int = 32) -> None:
        self.bitness = bitness
        self.interpreters: dict[Path, str | None] = {}
        self.dependencies: dict[Path, tuple[str, ...]] = {}
        self.imports: dict[Path, tuple[VALIDATOR.VersionedImport, ...]] = {}
        self.unversioned_imports: dict[Path, tuple[str, ...]] = {}
        self.symbols: dict[Path, VALIDATOR.SymbolTable] = {}

    def availability_errors(self) -> list[str]:
        return []

    @staticmethod
    def is_elf32_arm(path: Path) -> bool:
        return VALIDATOR.ElfToolchain.is_elf32_arm(path)

    def is_target_elf(self, path: Path) -> bool:
        if self.bitness == 64:
            return VALIDATOR.ElfToolchain.is_elf64_aarch64(path)
        return self.is_elf32_arm(path)

    def interpreter(self, path: Path) -> str | None:
        return self.interpreters.get(path)

    def needed(self, path: Path) -> tuple[str, ...]:
        return self.dependencies.get(path, ())

    def versioned_imports(
        self, path: Path
    ) -> tuple[VALIDATOR.VersionedImport, ...]:
        return self.imports.get(path, ())

    def defined_symbols(self, path: Path) -> VALIDATOR.SymbolTable:
        return self.symbols.get(
            path, VALIDATOR.SymbolTable(frozenset(), frozenset())
        )

    def strong_unversioned_imports(self, path: Path) -> tuple[str, ...]:
        return self.unversioned_imports.get(path, ())


class SyntheticClosureFixture:
    def __init__(self, root: Path, bitness: int = 32) -> None:
        self.root = root
        self.work = root / "work"
        self.payloads = root / "payloads"
        self.bitness = bitness
        self.lib_dir = "lib64" if bitness == 64 else "lib"
        self.linker_name = "linker64" if bitness == 64 else "linker"
        self.write_elf = write_elf64 if bitness == 64 else write_elf32
        self.toolchain = FakeElfToolchain(bitness)
        self.service = self.work / "vendor/bin/hw/legacy-service"
        self.vendor_library = (
            self.work / "vendor" / self.lib_dir / "libvendor.so"
        )
        self.system_library = (
            self.work / "system/system" / self.lib_dir / "liblog.so"
        )
        self.vndk_library = (
            self.payloads / "vndk31" / self.lib_dir / "libbase.so"
        )
        self.runtime_libc = (
            self.payloads / "runtime" / self.lib_dir / "bionic/libc.so"
        )
        self._create_work_dir()
        self._create_payloads()
        self._configure_elf_graph()

    def _create_work_dir(self) -> None:
        (self.work / "vendor").mkdir(parents=True)
        (self.work / "vendor/build.prop").write_text(
            "ro.vndk.version=31\n", encoding="utf-8"
        )
        system_manifest = (
            self.work
            / "system/system/system_ext/etc/vintf/manifest.xml"
        )
        system_manifest.parent.mkdir(parents=True)
        system_manifest.write_text(
            "<manifest><vendor-ndk><version>31</version>"
            "</vendor-ndk></manifest>\n",
            encoding="utf-8",
        )
        vendor_matrix = self.work / "vendor/etc/vintf/compatibility_matrix.xml"
        vendor_matrix.parent.mkdir(parents=True)
        vendor_matrix.write_text(
            "<compatibility-matrix><vendor-ndk><version>31</version>"
            "</vendor-ndk></compatibility-matrix>\n",
            encoding="utf-8",
        )
        system_etc = self.work / "system/system/etc"
        system_etc.mkdir(parents=True)
        (system_etc / "linker.config.pb").write_bytes(b"\x1a\x09liblog.so")

        apex_dir = self.work / "system/system/apex"
        apex_dir.mkdir(parents=True)
        (apex_dir / VALIDATOR.RUNTIME_APEX).write_bytes(b"runtime-apex")
        (apex_dir / VALIDATOR.I18N_APEX).write_bytes(b"i18n-apex")
        vndk_dir = self.work / "system/system/system_ext/apex"
        vndk_dir.mkdir(parents=True)
        (vndk_dir / VALIDATOR.VNDK31_APEX).write_bytes(b"vndk-apex")

        linker = self.work / "system/system/bin" / self.linker_name
        linker.parent.mkdir(parents=True)
        linker.symlink_to(
            f"/apex/com.android.runtime/bin/{self.linker_name}"
        )
        for path in (self.service, self.vendor_library, self.system_library):
            self.write_elf(path)

    def _create_payloads(self) -> None:
        runtime = self.payloads / "runtime"
        self.write_elf(runtime / "bin" / self.linker_name)
        for name in ("libc.so", "libdl.so", "libdl_android.so", "libm.so"):
            self.write_elf(runtime / self.lib_dir / "bionic" / name)
        self.write_elf(
            self.payloads / "i18n" / self.lib_dir / "libicuuc.so"
        )

        vndk = self.payloads / "vndk31"
        self.write_elf(self.vndk_library)
        filler_names: list[str] = []
        for index in range(VALIDATOR.EXPECTED_VNDK31_ELF32 - 1):
            name = f"libfixture{index:03d}.so"
            filler_names.append(name)
            self.write_elf(vndk / self.lib_dir / name)
        etc = vndk / "etc"
        etc.mkdir(parents=True)
        (etc / "llndk.libraries.31.txt").write_text(
            "liblog.so\n", encoding="utf-8"
        )
        (etc / "vndkcore.libraries.31.txt").write_text(
            "libbase.so\n" + "\n".join(filler_names) + "\n",
            encoding="utf-8",
        )
        (etc / "vndkprivate.libraries.31.txt").write_text(
            "libprivate-vndk.so\n", encoding="utf-8"
        )
        (etc / "vndksp.libraries.31.txt").write_text(
            "libbase.so\n", encoding="utf-8"
        )

    def _configure_elf_graph(self) -> None:
        self.toolchain.interpreters[self.service] = (
            f"/system/bin/{self.linker_name}"
        )
        self.toolchain.dependencies[self.service] = (
            "libvendor.so",
            "libbase.so",
            "libc.so",
            "liblog.so",
        )
        self.toolchain.dependencies[self.vendor_library] = ("libc.so",)
        self.toolchain.dependencies[self.vndk_library] = ("libc.so",)
        self.toolchain.dependencies[self.system_library] = ("libc.so",)

    def apex_inspector(
        self, archive: Path, label: str, _temporary: Path
    ) -> VALIDATOR.ApexPayload:
        names = {
            "runtime": "com.android.runtime",
            "i18n": "com.android.i18n",
            "vndk31": "com.android.vndk.v31",
        }
        return VALIDATOR.ApexPayload(
            archive=archive,
            manifest_name=names[label],
            payload_root=self.payloads / label,
            sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )

    def validate(
        self,
        provider: Path | None = None,
        vendor_dlopen_roots: tuple[Path, ...] = (),
    ) -> VALIDATOR.ValidationReport:
        return VALIDATOR.validate_work_dir(
            self.work,
            multilib_firmware_dir=provider,
            vendor_dlopen_roots=vendor_dlopen_roots,
            toolchain=self.toolchain,
            apex_inspector=self.apex_inspector,
        )


class ValidatorPrimitiveTest(unittest.TestCase):
    def test_distinguishes_arm32_and_aarch64_elf_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arm = root / "arm.so"
            arm64 = root / "arm64.so"
            write_elf32(arm)
            write_elf64(arm64)

            self.assertTrue(VALIDATOR.ElfToolchain.is_elf32_arm(arm))
            self.assertFalse(VALIDATOR.ElfToolchain.is_elf64_aarch64(arm))
            self.assertTrue(VALIDATOR.ElfToolchain.is_elf64_aarch64(arm64))
            self.assertFalse(VALIDATOR.ElfToolchain.is_elf32_arm(arm64))

    def test_apex_manifest_requires_version_and_valid_trailing_data(self) -> None:
        valid = apex_manifest("com.android.runtime")

        self.assertEqual(
            "com.android.runtime", VALIDATOR.parse_apex_manifest_name(valid)
        )
        with self.assertRaises(VALIDATOR.ValidationError):
            VALIDATOR.parse_apex_manifest_name(valid + b"\x80")
        with self.assertRaises(VALIDATOR.ValidationError):
            VALIDATOR.parse_apex_manifest_name(valid[:-2])

    def test_apex_inspector_rejects_outer_payload_key_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.apex"
            with zipfile.ZipFile(archive, "w") as apex:
                apex.writestr("apex_payload.img", b"payload")
                apex.writestr("apex_pubkey", b"outer-key")
                apex.writestr(
                    "apex_manifest.pb", apex_manifest("com.android.runtime")
                )
            fake_avbtool = root / "avbtool"
            fake_avbtool.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = info_image ]; then\n"
                "  echo 'Public key (sha1): " + "0" * 40 + "'\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_avbtool.chmod(0o755)

            inspected = VALIDATOR.inspect_apex(
                archive,
                "runtime",
                root / "inspect",
                avbtool=str(fake_avbtool),
                debugfs="/not/reached",
            )

            self.assertIsNone(inspected.payload_root)
            self.assertIn("key mismatch", inspected.error or "")


class Elf32ClosureValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = SyntheticClosureFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def check(
        self, report: VALIDATOR.ValidationReport, check_id: str
    ) -> VALIDATOR.CheckResult:
        return next(check for check in report.checks if check.check_id == check_id)

    def test_accepts_namespace_aware_complete_closure(self) -> None:
        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(1, len(report.roots))
        root = report.roots[0]
        self.assertEqual([], root.missing)
        self.assertEqual([], root.namespace_blocked)
        self.assertEqual(5, root.loaded_elfs)

    def test_accepts_aarch64_namespace_aware_complete_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticClosureFixture(Path(temporary), bitness=64)
            report = fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(64, report.bitness)
        self.assertEqual(64, report.to_dict()["elf_bitness"])
        self.assertTrue(
            next(
                check
                for check in report.checks
                if check.check_id == "vendor.elf64_interpreters"
            ).ok
        )
        self.assertIn("AArch64 ELF64 linker", report.roots[0].interpreter_detail)

    def test_reports_true_missing_dependency(self) -> None:
        self.fixture.toolchain.dependencies[self.fixture.service] += (
            "libabsent.so",
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertEqual(
            ["libabsent.so"],
            [issue.needed for issue in report.roots[0].missing],
        )
        self.assertEqual([], report.roots[0].namespace_blocked)

    def test_reports_provider_in_inaccessible_system_namespace(self) -> None:
        private = self.fixture.work / "system/system/lib/libprivate.so"
        write_elf32(private)
        linker_config = (
            self.fixture.work / "system/system/etc/linker.config.pb"
        )
        linker_config.write_bytes(
            linker_config.read_bytes() + b"\x1a\x0dlibprivate.so"
        )
        self.fixture.toolchain.dependencies[self.fixture.service] += (
            "libprivate.so",
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        blocked = report.roots[0].namespace_blocked
        self.assertEqual(["libprivate.so"], [issue.needed for issue in blocked])
        self.assertIn("system:/system/lib", blocked[0].candidates[0])

    def test_nested_provider_is_blocked_instead_of_missing(self) -> None:
        nested = (
            self.fixture.work
            / "system/system/lib/private/libnested-provider.so"
        )
        write_elf32(nested)
        self.fixture.toolchain.dependencies[self.fixture.service] += (
            "libnested-provider.so",
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertEqual([], report.roots[0].missing)
        blocked = report.roots[0].namespace_blocked
        self.assertEqual(
            ["libnested-provider.so"], [issue.needed for issue in blocked]
        )
        self.assertIn("/system/lib/private/", blocked[0].candidates[0])

    def test_reports_private_runtime_library_as_namespace_blocked(self) -> None:
        private = self.fixture.payloads / "runtime/lib/libc_malloc_debug.so"
        write_elf32(private)
        self.fixture.toolchain.dependencies[self.fixture.service] += (
            "libc_malloc_debug.so",
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        blocked = report.roots[0].namespace_blocked
        self.assertEqual(
            ["libc_malloc_debug.so"], [issue.needed for issue in blocked]
        )
        self.assertIn("runtime:", blocked[0].candidates[0])

    def test_duplicate_route_is_warning_and_vendor_local_wins(self) -> None:
        vendor_duplicate = self.fixture.work / "vendor/lib/libbase.so"
        write_elf32(vendor_duplicate)

        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        duplicate = next(
            item
            for item in report.roots[0].duplicate_routes
            if item.needed == "libbase.so"
        )
        self.assertTrue(duplicate.selected.startswith("vendor:"))
        self.assertTrue(any(item.startswith("vndk:") for item in duplicate.candidates))

    def test_android_absolute_vendor_symlink_is_a_real_provider(self) -> None:
        mali = self.fixture.work / "vendor/lib/egl/libGLES_mali.so"
        write_elf32(mali)
        opencl = self.fixture.work / "vendor/lib/libOpenCL.so"
        opencl.symlink_to("/vendor/lib/egl/libGLES_mali.so")
        self.fixture.toolchain.dependencies[self.fixture.service] += (
            "libOpenCL.so",
        )

        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual([], report.roots[0].missing)
        self.assertEqual(6, report.roots[0].loaded_elfs)

    def test_vendor_vndk_override_keeps_vndk_namespace(self) -> None:
        override = self.fixture.work / "vendor/lib/vndk/libbase.so"
        write_elf32(override)

        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        duplicate = next(
            item
            for item in report.roots[0].duplicate_routes
            if item.needed == "libbase.so"
        )
        self.assertEqual(
            "vndk:/vendor/lib/vndk/libbase.so", duplicate.selected
        )

    def test_unexported_vendor_vndk_override_is_namespace_blocked(self) -> None:
        private = self.fixture.work / "vendor/lib/vndk/libnotexported.so"
        write_elf32(private)
        self.fixture.toolchain.dependencies[self.fixture.service] += (
            "libnotexported.so",
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        blocked = report.roots[0].namespace_blocked
        self.assertEqual(["libnotexported.so"], [item.needed for item in blocked])
        self.assertIn("vndk:/vendor/lib/vndk", blocked[0].candidates[0])

    def test_vndk_extension_can_resolve_vendor_dependency(self) -> None:
        self.fixture.toolchain.dependencies[self.fixture.vndk_library] = (
            "libvendor.so",
            "libc.so",
        )

        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual([], report.roots[0].namespace_blocked)

    def test_unversioned_base_symbol_is_warning(self) -> None:
        self.fixture.toolchain.imports[self.fixture.service] = (
            VALIDATOR.VersionedImport("compat_symbol", "OLD_1", "libbase.so"),
        )
        self.fixture.toolchain.symbols[self.fixture.vndk_library] = (
            VALIDATOR.SymbolTable(
                frozenset({"compat_symbol"}), frozenset()
            )
        )

        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(1, len(report.roots[0].version_fallbacks))
        self.assertEqual([], report.roots[0].version_missing)

    def test_exact_version_may_be_supplied_by_another_loaded_library(self) -> None:
        self.fixture.toolchain.imports[self.fixture.service] = (
            VALIDATOR.VersionedImport(
                "interposed_symbol", "LIBBINDER", "libbase.so"
            ),
        )
        self.fixture.toolchain.symbols[self.fixture.vendor_library] = (
            VALIDATOR.SymbolTable(
                frozenset({"interposed_symbol"}),
                frozenset({("interposed_symbol", "LIBBINDER")}),
            )
        )

        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(1, report.roots[0].exact_versioned_imports)
        self.assertEqual([], report.roots[0].version_missing)

    def test_different_symbol_version_is_not_a_base_fallback(self) -> None:
        self.fixture.toolchain.imports[self.fixture.service] = (
            VALIDATOR.VersionedImport("versioned_symbol", "OLD_1", "libbase.so"),
        )
        self.fixture.toolchain.symbols[self.fixture.vndk_library] = (
            VALIDATOR.SymbolTable(
                frozenset(), frozenset({("versioned_symbol", "NEW_1")})
            )
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertEqual([], report.roots[0].version_fallbacks)
        self.assertEqual(1, len(report.roots[0].version_missing))

    def test_missing_versioned_and_base_symbol_is_hard_failure(self) -> None:
        self.fixture.toolchain.imports[self.fixture.service] = (
            VALIDATOR.VersionedImport("missing_symbol", "OLD_1", "libbase.so"),
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertEqual(1, len(report.roots[0].version_missing))
        self.assertEqual("missing_symbol", report.roots[0].version_missing[0].symbol)

    def test_missing_strong_unversioned_symbol_is_hard_failure(self) -> None:
        self.fixture.toolchain.unversioned_imports[self.fixture.service] = (
            "missing_unversioned_symbol",
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertEqual(1, len(report.roots[0].unversioned_missing))
        self.assertEqual(
            "missing_unversioned_symbol",
            report.roots[0].unversioned_missing[0].symbol,
        )

    def test_loaded_default_symbol_satisfies_unversioned_import(self) -> None:
        self.fixture.toolchain.unversioned_imports[self.fixture.service] = (
            "default_export",
        )
        self.fixture.toolchain.symbols[self.fixture.vndk_library] = (
            VALIDATOR.SymbolTable(
                frozenset({"default_export"}),
                frozenset({("default_export", "VNDK_1")}),
            )
        )

        report = self.fixture.validate()

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(1, report.roots[0].resolved_unversioned_imports)
        self.assertEqual([], report.roots[0].unversioned_missing)

    def test_explicit_vendor_dlopen_root_is_audited(self) -> None:
        dynamic_root = self.fixture.work / "vendor/lib/hw/libdynamic.so"
        write_elf32(dynamic_root)
        self.fixture.toolchain.dependencies[dynamic_root] = ("libvendor.so",)

        report = self.fixture.validate(
            vendor_dlopen_roots=(Path("vendor/lib/hw/libdynamic.so"),)
        )

        self.assertTrue(report.ok, report.to_text())
        self.assertEqual(2, len(report.roots))
        self.assertEqual(
            "vendor/lib/hw/libdynamic.so", report.roots[1].executable
        )

    def test_explicit_dlopen_root_must_stay_inside_vendor(self) -> None:
        report = self.fixture.validate(
            vendor_dlopen_roots=(Path("system/system/lib/liblog.so"),)
        )

        self.assertFalse(report.ok)
        self.assertFalse(self.check(report, "vendor.dlopen_root.1").ok)

    def test_rejects_wrong_vndk_property_and_competing_apex(self) -> None:
        (self.fixture.work / "vendor/build.prop").write_text(
            "ro.vndk.version=34\n", encoding="utf-8"
        )
        competing = (
            self.fixture.work
            / "system/system/system_ext/apex/com.android.vndk.v34.apex"
        )
        competing.write_bytes(b"competing")

        report = self.fixture.validate()

        self.assertFalse(self.check(report, "vendor.ro_vndk_version").ok)
        self.assertFalse(self.check(report, "apex.vndk31_unique").ok)
        self.assertEqual([], report.roots)

    def test_rejects_competing_vintf_vendor_ndk_version(self) -> None:
        manifest = (
            self.fixture.work
            / "system/system/system_ext/etc/vintf/manifest.xml"
        )
        manifest.write_text(
            "<manifest><vendor-ndk><version>31</version><version>34</version>"
            "</vendor-ndk></manifest>\n",
            encoding="utf-8",
        )

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertFalse(
            self.check(report, "vintf.system_ext_vendor_ndk31").ok
        )

    def test_rejects_empty_system_linker_config(self) -> None:
        linker_config = (
            self.fixture.work / "system/system/etc/linker.config.pb"
        )
        linker_config.write_bytes(b"")

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertFalse(
            self.check(report, "namespace.system_linker_config").ok
        )

    def test_rejects_wrong_runtime_linker_symlink(self) -> None:
        linker = self.fixture.work / "system/system/bin/linker"
        linker.unlink()
        linker.symlink_to("/system/bin/linker64")

        report = self.fixture.validate()

        self.assertFalse(report.ok)
        self.assertFalse(report.roots[0].interpreter_ok)
        self.assertIn("points to", report.roots[0].interpreter_detail)

    def test_provider_hash_mismatch_is_hard_failure(self) -> None:
        provider = self.fixture.root / "provider"
        provider_runtime = provider / "system/system/apex"
        provider_runtime.mkdir(parents=True)
        work_runtime = self.fixture.work / "system/system/apex"
        for name in (VALIDATOR.RUNTIME_APEX, VALIDATOR.I18N_APEX):
            (provider_runtime / name).write_bytes((work_runtime / name).read_bytes())
        provider_vndk = provider / "system/system/system_ext/apex"
        provider_vndk.mkdir(parents=True)
        (provider_vndk / VALIDATOR.VNDK31_APEX).write_bytes(b"different")

        report = self.fixture.validate(provider)

        self.assertFalse(report.ok)
        self.assertTrue(self.check(report, "provider_hash.runtime").ok)
        self.assertTrue(self.check(report, "provider_hash.i18n").ok)
        self.assertFalse(self.check(report, "provider_hash.vndk31").ok)

    def test_json_keeps_issue_classes_separate(self) -> None:
        private = self.fixture.work / "system/system/lib/libprivate.so"
        write_elf32(private)
        self.fixture.toolchain.dependencies[self.fixture.service] += (
            "libmissing.so",
            "libprivate.so",
        )

        payload = self.fixture.validate().to_dict()

        summary = payload["summary"]
        self.assertEqual(1, summary["missing"])
        self.assertEqual(1, summary["namespace_blocked"])
        self.assertIn("duplicate_routes", summary)
        self.assertIn("version_fallbacks", summary)
        self.assertIn("unversioned_missing", summary)


if __name__ == "__main__":
    unittest.main()
