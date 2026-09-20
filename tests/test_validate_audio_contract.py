from __future__ import annotations

import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "internal"
    / "validate_audio_contract.py"
)
SPEC = importlib.util.spec_from_file_location("validate_audio_contract", SCRIPT)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def manifest(version: str = "6.0") -> str:
    return f'''<manifest version="4.0" type="device" target-level="3">
  <hal format="hidl">
    <name>android.hardware.audio</name>
    <transport>hwbinder</transport>
    <version>{version}</version>
    <interface><name>IDevicesFactory</name><instance>default</instance></interface>
    <fqname>@{version}::IDevicesFactory/default</fqname>
  </hal>
  <hal format="hidl">
    <name>android.hardware.audio.effect</name>
    <transport>hwbinder</transport>
    <version>{version}</version>
    <interface><name>IEffectsFactory</name><instance>default</instance></interface>
    <fqname>@{version}::IEffectsFactory/default</fqname>
  </hal>
</manifest>'''


def write_elf(path: Path, elf_class: int, machine: int, suffix: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(64)
    header[:4] = b"\x7fELF"
    header[4] = elf_class
    header[5] = 1
    header[6] = 1
    header[16:18] = struct.pack("<H", 3)
    header[18:20] = struct.pack("<H", machine)
    path.write_bytes(bytes(header) + suffix)


class AudioManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "manifest.xml"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_exact_hidl_6_default_instances(self) -> None:
        self.path.write_text(manifest(), encoding="utf-8")

        self.assertEqual([], VALIDATOR.manifest_audio_errors(self.path))

    def test_rejects_legacy_hidl_5_contract(self) -> None:
        self.path.write_text(manifest("5.0"), encoding="utf-8")

        errors = VALIDATOR.manifest_audio_errors(self.path)

        self.assertEqual(4, len(errors))
        self.assertTrue(all("expected" in error for error in errors))

    def test_rejects_duplicate_audio_declaration(self) -> None:
        duplicated = manifest().replace(
            "</manifest>",
            "<hal format=\"hidl\"><name>android.hardware.audio</name>"
            "<version>6.0</version></hal></manifest>",
        )
        self.path.write_text(duplicated, encoding="utf-8")

        errors = VALIDATOR.manifest_audio_errors(self.path)

        self.assertTrue(any("declarations=2" in error for error in errors))


class AudioFileContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_hash_contract_detects_drift(self) -> None:
        path = self.root / "audio.bin"
        path.write_bytes(b"known")
        expected = {"audio.bin": VALIDATOR._sha256(path)}

        errors, matched = VALIDATOR._hash_contract(self.root, expected)
        path.write_bytes(b"changed")
        drift, drift_matched = VALIDATOR._hash_contract(self.root, expected)

        self.assertEqual(([], 1), (errors, matched))
        self.assertEqual(0, drift_matched)
        self.assertIn("sha256=", drift[0])

    def test_provider_contract_requires_byte_identity(self) -> None:
        work = self.root / "work"
        provider = self.root / "provider"
        for root in (work, provider):
            (root / "lib").mkdir(parents=True)
            (root / "lib/audio.so").write_bytes(b"same")

        errors, matched = VALIDATOR._provider_contract(
            work, provider, ("lib/audio.so",)
        )
        (work / "lib/audio.so").write_bytes(b"different")
        drift, _ = VALIDATOR._provider_contract(
            work, provider, ("lib/audio.so",)
        )

        self.assertEqual(([], 1), (errors, matched))
        self.assertEqual(["provider mismatch for lib/audio.so"], drift)

    def test_service_must_advertise_both_hidl_6_factories(self) -> None:
        service = self.root / "vendor/bin/hw/android.hardware.audio.service"
        write_elf(
            service,
            1,
            VALIDATOR.EM_ARM,
            b"android.hardware.audio@6.0::IDevicesFactory\0"
            b"android.hardware.audio.effect@6.0::IEffectsFactory\0",
        )

        self.assertEqual([], VALIDATOR._validate_service(self.root))
        service.write_bytes(service.read_bytes().replace(b"IEffectsFactory", b"MissingFactory"))
        self.assertTrue(VALIDATOR._validate_service(self.root))


class AudioXmlContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, contents: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def test_policy_xinclude_closure(self) -> None:
        self.write(
            "vendor/etc/audio_policy_configuration.xml",
            '''<audioPolicyConfiguration xmlns:xi="http://www.w3.org/2001/XInclude">
<xi:include href="audio_policy_volumes.xml"/>
</audioPolicyConfiguration>''',
        )
        self.write("vendor/etc/audio_policy_volumes.xml", "<volumes/>")

        errors, count = VALIDATOR._validate_policy_xml(self.root)

        self.assertEqual([], errors)
        self.assertEqual(2, count)

    def test_policy_rejects_missing_include(self) -> None:
        self.write(
            "vendor/etc/audio_policy_configuration.xml",
            '''<audioPolicyConfiguration xmlns:xi="http://www.w3.org/2001/XInclude">
<xi:include href="missing.xml"/>
</audioPolicyConfiguration>''',
        )

        errors, _ = VALIDATOR._validate_policy_xml(self.root)

        self.assertEqual(["missing policy include missing.xml"], errors)

    def test_effect_xml_allows_only_known_stock_optional_libraries(self) -> None:
        self.write(
            "vendor/etc/audio_effects_sec.xml",
            '''<audio_effects_conf>
<libraries>
  <library name="good" path="libgood.so"/>
  <library name="optional" path="libgearvr.so"/>
</libraries>
<effects>
  <effect name="good_effect" library="good" uuid="one"/>
  <effect name="optional_effect" library="optional" uuid="two"/>
</effects>
</audio_effects_conf>''',
        )
        good = self.root / "vendor/lib/soundfx/libgood.so"
        good.parent.mkdir(parents=True)
        good.write_bytes(b"effect")

        errors, warnings, parsed = VALIDATOR._validate_effect_xmls(self.root)

        self.assertEqual([], errors)
        self.assertEqual(1, parsed)
        self.assertEqual(1, len(warnings))
        self.assertIn("known stock-optional", warnings[0])

    def test_effect_xml_rejects_unexpected_missing_library(self) -> None:
        self.write(
            "vendor/etc/audio_effects.xml",
            '''<audio_effects_conf>
<libraries><library name="bad" path="libunexpected.so"/></libraries>
<effects><effect name="bad_effect" library="bad" uuid="one"/></effects>
</audio_effects_conf>''',
        )

        errors, _, _ = VALIDATOR._validate_effect_xmls(self.root)

        self.assertEqual(1, len(errors))
        self.assertIn("libunexpected.so is absent", errors[0])


if __name__ == "__main__":
    unittest.main()
