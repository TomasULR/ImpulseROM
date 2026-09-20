#!/usr/bin/env python3
"""Check device HALs against Android's target-level framework matrix chain.

This intentionally models the HAL portion of Android 16 libvintf's framework
matrix combination. The exact target FCM is mandatory. Matrices from newer
levels are optional, but versions for the same format/name/interface/instance
are merged as alternatives into an existing mandatory requirement.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True, order=True)
class VersionRange:
    major: int
    minimum_minor: int
    maximum_minor: int

    def supports(self, version: Version) -> bool:
        # libvintf treats the upper minor as informational: a framework that
        # accepts x.min also accepts a newer minor from the same HIDL package.
        return version.major == self.major and version.minor >= self.minimum_minor

    def __str__(self) -> str:
        if self.minimum_minor == self.maximum_minor:
            return f"{self.major}.{self.minimum_minor}"
        return f"{self.major}.{self.minimum_minor}-{self.maximum_minor}"


@dataclass(frozen=True, order=True)
class InstanceKey:
    hal_format: str
    package: str
    interface: str
    instance: str
    is_regex: bool = False

    def describe(self) -> str:
        marker = "regex:" if self.is_regex else ""
        return (
            f"{self.hal_format} {self.package}::{self.interface}/"
            f"{marker}{self.instance}"
        )


def _tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [child for child in element if _tag(child) == name]


def _text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _tag(child) == name and child.text:
            return child.text.strip()
    return None


def _parse_version_range(value: str) -> VersionRange:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:-(\d+))?", value.strip())
    if not match:
        raise ValueError(f"invalid HIDL version range: {value}")
    major, minimum, maximum = match.groups()
    return VersionRange(int(major), int(minimum), int(maximum or minimum))


def _parse_version(value: str, hal_format: str) -> Version:
    value = value.strip()
    if hal_format == "aidl" and re.fullmatch(r"\d+", value):
        return Version(int(value), 0)
    parsed = _parse_version_range(value)
    if parsed.minimum_minor != parsed.maximum_minor:
        raise ValueError(f"manifest version cannot be a range: {value}")
    return Version(parsed.major, parsed.minimum_minor)


def _parse_aidl_ranges(value: str) -> tuple[VersionRange, ...]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", value.strip())
    if not match:
        raise ValueError(f"invalid AIDL version range: {value}")
    minimum, maximum = (int(item) if item else None for item in match.groups())
    maximum = maximum if maximum is not None else minimum
    if maximum < minimum:
        raise ValueError(f"invalid descending AIDL version range: {value}")
    return tuple(VersionRange(version, 0, 0) for version in range(minimum, maximum + 1))


def _matrix_instances(
    root: ElementTree.Element,
) -> list[tuple[InstanceKey, tuple[VersionRange, ...], bool]]:
    instances: list[tuple[InstanceKey, tuple[VersionRange, ...], bool]] = []
    for hal in _children(root, "hal"):
        hal_format = hal.attrib.get("format", "hidl")
        package = _text(hal, "name")
        if not package:
            continue
        optional = hal.attrib.get("optional", "false") == "true"
        version_values = [
            child.text.strip()
            for child in _children(hal, "version")
            if child.text and child.text.strip()
        ]
        if hal_format == "aidl":
            ranges = tuple(
                version_range
                for value in version_values
                for version_range in _parse_aidl_ranges(value)
            )
        else:
            ranges = tuple(_parse_version_range(value) for value in version_values)

        for interface in _children(hal, "interface"):
            interface_name = _text(interface, "name")
            if not interface_name:
                continue
            for child in interface:
                child_tag = _tag(child)
                if child_tag not in {"instance", "regex-instance"} or not child.text:
                    continue
                key = InstanceKey(
                    hal_format,
                    package,
                    interface_name,
                    child.text.strip(),
                    child_tag == "regex-instance",
                )
                instances.append((key, ranges, optional))

        for fqname_node in _children(hal, "fqname"):
            if not fqname_node.text:
                continue
            fqname = fqname_node.text.strip()
            if hal_format == "hidl":
                match = re.fullmatch(r"@(\d+)\.(\d+)::([^/]+)/(.+)", fqname)
                if not match:
                    raise ValueError(f"invalid matrix HIDL fqname: {fqname}")
                major, minor, interface_name, instance = match.groups()
                fq_ranges = (VersionRange(int(major), int(minor), int(minor)),)
            else:
                match = re.fullmatch(r"([^/]+)/(.+)", fqname)
                if not match:
                    raise ValueError(f"invalid matrix AIDL fqname: {fqname}")
                interface_name, instance = match.groups()
                fq_ranges = ranges
            instances.append(
                (
                    InstanceKey(
                        hal_format, package, interface_name, instance, False
                    ),
                    fq_ranges,
                    optional,
                )
            )
    return instances


def _manifest_instances(root: ElementTree.Element) -> dict[InstanceKey, set[Version]]:
    instances: dict[InstanceKey, set[Version]] = {}
    for hal in _children(root, "hal"):
        hal_format = hal.attrib.get("format", "hidl")
        package = _text(hal, "name")
        if not package:
            continue
        versions = [
            _parse_version(child.text, hal_format)
            for child in _children(hal, "version")
            if child.text and child.text.strip()
        ]

        for interface in _children(hal, "interface"):
            interface_name = _text(interface, "name")
            if not interface_name:
                continue
            for instance_node in _children(interface, "instance"):
                if not instance_node.text:
                    continue
                key = InstanceKey(
                    hal_format,
                    package,
                    interface_name,
                    instance_node.text.strip(),
                    False,
                )
                instances.setdefault(key, set()).update(versions)

        for fqname_node in _children(hal, "fqname"):
            if not fqname_node.text:
                continue
            fqname = fqname_node.text.strip()
            if hal_format == "hidl":
                match = re.fullmatch(r"@(\d+)\.(\d+)::([^/]+)/(.+)", fqname)
                if not match:
                    raise ValueError(f"invalid manifest HIDL fqname: {fqname}")
                major, minor, interface_name, instance = match.groups()
                fq_versions = {Version(int(major), int(minor))}
            else:
                match = re.fullmatch(r"([^/]+)/(.+)", fqname)
                if not match:
                    raise ValueError(f"invalid manifest AIDL fqname: {fqname}")
                interface_name, instance = match.groups()
                fq_versions = set(versions) or {Version(1, 0)}
            key = InstanceKey(
                hal_format, package, interface_name, instance, False
            )
            instances.setdefault(key, set()).update(fq_versions)
    return instances


def _vintf_files(root: Path, kind: str) -> list[Path]:
    paths: set[Path] = set()
    if kind == "manifest":
        for partition in ("vendor", "odm"):
            vintf = root / partition / "etc/vintf"
            main = vintf / "manifest.xml"
            if main.is_file():
                paths.add(main)
            fragment_dir = vintf / "manifest"
            if fragment_dir.is_dir():
                paths.update(fragment_dir.glob("*.xml"))
    else:
        for vintf in (
            root / "system/system/etc/vintf",
            root / "system/system/system_ext/etc/vintf",
            root / "system_ext/etc/vintf",
            root / "product/etc/vintf",
        ):
            if vintf.is_dir():
                paths.update(vintf.glob("compatibility_matrix.*.xml"))
    return sorted(paths)


def validate(work_dir: Path) -> tuple[list[str], int, int, str | None]:
    manifest_files = _vintf_files(work_dir, "manifest")
    matrix_files = _vintf_files(work_dir, "matrix")
    errors: list[str] = []
    if not manifest_files:
        return ["no device VINTF manifests found"], 0, 0, None

    device_roots: list[ElementTree.Element] = []
    target_level: str | None = None
    for path in manifest_files:
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as error:
            errors.append(f"invalid device manifest XML {path}: {error}")
            continue
        if root.attrib.get("type") not in {None, "device"}:
            continue
        level = root.attrib.get("target-level")
        if level:
            if target_level is not None and target_level != level:
                errors.append(
                    f"conflicting device target levels: {target_level} and {level}"
                )
            target_level = level
        device_roots.append(root)

    if target_level is None:
        errors.append("device manifest does not declare target-level")
        return errors, 0, 0, None

    try:
        numeric_target_level = int(target_level)
    except ValueError:
        errors.append(f"unsupported non-numeric target-level: {target_level}")
        return errors, 0, 0, target_level

    matrices: list[tuple[int, Path, ElementTree.Element]] = []
    for path in matrix_files:
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as error:
            errors.append(f"invalid framework matrix XML {path}: {error}")
            continue
        if root.attrib.get("type") != "framework":
            continue
        level = root.attrib.get("level")
        if not level:
            continue
        try:
            numeric_level = int(level)
        except ValueError:
            errors.append(f"invalid framework matrix level {level} in {path}")
            continue
        matrices.append((numeric_level, path, root))

    exact = [item for item in matrices if item[0] == numeric_target_level]
    if len(exact) != 1:
        errors.append(
            f"expected exactly one framework matrix for target FCM {target_level}, "
            f"found {len(exact)}"
        )
        return errors, 0, 0, target_level

    required: dict[InstanceKey, set[VersionRange]] = {}
    try:
        for key, ranges, optional in _matrix_instances(exact[0][2]):
            if optional:
                continue
            required.setdefault(key, set()).update(ranges)

        for level, _, root in sorted(matrices, key=lambda item: item[0]):
            if level <= numeric_target_level:
                continue
            for key, ranges, _ in _matrix_instances(root):
                if key in required:
                    required[key].update(ranges)
    except ValueError as error:
        errors.append(str(error))
        return errors, len(required), 0, target_level

    provided: dict[InstanceKey, set[Version]] = {}
    try:
        for root in device_roots:
            for key, versions in _manifest_instances(root).items():
                provided.setdefault(key, set()).update(versions)
    except ValueError as error:
        errors.append(str(error))
        return errors, len(required), len(provided), target_level

    for requirement, ranges in sorted(required.items()):
        candidates = [
            (key, versions)
            for key, versions in provided.items()
            if key.hal_format == requirement.hal_format
            and key.package == requirement.package
            and key.interface == requirement.interface
            and (
                re.fullmatch(requirement.instance, key.instance) is not None
                if requirement.is_regex
                else key.instance == requirement.instance
            )
        ]
        matched = False
        for _, versions in candidates:
            if not ranges and versions:
                matched = True
                break
            if any(version_range.supports(version) for version_range in ranges for version in versions):
                matched = True
                break
        if matched:
            continue

        allowed = ",".join(str(item) for item in sorted(ranges)) or "any"
        available = sorted(
            {str(version) for _, versions in candidates for version in versions}
        )
        errors.append(
            f"required {requirement.describe()} versions [{allowed}] is not "
            f"provided; available={available or '<missing>'}"
        )

    return errors, len(required), len(provided), target_level


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_dir", type=Path)
    args = parser.parse_args()
    work_dir = args.work_dir.resolve()
    if not work_dir.is_dir():
        parser.error(f"work dir does not exist: {work_dir}")

    errors, required_count, provided_count, target_level = validate(work_dir)
    print(
        "VINTF HAL compatibility: "
        f"target FCM={target_level or '<missing>'}, "
        f"{required_count} required instances, {provided_count} declared instances"
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("VINTF HAL compatibility passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
