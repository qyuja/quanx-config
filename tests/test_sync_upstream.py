import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "sync_upstream", Path(__file__).resolve().parents[1] / "tools/sync_upstream.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)

CONFIG = """[general]
server_check_timeout=3000
[server_remote]
# Client subscription settings are retained here.
[dns]
no-ipv6
[policy]
static=兜底分流,proxy,direct
[filter_remote]
https://example.org/old.list, force-policy=direct
[filter_local]
host-suffix,example.com,direct
final,兜底分流
[rewrite_remote]
https://example.org/custom.conf,tag=custom,enabled=true
[mitm]
hostname=-example.com
"""


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.source, self.target = self.parent / "upstream", self.parent / "target"
        self.target.mkdir()
        files = {
            "rule/QuantumultX/Direct/Direct.list": "HOST-SUFFIX,example.com,Direct\n",
            "rule/QuantumultX/Optional/Optional.list": "IP-ASN,12345,Optional\n",
            "rewrite/QuantumultX/AdvertisingLite/AdvertisingLite.conf": "^https://example.com/ads url reject\nhostname=example.com\n",
            "rewrite/QuantumultX/AdvertisingLite/AdvertisingLite.list": "HOST,ads.example.com,AdvertisingLite\n",
            "rewrite/QuantumultX/AdvertisingScript/AdvertisingScript.conf": "^https://example.com/api url script-response-body " + sync.UPSTREAM_RAW + "script/example.js\n",
            "rewrite/QuantumultX/AdvertisingScript/AdvertisingScript.list": "HOST,track.example.com,AdvertisingScript\n",
            "rewrite/QuantumultX/AllInOne/AllInOne.conf": "^https://example.com/ads url reject\n",
            "script/example.js": "$done({});\n",
            "README.md": "Upstream author and sources\n",
            "LICENSE": "Upstream license\n"
        }
        for path, content in files.items():
            sync.write_text(self.source / path, content)
        self.profile = {
            "config": "main.conf",
            "raw_base": "https://raw.githubusercontent.com/example/config/master/",
            "default_policy": "兜底分流",
            "update_interval": 86400,
            "filters": [
                {"path": "rule/QuantumultX/Direct/Direct.list", "tag": "Direct", "policy": "direct"},
                {"path": "rewrite/QuantumultX/AdvertisingLite/AdvertisingLite.list", "tag": "AdBlock", "policy": "reject"}
            ],
            "optional_policies": {},
            "rewrite_enabled": ["AdvertisingLite"]
        }
        sync.write_text(self.target / "profiles/blackmatrix7.json", json.dumps(self.profile))
        sync.write_text(self.target / "main.conf", CONFIG)

    def commit_source(self):
        for command in [["git", "init", "-q"], ["git", "add", "."],
                        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                         "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture"]]:
            subprocess.run(command, cwd=self.source, check=True, capture_output=True)

    def test_sections_preserve_settings_and_custom_resources(self):
        updated = sync.update_section(CONFIG, "filter_remote", "new filters", replace_initial=True)
        updated = sync.update_section(updated, "rewrite_remote", "new rewrites")
        for section in ["general", "server_remote", "dns", "policy", "filter_local", "mitm"]:
            self.assertEqual(sync.section_body(CONFIG, section)[2], sync.section_body(updated, section)[2])
        self.assertIn("https://example.org/custom.conf", updated)
        self.assertNotIn("https://example.org/old.list", updated)
        self.assertEqual(updated, sync.update_section(updated, "filter_remote", "new filters"))
        self.assertEqual(updated, sync.update_section(updated, "rewrite_remote", "new rewrites"))

    def test_partial_or_reversed_markers_fail(self):
        for body in ["# BEGIN blackmatrix7 filter_remote", "# END blackmatrix7 filter_remote\n# BEGIN blackmatrix7 filter_remote"]:
            with self.assertRaises(ValueError):
                sync.update_section("[filter_remote]\n" + body, "filter_remote", "new")

    def test_catalog_contains_every_resource_with_valid_default_policy(self):
        outputs, filters, rewrites, external = sync.render(self.source, self.profile)
        rows = [row for row in filters.splitlines() if row.startswith("https://")]
        self.assertEqual(len(rows), len(sync.filter_paths(self.source)))
        self.assertEqual(len(set(row.split(",", 1)[0] for row in rows)), len(rows))
        self.assertIn("Optional.list, tag=BM规则_Optional-Optional, force-policy=兜底分流", filters)
        self.assertEqual(sum("enabled=true" in row for row in rows), 2)
        self.assertEqual(sum("enabled=true" in row for row in rewrites.splitlines()), 1)
        self.assertEqual(external, [])
        self.assertIn(self.profile["raw_base"] + "script/example.js",
                      outputs["quantumultx/rewrite/AdvertisingScript/AdvertisingScript.conf"])

    def test_enabled_rewrite_requires_paired_reject_filter(self):
        profile = copy.deepcopy(self.profile)
        profile["rewrite_enabled"].append("AdvertisingScript")
        with self.assertRaisesRegex(ValueError, "requires filter"):
            sync.render(self.source, profile)
        profile = copy.deepcopy(self.profile)
        profile["filters"][1]["policy"] = "direct"
        with self.assertRaisesRegex(ValueError, "must use reject"):
            sync.render(self.source, profile)

    def split_profile(self):
        dedicated = "rule/QuantumultX/Binance/Binance.list"
        aggregate = "rule/QuantumultX/Global/Global.list"
        sync.write_text(self.source / dedicated,
                        "HOST-SUFFIX,binance.test,Binance\nHOST,login.example.test,Binance\n")
        sync.write_text(self.source / aggregate,
                        "# NAME: Global\n# AUTHOR: upstream\n# HOST: 2\n# TOTAL: 7\n"
                        "HOST,API.BINANCE.TEST,Global\nHOST,login.example.test,Global\n"
                        "HOST-SUFFIX,BINANCE.TEST,Global\nHOST-SUFFIX,static.binance.test,Global\n"
                        "HOST-SUFFIX,notbinance.test,Global\nHOST-SUFFIX,example.test,Global\n"
                        "IP-ASN,12345,Global\n")
        profile = copy.deepcopy(self.profile)
        profile["filters"][:0] = [
            {"path": dedicated, "tag": "Binance", "policy": "proxy"},
            {"path": aggregate, "tag": "Global", "policy": "兜底分流", "exclude": [dedicated]}
        ]
        return profile, aggregate

    def test_split_filters_remove_owned_hosts_without_changing_upstream(self):
        profile, original = self.split_profile()
        before = (self.source / original).read_bytes()
        outputs, filters, _, _ = sync.render(self.source, profile)
        generated = "quantumultx/filter/Global/Global.list"
        rules = [line for line in outputs[generated].splitlines()
                 if line.strip() and not line.startswith("#")]
        self.assertEqual(rules, ["HOST-SUFFIX,notbinance.test,Global",
                                 "HOST-SUFFIX,example.test,Global", "IP-ASN,12345,Global"])
        self.assertIn("# AUTHOR: upstream", outputs[generated])
        self.assertIn("# TOTAL: 3", outputs[generated])
        self.assertIn("# HOST-SUFFIX: 2", outputs[generated])
        self.assertNotIn("# HOST: 2", outputs[generated])
        self.assertEqual((self.source / original).read_bytes(), before)
        self.assertIn(profile["raw_base"] + generated + ", tag=Global", filters)
        self.assertNotIn(profile["raw_base"] + original + ",", filters)
        self.assertLess(filters.index("tag=Binance"), filters.index("tag=Global"))
        self.assertIn(f"| [{generated}]", outputs["quantumultx/catalog.md"])
        self.assertEqual(len([line for line in filters.splitlines() if line.startswith("https://")]),
                         len(sync.filter_paths(self.source)))

    def test_excluded_filters_must_be_enabled_before_the_aggregate(self):
        profile, _ = self.split_profile()
        for change in ("disabled", "later"):
            with self.subTest(change=change):
                invalid = copy.deepcopy(profile)
                dedicated = invalid["filters"].pop(0)
                if change == "later":
                    invalid["filters"].append(dedicated)
                with self.assertRaisesRegex(ValueError, "must be enabled before"):
                    sync.render(self.source, invalid)

    def test_split_filter_sync_is_idempotent_and_cleans_removed_derivatives(self):
        profile, original = self.split_profile()
        sync.write_text(self.target / "profiles/blackmatrix7.json", json.dumps(profile))
        self.commit_source()
        sync.sync(self.target, self.source)
        sync.check(self.target)
        generated = self.target / "quantumultx/filter/Global/Global.list"
        first = generated.read_bytes()
        sync.sync(self.target, self.source)
        self.assertEqual(generated.read_bytes(), first)
        self.assertEqual((self.target / original).read_bytes(), (self.source / original).read_bytes())
        profile["filters"][1].pop("exclude")
        sync.write_text(self.target / "profiles/blackmatrix7.json", json.dumps(profile))
        sync.sync(self.target, self.source)
        sync.check(self.target)
        self.assertFalse(generated.exists())

    def test_all_in_one_and_components_are_exclusive(self):
        profile = copy.deepcopy(self.profile)
        profile["rewrite_enabled"].append("AllInOne")
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            sync.render(self.source, profile)

    def test_missing_script_fails_before_rendering(self):
        (self.source / "script/example.js").unlink()
        with self.assertRaisesRegex(ValueError, "Missing upstream script"):
            sync.render(self.source, self.profile)

    def test_deleted_upstream_script_uses_verified_historical_copy(self):
        data = (self.source / "script/example.js").read_bytes()
        (self.source / "script/example.js").unlink()
        archived = "dependencies/example.js"
        sync.write_text(self.target / archived, data.decode())
        url = sync.UPSTREAM_RAW + "script/example.js"
        manifest = {url: {"path": archived, "bytes": len(data),
                          "source_url": "https://example.org/pinned/example.js",
                          "sha256": hashlib.sha256(data).hexdigest(),
                          "git_blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}}
        sync.write_text(self.target / "dependencies/manifest.json", json.dumps(manifest))
        profile = copy.deepcopy(self.profile)
        profile["dependency_overrides_file"] = "dependencies/manifest.json"
        outputs, _, _, _ = sync.render(self.source, profile, dependency_root=self.target)
        self.assertIn(profile["raw_base"] + archived,
                      outputs["quantumultx/rewrite/AdvertisingScript/AdvertisingScript.conf"])
        (self.target / archived).write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "Archived dependency changed"):
            sync.render(self.source, profile, dependency_root=self.target)

    def test_unrecoverable_external_script_remains_as_comment(self):
        url = "https://deleted.example.org/script.js"
        path = self.source / "rewrite/QuantumultX/AllInOne/AllInOne.conf"
        path.write_text("^https://example.com/api url script-request-body " + url + "\n")
        profile = copy.deepcopy(self.profile)
        profile["disabled_script_urls"] = [url]
        outputs, _, _, external = sync.render(self.source, profile)
        line = outputs["quantumultx/rewrite/AllInOne/AllInOne.conf"].strip()
        self.assertTrue(line.startswith("# DISABLED:"))
        self.assertIn(url, line)
        self.assertNotIn(url, external)

    def test_snapshot_round_trip_is_idempotent_and_detects_corruption(self):
        self.commit_source()
        sync.sync(self.target, self.source)
        sync.check(self.target)
        first = {str(path.relative_to(self.target)): path.read_bytes()
                 for path in self.target.rglob("*") if path.is_file()}
        sync.sync(self.target, self.source)
        second = {str(path.relative_to(self.target)): path.read_bytes()
                  for path in self.target.rglob("*") if path.is_file()}
        self.assertEqual(first, second)
        sync.write_text(self.target / "rule/QuantumultX/Direct/Direct.list", "HOST,changed.com,Direct\n")
        with self.assertRaisesRegex(ValueError, "Mirror content changed"):
            sync.check(self.target)

    def test_dirty_source_or_nested_checkout_cannot_replace_target(self):
        self.commit_source()
        (self.source / "script/example.js").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "differs from its commit"):
            sync.sync(self.target, self.source)
        self.assertFalse((self.target / "rule").exists())
        with self.assertRaisesRegex(ValueError, "outside the destination"):
            sync.sync(self.target, self.target)

    def test_untracked_upstream_files_are_not_published(self):
        self.commit_source()
        (self.source / "script/untracked.js").write_text("untracked\n")
        with self.assertRaisesRegex(ValueError, "untracked or missing"):
            sync.sync(self.target, self.source)
        self.assertFalse((self.target / "script").exists())

    def test_offline_check_rejects_undefined_policy(self):
        self.commit_source()
        sync.sync(self.target, self.source)
        config = self.target / "main.conf"
        config.write_text(config.read_text().replace("static=兜底分流,proxy,direct", "static=other,proxy,direct"))
        with self.assertRaisesRegex(ValueError, "Undefined policy"):
            sync.check(self.target)


if __name__ == "__main__":
    unittest.main()
