#!/usr/bin/env python3
"""Record and verify logical DEX inventories across container round-trips."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence


INVENTORY_KINDS = ("classes", "methods", "fields", "types")
DEX_NUMBER_RE = r"(?:[2-9]|[1-9][0-9]+)"
DEX_ENTRY_RE = re.compile(rf"classes(?:{DEX_NUMBER_RE})?\.dex")
SOURCE_ENTRY_RE = re.compile(
    rf"classes(?P<physical>{DEX_NUMBER_RE})?\.dex"
    rf"(?:/(?P<logical>{DEX_NUMBER_RE}))?"
)
DESCRIPTOR_RE = re.compile(r"L[^\s;]+;")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
VALID_STANDALONE_DEX_MAGICS = {
    b"dex\n035\x00",
    b"dex\n037\x00",
    b"dex\n038\x00",
    b"dex\n039\x00",
    b"dex\n040\x00",
}


class ValidationError(RuntimeError):
    """Raised when a DEX mapping or inventory cannot be trusted."""


@dataclass(frozen=True)
class LogicalDex:
    index: int
    source_entry: str
    smali_dir: str
    output_dex: str


@dataclass(frozen=True)
class InventoryItem:
    count: int
    sha256: str


@dataclass(frozen=True)
class SentinelLocation:
    descriptor: str
    logical_index: int
    source_entry: str
    output_dex: str


ListItems = Callable[[str, str], list[str]]
AllowedAdditions = dict[tuple[int, str], set[str]]


def _canonical_items(items: Iterable[str]) -> list[str]:
    return sorted(item.rstrip("\r\n") for item in items if item.rstrip("\r\n"))


def _inventory_item(items: Iterable[str]) -> InventoryItem:
    ordered = _canonical_items(items)
    payload = "".join(f"{item}\n" for item in ordered).encode("utf-8")
    return InventoryItem(len(ordered), hashlib.sha256(payload).hexdigest())


def run_baksmali_list(baksmali: str, kind: str, dex_spec: str) -> list[str]:
    try:
        result = subprocess.run(
            [baksmali, "list", kind, dex_spec],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise ValidationError(
            f"cannot run {baksmali} list {kind} for {dex_spec}: {error}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise ValidationError(
            f"baksmali list {kind} failed for {dex_spec}: {detail}"
        )
    # Preserve tool output here. Inventory callers canonicalize their own
    # values; DEX-entry callers compare exact sets because baksmali's ZIP-backed
    # implementation reports a lexical TreeMap order (classes10 before
    # classes2), while logical order is recorded explicitly by our map.
    return [line.rstrip("\r\n") for line in result.stdout.splitlines() if line]


def load_logical_map(path: Path) -> list[LogicalDex]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValidationError(f"cannot read logical DEX map {path}: {error}") from error
    if not lines or lines[0] != "index\tsource_entry\tsmali_dir\toutput_dex":
        raise ValidationError(f"invalid logical DEX map header in {path}")

    entries: list[LogicalDex] = []
    for line_number, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            raise ValidationError(f"invalid logical DEX map row {path}:{line_number}")
        try:
            index = int(fields[0])
        except ValueError as error:
            raise ValidationError(
                f"invalid logical DEX index at {path}:{line_number}: {fields[0]}"
            ) from error
        entries.append(LogicalDex(index, fields[1], fields[2], fields[3]))

    if not entries:
        raise ValidationError(f"logical DEX map is empty: {path}")
    expected_indexes = list(range(1, len(entries) + 1))
    if [entry.index for entry in entries] != expected_indexes:
        raise ValidationError(
            f"logical DEX indexes must be contiguous and ordered in {path}: "
            f"expected={expected_indexes}, actual={[entry.index for entry in entries]}"
        )

    source_order: list[tuple[int, int]] = []
    for entry in entries:
        expected_smali = "smali" if entry.index == 1 else f"smali_classes{entry.index}"
        expected_output = "classes.dex" if entry.index == 1 else f"classes{entry.index}.dex"
        if entry.smali_dir != expected_smali or entry.output_dex != expected_output:
            raise ValidationError(
                f"logical DEX {entry.index} has an unsafe flattening map: "
                f"smali={entry.smali_dir} output={entry.output_dex}, "
                f"expected smali={expected_smali} output={expected_output}"
            )
        source_match = SOURCE_ENTRY_RE.fullmatch(entry.source_entry)
        if not source_match:
            raise ValidationError(
                f"logical DEX {entry.index} has invalid source entry {entry.source_entry}"
            )
        source_order.append(
            (
                int(source_match.group("physical") or "1"),
                int(source_match.group("logical") or "1"),
            )
        )

    if source_order != sorted(source_order):
        raise ValidationError(
            f"logical DEX source entries are not in Android load order in {path}"
        )
    physical_indexes = sorted({physical for physical, _ in source_order})
    if physical_indexes != list(range(1, len(physical_indexes) + 1)):
        raise ValidationError(
            f"physical DEX indexes must be contiguous in {path}: "
            f"actual={physical_indexes}"
        )
    for physical_index in physical_indexes:
        logical_indexes = [
            logical
            for physical, logical in source_order
            if physical == physical_index
        ]
        if logical_indexes != list(range(1, len(logical_indexes) + 1)):
            raise ValidationError(
                f"container DEX indexes for physical DEX {physical_index} must be "
                f"contiguous in {path}: actual={logical_indexes}"
            )

    for attribute in ("source_entry", "smali_dir", "output_dex"):
        values = [getattr(entry, attribute) for entry in entries]
        if len(values) != len(set(values)):
            raise ValidationError(f"logical DEX map contains duplicate {attribute}: {path}")
    return entries


def _manifest_path(manifest_dir: Path, logical_index: int) -> Path:
    return manifest_dir / f"logical-{logical_index}.inventory.tsv"


def write_inventory(path: Path, inventory: dict[str, InventoryItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["kind\tcount\tsha256"]
    for kind in INVENTORY_KINDS:
        item = inventory[kind]
        rows.append(f"{kind}\t{item.count}\t{item.sha256}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def load_inventory(path: Path) -> dict[str, InventoryItem]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValidationError(f"cannot read DEX inventory {path}: {error}") from error
    if not lines or lines[0] != "kind\tcount\tsha256":
        raise ValidationError(f"invalid DEX inventory header in {path}")

    inventory: dict[str, InventoryItem] = {}
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != 3 or fields[0] not in INVENTORY_KINDS:
            raise ValidationError(f"invalid DEX inventory row {path}:{line_number}")
        if fields[0] in inventory:
            raise ValidationError(f"duplicate {fields[0]} inventory row in {path}")
        try:
            count = int(fields[1])
        except ValueError as error:
            raise ValidationError(
                f"invalid inventory count at {path}:{line_number}: {fields[1]}"
            ) from error
        if count < 0 or not SHA256_RE.fullmatch(fields[2]):
            raise ValidationError(f"invalid DEX inventory row {path}:{line_number}")
        inventory[fields[0]] = InventoryItem(count, fields[2])

    if set(inventory) != set(INVENTORY_KINDS):
        raise ValidationError(f"DEX inventory is incomplete: {path}")
    return inventory


def create_inventory(dex_spec: str, list_items: ListItems) -> dict[str, InventoryItem]:
    return {
        kind: _inventory_item(list_items(kind, dex_spec))
        for kind in INVENTORY_KINDS
    }


def compare_inventory(
    expected: dict[str, InventoryItem],
    actual: dict[str, InventoryItem],
    *,
    label: str,
) -> None:
    differences = []
    for kind in INVENTORY_KINDS:
        if expected[kind] != actual[kind]:
            differences.append(
                f"{kind}: expected count={expected[kind].count} "
                f"sha256={expected[kind].sha256}, actual count={actual[kind].count} "
                f"sha256={actual[kind].sha256}"
            )
    if differences:
        raise ValidationError(
            f"DEX inventory mismatch for {label}: " + "; ".join(differences)
        )


def load_allowed_additions(path: Path) -> AllowedAdditions:
    """Load an exact, logical-DEX-scoped allowlist of newly added members."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValidationError(
            f"cannot read allowed DEX additions {path}: {error}"
        ) from error
    if not lines or lines[0] != "logical_index\tkind\titem":
        raise ValidationError(f"invalid allowed DEX additions header in {path}")

    additions: AllowedAdditions = {}
    for line_number, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        fields = line.split("\t", 2)
        if len(fields) != 3 or fields[1] not in INVENTORY_KINDS or not fields[2]:
            raise ValidationError(
                f"invalid allowed DEX addition at {path}:{line_number}"
            )
        try:
            logical_index = int(fields[0])
        except ValueError as error:
            raise ValidationError(
                f"invalid logical DEX index at {path}:{line_number}: {fields[0]}"
            ) from error
        if logical_index < 1:
            raise ValidationError(
                f"invalid logical DEX index at {path}:{line_number}: {logical_index}"
            )
        key = (logical_index, fields[1])
        values = additions.setdefault(key, set())
        if fields[2] in values:
            raise ValidationError(
                f"duplicate allowed DEX addition at {path}:{line_number}"
            )
        values.add(fields[2])

    if not additions:
        raise ValidationError(f"allowed DEX additions file is empty: {path}")
    return additions


def compare_inventory_with_allowed_additions(
    source_spec: str,
    actual_spec: str,
    logical_index: int,
    allowed_additions: AllowedAdditions,
    list_items: ListItems,
    *,
    label: str,
) -> None:
    """Require a lossless inventory plus only the explicitly named additions."""
    differences = []
    for kind in INVENTORY_KINDS:
        source_list = list_items(kind, source_spec)
        actual_list = list_items(kind, actual_spec)
        source = set(source_list)
        actual = set(actual_list)
        if len(source) != len(source_list) or len(actual) != len(actual_list):
            raise ValidationError(
                f"duplicate {kind} entries while checking allowed additions for {label}"
            )
        allowed = allowed_additions.get((logical_index, kind), set())
        already_present = allowed & source
        removed = source - actual
        added = actual - source
        if already_present or removed or added != allowed:
            differences.append(
                f"{kind}: allowed={sorted(allowed)}, already-present={sorted(already_present)}, "
                f"removed={sorted(removed)}, added={sorted(added)}"
            )
    if differences:
        raise ValidationError(
            f"DEX allowed-additions mismatch for {label}: " + "; ".join(differences)
        )


def _artifact_spec(artifact: Path, entry: str) -> str:
    if artifact.is_dir():
        return str(artifact / entry)
    return f"{artifact}/{entry}"


def _require_standalone_output_dex(artifact: Path, entry: str) -> None:
    try:
        if artifact.is_dir():
            with (artifact / entry).open("rb") as dex_file:
                magic = dex_file.read(8)
        else:
            with zipfile.ZipFile(artifact) as archive:
                with archive.open(entry) as dex_file:
                    magic = dex_file.read(8)
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise ValidationError(
            f"cannot read packaged DEX entry {entry} from {artifact}: {error}"
        ) from error
    if magic not in VALID_STANDALONE_DEX_MAGICS:
        rendered_magic = magic.hex() if magic else "empty"
        raise ValidationError(
            f"flattened DEX entry {entry} in {artifact} is not a supported "
            f"standalone DEX 035-040 (magic={rendered_magic}); DEX 041 "
            "containers must be split before packaging"
        )


def _require_source_entries(
    artifact: Path, logical_map: Sequence[LogicalDex], list_items: ListItems
) -> None:
    actual = list_items("dex", str(artifact))
    expected = [entry.source_entry for entry in logical_map]
    if set(actual) != set(expected) or len(actual) != len(expected):
        raise ValidationError(
            f"source logical DEX map does not match {artifact}: "
            f"expected={expected}, actual={actual}"
        )


def _require_output_entries(
    artifact: Path, logical_map: Sequence[LogicalDex], list_items: ListItems
) -> None:
    expected = [entry.output_dex for entry in logical_map]
    if artifact.is_dir():
        actual = sorted(
            path.name
            for path in artifact.iterdir()
            if path.is_file() and DEX_ENTRY_RE.fullmatch(path.name)
        )
        missing_files = [entry for entry in expected if not (artifact / entry).is_file()]
        if missing_files:
            raise ValidationError(
                f"assembled artifact {artifact} is missing DEX entries {missing_files}"
            )
        if set(actual) != set(expected) or len(actual) != len(expected):
            raise ValidationError(
                f"assembled DEX entries do not match {artifact}: "
                f"expected={expected}, actual={actual}"
            )
        for entry in expected:
            _require_standalone_output_dex(artifact, entry)
        return

    actual = list_items("dex", str(artifact))
    if set(actual) != set(expected) or len(actual) != len(expected):
        raise ValidationError(
            f"packaged DEX entries do not match {artifact}: "
            f"expected={expected}, actual={actual}"
        )
    for entry in expected:
        _require_standalone_output_dex(artifact, entry)


def load_sentinel_descriptors(path: Path) -> list[str]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValidationError(f"cannot read DEX sentinels {path}: {error}") from error
    descriptors = [
        line.strip()
        for line in raw_lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not descriptors:
        raise ValidationError(f"DEX sentinel list is empty: {path}")
    if len(descriptors) != len(set(descriptors)):
        raise ValidationError(f"DEX sentinel list contains duplicates: {path}")
    invalid = [item for item in descriptors if not DESCRIPTOR_RE.fullmatch(item)]
    if invalid:
        raise ValidationError(f"invalid DEX sentinel descriptors in {path}: {invalid}")
    return descriptors


def locate_sentinels(
    artifact: Path,
    logical_map: Sequence[LogicalDex],
    descriptors: Sequence[str],
    list_items: ListItems,
    *,
    source: bool,
) -> list[SentinelLocation]:
    classes_by_index: dict[int, set[str]] = {}
    for entry in logical_map:
        dex_entry = entry.source_entry if source else entry.output_dex
        classes_by_index[entry.index] = set(
            list_items("classes", _artifact_spec(artifact, dex_entry))
        )

    locations: list[SentinelLocation] = []
    for descriptor in descriptors:
        matches = [
            entry
            for entry in logical_map
            if descriptor in classes_by_index[entry.index]
        ]
        if len(matches) != 1:
            raise ValidationError(
                f"DEX sentinel {descriptor} must occur in exactly one logical DEX "
                f"inside {artifact}, found indexes={[entry.index for entry in matches]}"
            )
        entry = matches[0]
        locations.append(
            SentinelLocation(
                descriptor, entry.index, entry.source_entry, entry.output_dex
            )
        )
    return locations


def write_sentinel_map(path: Path, sentinels: Sequence[SentinelLocation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["descriptor\tlogical_index\tsource_entry\toutput_dex"]
    rows.extend(
        f"{item.descriptor}\t{item.logical_index}\t{item.source_entry}\t{item.output_dex}"
        for item in sentinels
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def load_sentinel_map(path: Path) -> list[SentinelLocation]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValidationError(f"cannot read DEX sentinel map {path}: {error}") from error
    if not lines or lines[0] != "descriptor\tlogical_index\tsource_entry\toutput_dex":
        raise ValidationError(f"invalid DEX sentinel map header in {path}")
    sentinels: list[SentinelLocation] = []
    for line_number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != 4:
            raise ValidationError(f"invalid DEX sentinel row {path}:{line_number}")
        try:
            logical_index = int(fields[1])
        except ValueError as error:
            raise ValidationError(
                f"invalid sentinel logical index at {path}:{line_number}"
            ) from error
        if logical_index < 1 or not DESCRIPTOR_RE.fullmatch(fields[0]):
            raise ValidationError(f"invalid DEX sentinel row {path}:{line_number}")
        sentinels.append(
            SentinelLocation(fields[0], logical_index, fields[2], fields[3])
        )
    if not sentinels:
        raise ValidationError(f"DEX sentinel map is empty: {path}")
    descriptors = [item.descriptor for item in sentinels]
    if len(descriptors) != len(set(descriptors)):
        raise ValidationError(f"DEX sentinel map contains duplicates: {path}")
    return sentinels


def snapshot_logical_dexes(
    artifact: Path,
    map_path: Path,
    manifest_dir: Path,
    list_items: ListItems,
    *,
    sentinel_file: Path | None = None,
    sentinel_output: Path | None = None,
) -> None:
    logical_map = load_logical_map(map_path)
    _require_source_entries(artifact, logical_map, list_items)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for entry in logical_map:
        inventory = create_inventory(
            _artifact_spec(artifact, entry.source_entry), list_items
        )
        write_inventory(_manifest_path(manifest_dir, entry.index), inventory)

    if sentinel_file is None:
        if sentinel_output is not None:
            raise ValidationError("sentinel output was supplied without a sentinel file")
        return
    if sentinel_output is None:
        raise ValidationError("sentinel file needs a sentinel output path")
    descriptors = load_sentinel_descriptors(sentinel_file)
    sentinels = locate_sentinels(
        artifact, logical_map, descriptors, list_items, source=True
    )
    write_sentinel_map(sentinel_output, sentinels)


def verify_logical_dexes(
    artifact: Path,
    map_path: Path,
    manifest_dir: Path,
    list_items: ListItems,
    *,
    label: str,
    sentinel_map_path: Path | None = None,
    source_artifact: Path | None = None,
    allowed_additions_path: Path | None = None,
) -> None:
    logical_map = load_logical_map(map_path)
    _require_output_entries(artifact, logical_map, list_items)
    allowed_additions: AllowedAdditions | None = None
    if allowed_additions_path is not None:
        if source_artifact is None:
            raise ValidationError(
                "allowed DEX additions require the original source artifact"
            )
        allowed_additions = load_allowed_additions(allowed_additions_path)
        valid_indexes = {entry.index for entry in logical_map}
        invalid_indexes = sorted(
            {index for index, _ in allowed_additions} - valid_indexes
        )
        if invalid_indexes:
            raise ValidationError(
                f"allowed DEX additions reference missing logical indexes: {invalid_indexes}"
            )
        _require_source_entries(source_artifact, logical_map, list_items)
    elif source_artifact is not None:
        raise ValidationError(
            "source artifact was supplied without allowed DEX additions"
        )

    for entry in logical_map:
        entry_label = (
            f"{label} logical {entry.index} "
            f"({entry.source_entry} -> {entry.output_dex})"
        )
        if allowed_additions is None:
            expected = load_inventory(_manifest_path(manifest_dir, entry.index))
            actual = create_inventory(
                _artifact_spec(artifact, entry.output_dex), list_items
            )
            compare_inventory(expected, actual, label=entry_label)
        else:
            assert source_artifact is not None
            compare_inventory_with_allowed_additions(
                _artifact_spec(source_artifact, entry.source_entry),
                _artifact_spec(artifact, entry.output_dex),
                entry.index,
                allowed_additions,
                list_items,
                label=entry_label,
            )

    if sentinel_map_path is None:
        return
    expected_sentinels = load_sentinel_map(sentinel_map_path)
    actual_sentinels = locate_sentinels(
        artifact,
        logical_map,
        [item.descriptor for item in expected_sentinels],
        list_items,
        source=False,
    )
    if actual_sentinels != expected_sentinels:
        details = []
        for expected, actual in zip(expected_sentinels, actual_sentinels):
            if expected != actual:
                details.append(
                    f"{expected.descriptor}: source logical={expected.logical_index} "
                    f"({expected.source_entry} -> {expected.output_dex}), "
                    f"actual logical={actual.logical_index} ({actual.output_dex})"
                )
        raise ValidationError(
            f"DEX sentinel logical-index mismatch for {label}: " + "; ".join(details)
        )


JUMBO_RETRY_PATTERNS = (
    re.compile(
        r"(?:string (?:index|reference)|const-string)[^\n]*"
        r"(?:out of range|too large)[^\n]*"
        r"(?:please |must |should |try to )?use (?:the )?const-string/jumbo",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<!not )(?<!don't )\buse (?:the )?const-string/jumbo\b",
        re.IGNORECASE,
    ),
)


def needs_jumbo_retry(diagnostic: str) -> bool:
    """Only accept an assembler diagnostic that explicitly prescribes jumbo."""
    return any(pattern.search(diagnostic) for pattern in JUMBO_RETRY_PATTERNS)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_map = subparsers.add_parser("validate-map")
    validate_map.add_argument("--map", dest="map_path", type=Path, required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--baksmali", default="baksmali")
    snapshot.add_argument("--artifact", type=Path, required=True)
    snapshot.add_argument("--map", dest="map_path", type=Path, required=True)
    snapshot.add_argument("--manifest-dir", type=Path, required=True)
    snapshot.add_argument("--sentinels", type=Path)
    snapshot.add_argument("--sentinel-output", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--baksmali", default="baksmali")
    verify.add_argument("--artifact", type=Path, required=True)
    verify.add_argument("--map", dest="map_path", type=Path, required=True)
    verify.add_argument("--manifest-dir", type=Path, required=True)
    verify.add_argument("--sentinel-map", type=Path)
    verify.add_argument("--source-artifact", type=Path)
    verify.add_argument("--allowed-additions", type=Path)
    verify.add_argument("--label", required=True)

    jumbo = subparsers.add_parser("needs-jumbo-retry")
    jumbo.add_argument("diagnostic", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate-map":
            load_logical_map(args.map_path)
        elif args.command == "snapshot":
            list_items = lambda kind, spec: run_baksmali_list(
                args.baksmali, kind, spec
            )
            snapshot_logical_dexes(
                args.artifact,
                args.map_path,
                args.manifest_dir,
                list_items,
                sentinel_file=args.sentinels,
                sentinel_output=args.sentinel_output,
            )
        elif args.command == "verify":
            list_items = lambda kind, spec: run_baksmali_list(
                args.baksmali, kind, spec
            )
            verify_logical_dexes(
                args.artifact,
                args.map_path,
                args.manifest_dir,
                list_items,
                label=args.label,
                sentinel_map_path=args.sentinel_map,
                source_artifact=args.source_artifact,
                allowed_additions_path=args.allowed_additions,
            )
        elif args.command == "needs-jumbo-retry":
            try:
                diagnostic = args.diagnostic.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError as error:
                raise ValidationError(
                    f"cannot read smali diagnostic {args.diagnostic}: {error}"
                ) from error
            return 0 if needs_jumbo_retry(diagnostic) else 1
    except ValidationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
