"""Validate the installable package and prevent private deployment artifacts."""

import json
import pathlib
import re
import struct
import unittest

import yaml

ROOT = pathlib.Path(__file__).parents[1]


class DistributionTests(unittest.TestCase):
    def test_manifest_hacs_layout_and_brand(self):
        component = ROOT / "custom_components/econet_cloud"
        manifest = json.loads((component / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], "econet_cloud")
        self.assertEqual(manifest["codeowners"], ["@juras2500"])
        self.assertEqual(manifest["documentation"], "https://github.com/juras2500/ha-econet-cloud")
        self.assertEqual(manifest["issue_tracker"], manifest["documentation"] + "/issues")
        self.assertEqual(len(list((ROOT / "custom_components").iterdir())), 1)
        self.assertEqual(json.loads((ROOT / "hacs.json").read_text())["homeassistant"], "2026.11.2")
        for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
            image = (component / "brand" / name).read_bytes()
            self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", image[16:24]), (size, size))

    def test_translations_have_same_control_keys(self):
        component = ROOT / "custom_components/econet_cloud"
        en = json.loads((component / "strings.json").read_text())
        pl = json.loads((component / "translations/pl.json").read_text())
        for key in ("speed", "operating_mode"):
            self.assertEqual(set(en["entity"]["select"][key]["state"]), set(pl["entity"]["select"][key]["state"]))
        self.assertEqual(len(en["entity"]["select"]["speed"]["state"]), 6)

    def test_no_deployment_artifacts_or_live_credentials(self):
        forbidden_names = ("DEPLOYMENT.md", ".storage", "secrets.yaml", ".backups")
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            self.assertNotIn(path.name, forbidden_names)
            self.assertFalse(path.name.endswith(".dpapi"))
            self.assertFalse(path.name.startswith(("controls-verification-", "controls-test-baseline-", "verification-")))
            if path.is_file() and path.suffix in (".py", ".json", ".yaml", ".yml", ".md"):
                content = path.read_text()
                self.assertIsNone(re.search(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", content), str(path))
                self.assertIsNone(re.search(r"(?:192\.168|10\.\d{1,3})\.\d{1,3}\.\d{1,3}", content), str(path))
                self.assertNotIn("dom_" + "rekuperator_", content)
                self.assertNotIn("sunsynk_" + "sunsynk_", content)

    def test_json_yaml_and_readme_links(self):
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix == ".json":
                json.loads(path.read_text())
            elif path.suffix in (".yaml", ".yml"):
                self.assertIsNotNone(yaml.safe_load(path.read_text()))
            elif path.suffix == ".md":
                for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                    if "://" not in target and not target.startswith("#"):
                        self.assertTrue((path.parent / target.split("#")[0]).exists(), f"Broken local link in {path.name}")
