#!/usr/bin/env python3
"""Validate the complete One UI 8.5/d2s audio compatibility contract.

The Note10+ device audio HAL is a 32-bit legacy C module.  API 36 audioserver
does not ship a HIDL 5.0 libaudiohal adapter, so the assembled ROM must expose
the unchanged d2s module through a VNDK31 HIDL 6.0 passthrough bridge.  This
validator pins every side of that bridge and rejects partial or mixed stacks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence


EM_ARM = 40
EM_AARCH64 = 183

EXPECTED_SOURCE_MARKER = "S721BXXSCDZF3/S721BOXMCDZF3/S721BXXSCDZF3"
EXPECTED_MULTILIB_MARKER = "S711BXXSGGZF2/S711BOXMGGZF2/S711BXXSGGZF2"
EXPECTED_TARGET_MARKER = "N975FXXS9HWHA/N975FOXM9HWH6/N975FXXS9HWH6"

BRIDGE_HASHES = {
    "bin/hw/android.hardware.audio.service": (
        "4e5690e831fb454c7da911b12c006e79a7cc6cb9a3e8fe8971656e55fc4d8b24"
    ),
    "lib/hw/android.hardware.audio@6.0-impl.so": (
        "57092f6b3e4af8877d4e23bd32aea197f3b5df9bb7c61f74d3ce3f99ca16aeef"
    ),
    "lib/hw/android.hardware.audio.effect@6.0-impl.so": (
        "0c76d753d51005140b6d029923a53ab8c3b0a559c5536288ddecfd45f3ba275b"
    ),
    "lib/android.hardware.audio.common@6.0.so": (
        "109bfdee3c58e6b7d297523aeb4b71b4d6782be843855c21aa6da191b1c50e20"
    ),
    "lib/android.hardware.audio.common@6.0-util.so": (
        "73cf8256fb62e128cd47b3e1ae2c5013c6c0ca6c4495ac3b93d22476a1de8606"
    ),
    "lib/android.hardware.audio@6.0.so": (
        "1f336b8025d87ff702d489d35c4fac1468263530b90102af74e3c713c35656c5"
    ),
    "lib/android.hardware.audio@6.0-util.so": (
        "53a08a73458bfc64a0612f8e4fcd4cf63d91121872da1238c8ceb9b726ddf4d5"
    ),
    "lib/android.hardware.audio.effect@6.0.so": (
        "1c8fef364f95e9142ff0f43ab1f76a8278fcd17752383a36765f2d62e0e5ceb1"
    ),
    "lib/android.hardware.audio.effect@6.0-util.so": (
        "e606e14965234e9e81d761a530b4b8ccacc66853d029087fce9a93f70de00f6a"
    ),
    "lib/soundfx/libswspatializer.so": (
        "8a34942d275bc565cdbd811755cc15aaa7fc8d75f891678fe2db10378644054e"
    ),
    "lib/spatializer-aidl-cpp.so": (
        "444f4f4bf395eed954eab0f7a6396be1e34a0884a6ceccd0efe337cf1899d15f"
    ),
    "lib64/soundfx/libswspatializer.so": (
        "b5bf81305153f730f34f99e3162511817c66ac491ba760c9f06d80c23c56b798"
    ),
    "lib64/spatializer-aidl-cpp.so": (
        "57b159e54bdba0727617481ad891933a51090d0325aefe5c0e7e657d10f6d633"
    ),
}

FRAMEWORK_FACTORY_HASHES = {
    "system/system/lib/libaudiohal.so": (
        "3efefa8614e10aee1ac182f0a51baee74a64c48678570b48ba05cc8f3fd1f525"
    ),
    "system/system/lib/libaudiohal@6.0.so": (
        "f7ec826a69c58c900b5f42cd0cb2c443018883035c4c06d897a5f2a01c95d77b"
    ),
    "system/system/lib64/libaudiohal.so": (
        "c753712c4f5e00f8a0d2cb9d930ee656e4898b6ecbd7c49b80d18d83a49f6584"
    ),
    "system/system/lib64/libaudiohal@6.0.so": (
        "6bca9f357f2054bb03fc0d8f933330895250c79e5fe6c9c79d06c094448f86d9"
    ),
}

FRAMEWORK_AUDIO_FILES = (
    "libaudiohal.so",
    "libaudiohal@6.0.so",
    "android.hardware.audio.common@6.0.so",
    "android.hardware.audio.common@6.0-util.so",
    "android.hardware.audio@6.0.so",
    "android.hardware.audio@6.0-util.so",
    "android.hardware.audio.effect@6.0.so",
    "android.hardware.audio.effect@6.0-util.so",
)

DEVICE_AUDIO_HASHES = {
    "lib/hw/audio.primary.exynos9825.so": (
        "2d2232756f787d0d2dbcff716dd4378e0c2a62f52e6107fca638fce8cea7c567"
    ),
    "lib/hw/audio.sec_primary.default.so": (
        "815942b44ed94a41fd9bf758be2ae2231303e51fb134f78d24bfe71324805a91"
    ),
    "lib/libaudioproxy.so": (
        "5bb4a93e14cbe112ecacb9dc3734a34aa13140bd4524e8ce41b29def4295ce85"
    ),
    "lib/libaudio-ril.so": (
        "99220c9d0dae5b1b22f78f95b9529e65ed14d1efc53b7a86403d7e46ee1f48c6"
    ),
    "lib/libaudio_soundtrigger.so": (
        "75513ee55a29847ed4ac150a5fe21e6606e3f70f0629f113cf297f5da05045fa"
    ),
    "lib/librecordalive.so": (
        "60a3ac9745e73cb093a7673ae6d855659b1037874a0e0b68dd5f02c1bed0126c"
    ),
    "etc/audio_policy_configuration.xml": (
        "675afdcc226683a777c97010008edc5d713685fe18ac894772cdb9cdfe2ebe45"
    ),
    "etc/audio_effects.xml": (
        "a229c622ee9f96911f491f23c54315dbc898fa2b39a09419ecfc1e9e5e9d6c16"
    ),
    "etc/audio_effects_sec.xml": (
        "ec5b071dad1f310cbfa48be4112b8e77b8e3e3c851fa69237cdd27edd0d02096"
    ),
    "etc/mixer_paths.xml": (
        "c05de27f4983dd9887e8666bc80813740ac3d1982cf20a722c263aa425eaa52c"
    ),
    "etc/mixer_gains.xml": (
        "72ebe32ba2c8b35063b3f7e58a2d61495bad5cafa711d2d54651de2d52472c7a"
    ),
    "etc/SoundBoosterParam.txt": (
        "197dd2272ac00ad47eecf137a9706405d13573e524101bfdf4f344b1e0f0f836"
    ),
}

KNOWN_OPTIONAL_EFFECT_LIBRARIES = frozenset(
    {"libplaybackrecorder.so", "libgearvr.so"}
)


@dataclass(frozen=True)
class Check:
    check_id: str
    ok: bool
    detail: str


@dataclass
class AudioContractReport:
    work_dir: str
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, check_id: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(check_id, ok, detail))

    @property
    def ok(self) -> bool:
        return bool(self.checks and all(check.ok for check in self.checks))

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "work_dir": self.work_dir,
            "summary": {
                "checks_passed": sum(check.ok for check in self.checks),
                "checks_failed": sum(not check.ok for check in self.checks),
                "warnings": len(self.warnings),
            },
            "checks": [asdict(check) for check in self.checks],
            "warnings": self.warnings,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_text(self) -> str:
        lines = [
            f"d2s audio contract: {'PASS' if self.ok else 'FAIL'}",
            f"Work dir: {self.work_dir}",
            "",
        ]
        lines.extend(
            f"[{'PASS' if check.ok else 'FAIL'}] {check.check_id}: "
            f"{check.detail}"
            for check in self.checks
        )
        lines.extend(f"[WARN] {warning}" for warning in self.warnings)
        lines.append(
            f"Summary: {sum(check.ok for check in self.checks)}/"
            f"{len(self.checks)} checks, {len(self.warnings)} warnings"
        )
        return "\n".join(lines)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_marker(root: Path) -> str:
    marker = root / ".extracted"
    return marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    return element.text.strip() if element is not None and element.text else ""


def _hash_contract(
    root: Path, expected: Mapping[str, str]
) -> tuple[list[str], int]:
    errors: list[str] = []
    matched = 0
    for relative, expected_hash in expected.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing {relative}")
            continue
        actual = _sha256(path)
        if actual != expected_hash:
            errors.append(
                f"{relative} sha256={actual}, expected={expected_hash}"
            )
            continue
        matched += 1
    return errors, matched


def _provider_contract(
    work_root: Path,
    provider_root: Path,
    relatives: Sequence[str],
) -> tuple[list[str], int]:
    errors: list[str] = []
    matched = 0
    for relative in relatives:
        work_file = work_root / relative
        provider_file = provider_root / relative
        if not work_file.is_file() or not provider_file.is_file():
            errors.append(f"missing work/provider pair for {relative}")
            continue
        if _sha256(work_file) != _sha256(provider_file):
            errors.append(f"provider mismatch for {relative}")
            continue
        matched += 1
    return errors, matched


def manifest_audio_errors(path: Path) -> list[str]:
    if not path.is_file():
        return ["vendor manifest is missing"]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        return [f"invalid vendor manifest XML: {error}"]

    expected = {
        "android.hardware.audio": (
            "IDevicesFactory",
            "@6.0::IDevicesFactory/default",
        ),
        "android.hardware.audio.effect": (
            "IEffectsFactory",
            "@6.0::IEffectsFactory/default",
        ),
    }
    errors: list[str] = []
    for hal_name, (interface_name, fqname) in expected.items():
        matches: list[ET.Element] = []
        for hal in root:
            if _local_name(hal.tag) != "hal" or hal.get("format", "hidl") != "hidl":
                continue
            name = next(
                (_text(child) for child in hal if _local_name(child.tag) == "name"),
                "",
            )
            if name == hal_name:
                matches.append(hal)
        if len(matches) != 1:
            errors.append(f"{hal_name} declarations={len(matches)}, expected=1")
            continue
        hal = matches[0]
        versions = [
            _text(child) for child in hal if _local_name(child.tag) == "version"
        ]
        fqnames = [
            _text(child) for child in hal if _local_name(child.tag) == "fqname"
        ]
        interfaces: list[tuple[str, str]] = []
        for interface in hal:
            if _local_name(interface.tag) != "interface":
                continue
            name = next(
                (
                    _text(child)
                    for child in interface
                    if _local_name(child.tag) == "name"
                ),
                "",
            )
            instances = [
                _text(child)
                for child in interface
                if _local_name(child.tag) == "instance"
            ]
            interfaces.extend((name, instance) for instance in instances)
        if versions != ["6.0"]:
            errors.append(f"{hal_name} versions={versions}, expected=['6.0']")
        if interfaces != [(interface_name, "default")]:
            errors.append(
                f"{hal_name} interfaces={interfaces}, expected "
                f"[({interface_name!r}, 'default')]"
            )
        if fqnames != [fqname]:
            errors.append(f"{hal_name} fqnames={fqnames}, expected=[{fqname!r}]")
    return errors


def _elf_identity(path: Path) -> tuple[int | None, int | None]:
    try:
        with path.open("rb") as stream:
            header = stream.read(20)
    except OSError:
        return None, None
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return None, None
    byte_order = {1: "<", 2: ">"}.get(header[5])
    if byte_order is None:
        return None, None
    return header[4], struct.unpack(f"{byte_order}H", header[18:20])[0]


def _dynamic_symbols(path: Path, nm: str | None = None) -> set[str]:
    nm = nm or shutil.which("nm")
    if not nm:
        raise RuntimeError("nm was not found")
    result = subprocess.run(
        (nm, "-D", "--defined-only", str(path)),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return {
        fields[-1].split("@", 1)[0]
        for line in result.stdout.splitlines()
        if (fields := line.split())
    }


def _validate_elf_bridge(work_dir: Path) -> tuple[list[str], int]:
    expected = {
        "vendor/lib/hw/android.hardware.audio@6.0-impl.so": (
            1,
            EM_ARM,
            "HIDL_FETCH_IDevicesFactory",
        ),
        "vendor/lib/hw/android.hardware.audio.effect@6.0-impl.so": (
            1,
            EM_ARM,
            "HIDL_FETCH_IEffectsFactory",
        ),
        "vendor/lib/hw/audio.primary.exynos9825.so": (1, EM_ARM, "HMI"),
        "vendor/lib/soundfx/libswspatializer.so": (1, EM_ARM, None),
        "vendor/lib64/soundfx/libswspatializer.so": (2, EM_AARCH64, None),
    }
    errors: list[str] = []
    matched = 0
    for relative, (elf_class, machine, symbol) in expected.items():
        path = work_dir / relative
        actual_class, actual_machine = _elf_identity(path)
        if (actual_class, actual_machine) != (elf_class, machine):
            errors.append(
                f"{relative} ELF identity={(actual_class, actual_machine)}, "
                f"expected={(elf_class, machine)}"
            )
            continue
        if symbol:
            try:
                symbols = _dynamic_symbols(path)
            except RuntimeError as error:
                errors.append(f"cannot inspect {relative}: {error}")
                continue
            if symbol not in symbols:
                errors.append(f"{relative} does not export {symbol}")
                continue
        matched += 1
    return errors, matched


def _validate_service(work_dir: Path) -> list[str]:
    service = work_dir / "vendor/bin/hw/android.hardware.audio.service"
    if _elf_identity(service) != (1, EM_ARM):
        return ["vendor audio service is not an ARM ELF32 executable"]
    try:
        contents = service.read_bytes()
    except OSError as error:
        return [f"cannot read vendor audio service: {error}"]
    required = (
        b"android.hardware.audio@6.0::IDevicesFactory",
        b"android.hardware.audio.effect@6.0::IEffectsFactory",
    )
    return [
        f"vendor audio service lacks {descriptor.decode()}"
        for descriptor in required
        if descriptor not in contents
    ]


def _validate_init(work_dir: Path) -> list[str]:
    definitions: list[tuple[Path, str]] = []
    init_dir = work_dir / "vendor/etc/init"
    for path in sorted(init_dir.rglob("*.rc")) if init_dir.is_dir() else ():
        for raw_line in path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            line = raw_line.strip()
            if line.startswith("service vendor.audio-hal "):
                definitions.append((path, line))
    if len(definitions) != 1:
        return [f"vendor.audio-hal service definitions={len(definitions)}, expected=1"]
    path, definition = definitions[0]
    errors: list[str] = []
    if definition != (
        "service vendor.audio-hal /vendor/bin/hw/android.hardware.audio.service"
    ):
        errors.append(f"unexpected audio service command: {definition}")
    contents = path.read_text(encoding="utf-8", errors="replace")
    for pattern, label in (
        (r"(?m)^\s*user\s+audioserver\s*$", "audioserver user"),
        (r"(?m)^\s*group\s+.*\baudio\b", "audio group"),
        (r"(?m)^\s*onrestart\s+restart\s+audioserver\s*$", "audioserver restart"),
    ):
        if not re.search(pattern, contents):
            errors.append(f"vendor.audio-hal is missing {label}")
    return errors


def _validate_hwservice_contexts(work_dir: Path) -> list[str]:
    path = work_dir / "system/system/etc/selinux/plat_hwservice_contexts"
    if not path.is_file():
        return ["platform hwservice contexts are missing"]
    contents = path.read_text(encoding="utf-8", errors="replace")
    required = (
        "android.hardware.audio::IDevicesFactory",
        "android.hardware.audio.effect::IEffectsFactory",
    )
    return [
        f"missing hwservice context for {name}"
        for name in required
        if not re.search(
            rf"(?m)^{re.escape(name)}\s+u:object_r:hal_audio_hwservice:s0\s*$",
            contents,
        )
    ]


def _validate_policy_xml(work_dir: Path) -> tuple[list[str], int]:
    root_file = work_dir / "vendor/etc/audio_policy_configuration.xml"
    errors: list[str] = []
    visited: set[Path] = set()
    queue = [root_file]
    while queue:
        path = queue.pop()
        if path in visited:
            continue
        visited.add(path)
        if not path.is_file():
            errors.append(f"missing policy include {path.name}")
            continue
        try:
            xml = ET.parse(path).getroot()
        except ET.ParseError as error:
            errors.append(f"invalid XML in {path.name}: {error}")
            continue
        for element in xml.iter():
            if _local_name(element.tag) != "include":
                continue
            href = element.get("href", "")
            include = (path.parent / href).resolve()
            try:
                include.relative_to(path.parent.resolve())
            except ValueError:
                errors.append(f"policy include escapes vendor/etc: {href}")
                continue
            queue.append(include)
    return errors, len(visited)


def _effect_library_candidates(work_dir: Path, library: str) -> tuple[Path, ...]:
    if library.startswith("/"):
        return (work_dir / library.lstrip("/"),)
    return (
        work_dir / "vendor/lib/soundfx" / library,
        work_dir / "vendor/lib64/soundfx" / library,
        work_dir / "system/system/lib/soundfx" / library,
        work_dir / "system/system/lib64/soundfx" / library,
        work_dir / "system/system/lib" / library,
        work_dir / "system/system/lib64" / library,
    )


def _validate_effect_xmls(
    work_dir: Path,
) -> tuple[list[str], list[str], int]:
    configs = sorted((work_dir / "vendor/etc").glob("audio_effects*.xml"))
    system_config = work_dir / "system/system/etc/audio_effects.xml"
    if system_config.is_file():
        configs.append(system_config)
    errors: list[str] = []
    warnings: list[str] = []
    parsed = 0
    for path in configs:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as error:
            errors.append(f"invalid effect XML in {path}: {error}")
            continue
        parsed += 1
        libraries = {
            element.get("name", ""): element.get("path", "")
            for element in root.iter()
            if _local_name(element.tag) == "library"
        }
        referenced = {
            element.get("library", "")
            for element in root.iter()
            if _local_name(element.tag) in {"effect", "effectProxy", "libsw", "libhw"}
            and element.get("library")
        }
        undeclared = sorted(referenced - libraries.keys())
        if undeclared:
            errors.append(f"{path.name} references undeclared libraries {undeclared}")
        for name, library in sorted(libraries.items()):
            if not name or not library:
                errors.append(f"{path.name} has an incomplete library declaration")
                continue
            if any(candidate.is_file() for candidate in _effect_library_candidates(work_dir, library)):
                continue
            detail = f"{path.name} library {name} -> {library} is absent"
            if library in KNOWN_OPTIONAL_EFFECT_LIBRARIES:
                warnings.append(detail + " (known stock-optional entry)")
            else:
                errors.append(detail)
    if not configs:
        errors.append("no audio effect XML files were found")
    return errors, warnings, parsed


def validate(
    work_dir: Path,
    source_firmware_dir: Path,
    multilib_firmware_dir: Path,
    target_firmware_dir: Path,
) -> AudioContractReport:
    work_dir = work_dir.resolve()
    source_firmware_dir = source_firmware_dir.resolve()
    multilib_firmware_dir = multilib_firmware_dir.resolve()
    target_firmware_dir = target_firmware_dir.resolve()
    report = AudioContractReport(str(work_dir))

    for check_id, root, expected in (
        ("firmware.source", source_firmware_dir, EXPECTED_SOURCE_MARKER),
        ("firmware.multilib", multilib_firmware_dir, EXPECTED_MULTILIB_MARKER),
        ("firmware.target", target_firmware_dir, EXPECTED_TARGET_MARKER),
    ):
        actual = _read_marker(root)
        report.add(
            check_id,
            actual == expected,
            f"marker={actual or '<missing>'}, expected={expected}",
        )

    errors, matched = _hash_contract(work_dir / "vendor", BRIDGE_HASHES)
    report.add(
        "bridge.hashes",
        not errors,
        f"matched {matched}/{len(BRIDGE_HASHES)}" if not errors else "; ".join(errors),
    )
    errors, matched = _provider_contract(
        work_dir / "vendor",
        multilib_firmware_dir / "vendor",
        tuple(BRIDGE_HASHES),
    )
    report.add(
        "bridge.provider",
        not errors,
        f"matched {matched}/{len(BRIDGE_HASHES)} to multilib donor"
        if not errors
        else "; ".join(errors),
    )

    errors, matched = _hash_contract(work_dir, FRAMEWORK_FACTORY_HASHES)
    report.add(
        "framework.factories",
        not errors,
        f"matched {matched}/{len(FRAMEWORK_FACTORY_HASHES)} analyzed API 36 factories"
        if not errors
        else "; ".join(errors),
    )
    errors32, matched32 = _provider_contract(
        work_dir / "system/system/lib",
        multilib_firmware_dir / "system/system/lib",
        FRAMEWORK_AUDIO_FILES,
    )
    errors64, matched64 = _provider_contract(
        work_dir / "system/system/lib64",
        source_firmware_dir / "system/system/lib64",
        FRAMEWORK_AUDIO_FILES,
    )
    framework_errors = errors32 + errors64
    report.add(
        "framework.provider",
        not framework_errors,
        f"matched 32-bit={matched32}/{len(FRAMEWORK_AUDIO_FILES)}, "
        f"64-bit={matched64}/{len(FRAMEWORK_AUDIO_FILES)}"
        if not framework_errors
        else "; ".join(framework_errors),
    )

    errors, matched = _hash_contract(work_dir / "vendor", DEVICE_AUDIO_HASHES)
    report.add(
        "device.hashes",
        not errors,
        f"matched {matched}/{len(DEVICE_AUDIO_HASHES)} pinned d2s files"
        if not errors
        else "; ".join(errors),
    )
    errors, matched = _provider_contract(
        work_dir / "vendor",
        target_firmware_dir / "vendor",
        tuple(DEVICE_AUDIO_HASHES),
    )
    report.add(
        "device.provider",
        not errors,
        f"matched {matched}/{len(DEVICE_AUDIO_HASHES)} to N975F firmware"
        if not errors
        else "; ".join(errors),
    )

    errors = manifest_audio_errors(work_dir / "vendor/etc/vintf/manifest.xml")
    report.add(
        "vintf.audio6",
        not errors,
        "audio and effect default instances declare HIDL 6.0"
        if not errors
        else "; ".join(errors),
    )
    errors = _validate_service(work_dir)
    report.add(
        "service.capability",
        not errors,
        "ARM32 service carries both HIDL 6.0 registration descriptors"
        if not errors
        else "; ".join(errors),
    )
    errors, matched = _validate_elf_bridge(work_dir)
    report.add(
        "bridge.elf",
        not errors,
        f"validated {matched}/5 bridge and legacy ELF entry points"
        if not errors
        else "; ".join(errors),
    )
    errors = _validate_init(work_dir)
    report.add(
        "init.audio",
        not errors,
        "single vendor.audio-hal service has correct identity and restart contract"
        if not errors
        else "; ".join(errors),
    )
    errors = _validate_hwservice_contexts(work_dir)
    report.add(
        "selinux.hwservice",
        not errors,
        "audio HIDL services map to hal_audio_hwservice"
        if not errors
        else "; ".join(errors),
    )
    errors, parsed = _validate_policy_xml(work_dir)
    report.add(
        "policy.xml",
        not errors,
        f"parsed {parsed} active policy XML files with closed XIncludes"
        if not errors
        else "; ".join(errors),
    )
    errors, warnings, parsed = _validate_effect_xmls(work_dir)
    report.warnings.extend(warnings)
    report.add(
        "effects.xml",
        not errors,
        f"parsed {parsed} effect XML files; all non-optional libraries exist"
        if not errors
        else "; ".join(errors),
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the One UI 8.5/d2s audio compatibility bridge"
    )
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--source-firmware-dir", type=Path, required=True)
    parser.add_argument("--multilib-firmware-dir", type=Path, required=True)
    parser.add_argument("--target-firmware-dir", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    report = validate(
        args.work_dir,
        args.source_firmware_dir,
        args.multilib_firmware_dir,
        args.target_firmware_dir,
    )
    print(report.to_text())
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(report.to_json() + "\n", encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
