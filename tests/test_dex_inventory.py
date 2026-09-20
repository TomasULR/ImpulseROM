from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "internal" / "dex_inventory.py"
SPEC = importlib.util.spec_from_file_location("dex_inventory", SCRIPT)
assert SPEC and SPEC.loader
DEX_INVENTORY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DEX_INVENTORY
SPEC.loader.exec_module(DEX_INVENTORY)


DEX040 = b"dex\n040\x00" + b"\x00" * 120


class FakeBaksmaliList:
    def __init__(self) -> None:
        self.dex_entries: dict[str, list[str]] = {}
        self.inventories: dict[str, dict[str, list[str]]] = {}

    def __call__(self, kind: str, dex_spec: str) -> list[str]:
        if kind == "dex":
            return list(self.dex_entries[dex_spec])
        return list(self.inventories[dex_spec][kind])


class DexInventoryGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source-services.jar"
        self.output = self.root / "assembled"
        self.package = self.root / "packaged-services.jar"
        self.map_path = self.root / "logical_dex_map.tsv"
        self.manifest_dir = self.root / "inventories"
        self.sentinel_file = self.root / "sentinels.txt"
        self.sentinel_map = self.root / "sentinel_map.tsv"
        self.allowed_additions = self.root / "allowed-additions.tsv"
        self.list_items = FakeBaksmaliList()

        self.source.write_bytes(b"fake source archive")
        self.output.mkdir()
        (self.output / "classes.dex").write_bytes(DEX040)
        (self.output / "classes2.dex").write_bytes(DEX040)
        with zipfile.ZipFile(self.package, "w") as archive:
            archive.writestr("classes.dex", DEX040)
            archive.writestr("classes2.dex", DEX040)

        self.map_path.write_text(
            "index\tsource_entry\tsmali_dir\toutput_dex\n"
            "1\tclasses.dex\tsmali\tclasses.dex\n"
            "2\tclasses.dex/2\tsmali_classes2\tclasses2.dex\n",
            encoding="utf-8",
        )

        self.sentinels = [
            "Lcom/android/server/pm/PackageManagerService;",
            "Lcom/android/server/pm/InstallPackageHelper;",
            "Lcom/android/server/wm/WindowManagerService;",
        ]
        self.sentinel_file.write_text(
            "# boot-critical logical placement\n"
            + "\n".join(self.sentinels)
            + "\n",
            encoding="utf-8",
        )

        self.unit1 = {
            "classes": ["Lcore/A;", "Lcore/B;"],
            "methods": ["Lcore/A;->run()V", "Lcore/B;->boot(I)Z"],
            "fields": ["Lcore/A;->STATE:I"],
            "types": ["I", "Lcore/A;", "Lcore/B;", "V", "Z"],
        }
        self.unit2 = {
            "classes": [*self.sentinels, "Lserver/Other;"],
            "methods": [
                "Lcom/android/server/pm/PackageManagerService;->main()V",
                "Lcom/android/server/wm/WindowManagerService;->start()V",
            ],
            "fields": [
                "Lcom/android/server/pm/PackageManagerService;->mReady:Z"
            ],
            "types": [*self.sentinels, "Lserver/Other;", "V", "Z"],
        }

        # baksmali's ZIP container uses lexical ordering. Feed /2 first to
        # prove that the explicit logical map, not tool listing order, is the
        # authority.
        self.list_items.dex_entries[str(self.source)] = [
            "classes.dex/2",
            "classes.dex",
        ]
        self.list_items.dex_entries[str(self.package)] = [
            "classes2.dex",
            "classes.dex",
        ]
        self.add_inventory(self.source, "classes.dex", self.unit1)
        self.add_inventory(self.source, "classes.dex/2", self.unit2)
        self.add_inventory(self.output, "classes.dex", self.unit1, reverse=True)
        self.add_inventory(self.output, "classes2.dex", self.unit2, reverse=True)
        self.add_inventory(self.package, "classes.dex", self.unit1, reverse=True)
        self.add_inventory(self.package, "classes2.dex", self.unit2, reverse=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def add_inventory(
        self,
        artifact: Path,
        entry: str,
        inventory: dict[str, list[str]],
        *,
        reverse: bool = False,
    ) -> None:
        dex_spec = (
            str(artifact / entry) if artifact.is_dir() else f"{artifact}/{entry}"
        )
        self.list_items.inventories[dex_spec] = {
            kind: list(reversed(values)) if reverse else list(values)
            for kind, values in inventory.items()
        }

    def snapshot(self) -> None:
        DEX_INVENTORY.snapshot_logical_dexes(
            self.source,
            self.map_path,
            self.manifest_dir,
            self.list_items,
            sentinel_file=self.sentinel_file,
            sentinel_output=self.sentinel_map,
        )

    def test_roundtrip_records_all_inventories_and_checks_both_artifacts(self) -> None:
        self.snapshot()

        manifest = DEX_INVENTORY.load_inventory(
            self.manifest_dir / "logical-2.inventory.tsv"
        )
        self.assertEqual(set(DEX_INVENTORY.INVENTORY_KINDS), set(manifest))
        self.assertEqual(len(self.unit2["classes"]), manifest["classes"].count)
        self.assertRegex(manifest["methods"].sha256, r"^[0-9a-f]{64}$")

        sentinel_rows = DEX_INVENTORY.load_sentinel_map(self.sentinel_map)
        self.assertTrue(sentinel_rows)
        self.assertTrue(all(item.logical_index == 2 for item in sentinel_rows))
        self.assertTrue(
            all(item.source_entry == "classes.dex/2" for item in sentinel_rows)
        )
        self.assertTrue(all(item.output_dex == "classes2.dex" for item in sentinel_rows))

        DEX_INVENTORY.verify_logical_dexes(
            self.output,
            self.map_path,
            self.manifest_dir,
            self.list_items,
            label="pre-package",
            sentinel_map_path=self.sentinel_map,
        )
        DEX_INVENTORY.verify_logical_dexes(
            self.package,
            self.map_path,
            self.manifest_dir,
            self.list_items,
            label="packaged",
            sentinel_map_path=self.sentinel_map,
        )

    def test_equal_count_substitution_fails_on_inventory_sha(self) -> None:
        self.snapshot()
        output_spec = str(self.output / "classes.dex")
        self.list_items.inventories[output_spec]["classes"] = [
            "Lcore/A;",
            "Lcore/Substituted;",
        ]

        with self.assertRaisesRegex(
            DEX_INVENTORY.ValidationError,
            r"classes: expected count=2 .*actual count=2",
        ):
            DEX_INVENTORY.verify_logical_dexes(
                self.output,
                self.map_path,
                self.manifest_dir,
                self.list_items,
                label="equal-count substitution",
            )

    def test_exact_scoped_method_additions_are_allowed_without_losses(self) -> None:
        self.snapshot()
        added_method = "Lserver/Other;->compat()Z"
        self.allowed_additions.write_text(
            "logical_index\tkind\titem\n"
            f"2\tmethods\t{added_method}\n",
            encoding="utf-8",
        )
        output_spec = str(self.output / "classes2.dex")
        self.list_items.inventories[output_spec]["methods"].append(added_method)

        DEX_INVENTORY.verify_logical_dexes(
            self.output,
            self.map_path,
            self.manifest_dir,
            self.list_items,
            label="scoped method addition",
            source_artifact=self.source,
            allowed_additions_path=self.allowed_additions,
        )

    def test_scoped_additions_reject_unlisted_addition_or_source_loss(self) -> None:
        self.snapshot()
        allowed_method = "Lserver/Other;->compat()Z"
        self.allowed_additions.write_text(
            "logical_index\tkind\titem\n"
            f"2\tmethods\t{allowed_method}\n",
            encoding="utf-8",
        )
        output_spec = str(self.output / "classes2.dex")
        self.list_items.inventories[output_spec]["methods"].extend(
            [allowed_method, "Lserver/Other;->unexpected()V"]
        )
        self.list_items.inventories[output_spec]["fields"].clear()

        with self.assertRaisesRegex(
            DEX_INVENTORY.ValidationError,
            r"DEX allowed-additions mismatch.*unexpected.*removed",
        ):
            DEX_INVENTORY.verify_logical_dexes(
                self.output,
                self.map_path,
                self.manifest_dir,
                self.list_items,
                label="unlisted change",
                source_artifact=self.source,
                allowed_additions_path=self.allowed_additions,
            )

    def test_extra_output_dex_fails_closed(self) -> None:
        self.snapshot()
        (self.output / "classes3.dex").write_bytes(DEX040)

        with self.assertRaisesRegex(
            DEX_INVENTORY.ValidationError, "assembled DEX entries do not match"
        ):
            DEX_INVENTORY.verify_logical_dexes(
                self.output,
                self.map_path,
                self.manifest_dir,
                self.list_items,
                label="extra dex",
            )

    def test_dex041_container_cannot_hide_inside_prepackage_output(self) -> None:
        self.snapshot()
        (self.output / "classes2.dex").write_bytes(
            b"dex\n041\x00" + b"\x00" * 120
        )

        with self.assertRaisesRegex(
            DEX_INVENTORY.ValidationError, "DEX 041 containers must be split"
        ):
            DEX_INVENTORY.verify_logical_dexes(
                self.output,
                self.map_path,
                self.manifest_dir,
                self.list_items,
                label="hidden container",
            )

    def test_sentinel_location_exposes_logical_index_move(self) -> None:
        logical_map = DEX_INVENTORY.load_logical_map(self.map_path)
        expected = DEX_INVENTORY.locate_sentinels(
            self.source,
            logical_map,
            [self.sentinels[0]],
            self.list_items,
            source=True,
        )

        first_output = str(self.output / "classes.dex")
        second_output = str(self.output / "classes2.dex")
        self.list_items.inventories[first_output]["classes"].append(
            self.sentinels[0]
        )
        self.list_items.inventories[second_output]["classes"].remove(
            self.sentinels[0]
        )
        actual = DEX_INVENTORY.locate_sentinels(
            self.output,
            logical_map,
            [self.sentinels[0]],
            self.list_items,
            source=False,
        )

        self.assertEqual(2, expected[0].logical_index)
        self.assertEqual(1, actual[0].logical_index)
        self.assertNotEqual(expected, actual)

    def test_map_rejects_missing_container_index(self) -> None:
        self.map_path.write_text(
            "index\tsource_entry\tsmali_dir\toutput_dex\n"
            "1\tclasses.dex\tsmali\tclasses.dex\n"
            "2\tclasses.dex/3\tsmali_classes2\tclasses2.dex\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            DEX_INVENTORY.ValidationError, "container DEX indexes.*contiguous"
        ):
            DEX_INVENTORY.load_logical_map(self.map_path)

    def test_jumbo_retry_requires_explicit_prescription(self) -> None:
        self.assertTrue(
            DEX_INVENTORY.needs_jumbo_retry(
                "String index out of range; please use const-string/jumbo"
            )
        )
        for diagnostic in (
            "Unsigned short value out of range: 65536",
            "syntax error near const-string v0, value",
            "Method reference index is too large",
            "Do not use const-string/jumbo for this instruction",
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assertFalse(DEX_INVENTORY.needs_jumbo_retry(diagnostic))


if __name__ == "__main__":
    unittest.main()
