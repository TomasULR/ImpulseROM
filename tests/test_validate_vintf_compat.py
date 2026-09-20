from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "internal"
    / "validate_vintf_compat.py"
)
SPEC = importlib.util.spec_from_file_location("validate_vintf_compat", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


class VintfCompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, relative: str, contents: str) -> None:
        path = self.work_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def matrix(self, level: int, version: str, hal_format: str = "hidl") -> str:
        return f'''<compatibility-matrix type="framework" level="{level}">
  <hal format="{hal_format}" optional="false">
    <name>android.hardware.audio</name><version>{version}</version>
    <interface><name>IDevicesFactory</name><instance>default</instance></interface>
  </hal>
</compatibility-matrix>'''

    def manifest(self, version: str, hal_format: str = "hidl") -> str:
        return f'''<manifest type="device" target-level="3">
  <hal format="{hal_format}">
    <name>android.hardware.audio</name><version>{version}</version>
    <interface><name>IDevicesFactory</name><instance>default</instance></interface>
  </hal>
</manifest>'''

    def test_higher_fcm_adds_alternative_version_to_required_instance(self) -> None:
        self.write("vendor/etc/vintf/manifest.xml", self.manifest("5.0"))
        self.write(
            "system/system/etc/vintf/compatibility_matrix.3.xml",
            self.matrix(3, "4.0"),
        )
        self.write(
            "system/system/etc/vintf/compatibility_matrix.4.xml",
            self.matrix(4, "5.0"),
        )

        errors, required, _, level = VALIDATOR.validate(self.work_dir)

        self.assertEqual("3", level)
        self.assertEqual(1, required)
        self.assertEqual([], errors)

    def test_missing_bridge_fcm_rejects_new_major_version(self) -> None:
        self.write("vendor/etc/vintf/manifest.xml", self.manifest("5.0"))
        self.write(
            "system/system/etc/vintf/compatibility_matrix.3.xml",
            self.matrix(3, "4.0"),
        )

        errors, _, _, _ = VALIDATOR.validate(self.work_dir)

        self.assertTrue(any("versions [4.0]" in error for error in errors))

    def test_newer_aidl_hal_does_not_satisfy_required_hidl_hal(self) -> None:
        self.write(
            "vendor/etc/vintf/manifest.xml",
            self.manifest("1", hal_format="aidl"),
        )
        self.write(
            "system/system/etc/vintf/compatibility_matrix.3.xml",
            self.matrix(3, "2.0"),
        )
        self.write(
            "system/system/etc/vintf/compatibility_matrix.7.xml",
            self.matrix(7, "1", hal_format="aidl"),
        )

        errors, _, _, _ = VALIDATOR.validate(self.work_dir)

        self.assertTrue(any("hidl android.hardware.audio" in error for error in errors))

    def test_newer_hidl_minor_satisfies_required_minor(self) -> None:
        self.write("vendor/etc/vintf/manifest.xml", self.manifest("2.1"))
        self.write(
            "system/system/etc/vintf/compatibility_matrix.3.xml",
            self.matrix(3, "2.0"),
        )

        errors, _, _, _ = VALIDATOR.validate(self.work_dir)

        self.assertEqual([], errors)

    def test_regex_instance_matches_declared_instance(self) -> None:
        self.write(
            "vendor/etc/vintf/manifest.xml",
            self.manifest("2.4").replace("default", "legacy/0"),
        )
        self.write(
            "system/system/etc/vintf/compatibility_matrix.3.xml",
            self.matrix(3, "2.4").replace(
                "<instance>default</instance>",
                "<regex-instance>[^/]+/[0-9]+</regex-instance>",
            ),
        )

        errors, _, _, _ = VALIDATOR.validate(self.work_dir)

        self.assertEqual([], errors)

    def test_parses_aidl_version_range_in_higher_matrix(self) -> None:
        self.write("vendor/etc/vintf/manifest.xml", self.manifest("2.0"))
        self.write(
            "system/system/etc/vintf/compatibility_matrix.3.xml",
            self.matrix(3, "2.0"),
        )
        self.write(
            "system/system/etc/vintf/compatibility_matrix.7.xml",
            self.matrix(7, "1-3", hal_format="aidl"),
        )

        errors, _, _, _ = VALIDATOR.validate(self.work_dir)

        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
