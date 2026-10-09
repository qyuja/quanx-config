import base64
import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / f"tools/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


exporter = load("export_nodes")
publisher = load("publish_subscription")

# Public RFC 7748 test vector, not an operational server credential.
RFC_PRIVATE = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
RFC_PUBLIC = bytes.fromhex("8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.config = {"inbounds": [{
            "type": "vless", "listen_port": 21443,
            "users": [{"uuid": "00000000-0000-0000-0000-000000000000", "flow": "xtls-rprx-vision"}],
            "tls": {"enabled": True, "server_name": "example.com", "reality": {
                "enabled": True, "private_key": base64.urlsafe_b64encode(RFC_PRIVATE).decode().rstrip("="),
                "short_id": ["0123456789abcdef"],
            }},
        }, {
            "type": "anytls", "listen_port": 31443,
            "users": [{"password": "TEST_ONLY_PASSWORD"}],
            "tls": {"enabled": True, "server_name": "example.com"},
        }]}

    def test_reality_public_key_matches_rfc_vector(self):
        expected = base64.urlsafe_b64encode(RFC_PUBLIC).decode().rstrip("=")
        self.assertEqual(exporter.public_key(self.config["inbounds"][0]["tls"]["reality"]["private_key"]), expected)

    def test_native_nodes_preserve_ports_flow_and_secure_tls(self):
        nodes = exporter.render_nodes(self.config, "192.0.2.1", "日本")
        self.assertIn("vless=192.0.2.1:21443", nodes)
        self.assertIn("vless-flow=xtls-rprx-vision", nodes)
        self.assertIn("anytls=192.0.2.1:31443", nodes)
        self.assertIn("tls-verification=true", nodes)
        self.assertNotIn("tls-verification=false", nodes)
        self.assertNotIn(self.config["inbounds"][0]["tls"]["reality"]["private_key"], nodes)
        self.assertIn("tag=日本-AnyTLS", nodes)

    def test_self_signed_anytls_uses_certificate_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            cert = directory / "cert.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                            "-nodes", "-keyout", str(directory / "key.pem"), "-out", str(cert),
                            "-days", "1", "-subj", "/CN=example.com"], check=True, capture_output=True)
            self.config["inbounds"][1]["tls"]["certificate_path"] = str(cert)
            nodes = exporter.render_nodes(self.config, "192.0.2.1", "日本", pin_anytls=True)
            self.assertRegex(nodes, r"tls-pubkey-sha256=[0-9a-f]{64}")
            self.assertIn("tls-verification=true", nodes)

    def test_rejects_ambiguous_users_unsupported_transport_and_plaintext_tls(self):
        for mutation in ("users", "transport", "tls"):
            with self.subTest(mutation=mutation):
                config = copy.deepcopy(self.config)
                if mutation == "users":
                    config["inbounds"][0]["users"].append(config["inbounds"][0]["users"][0])
                elif mutation == "transport":
                    config["inbounds"][0]["transport"] = {"type": "grpc"}
                else:
                    config["inbounds"][1]["tls"]["enabled"] = False
                with self.assertRaises(ValueError):
                    exporter.render_nodes(config, "192.0.2.1", "日本")

    def test_rejects_native_delimiter_in_credentials(self):
        self.config["inbounds"][1]["users"][0]["password"] = "TEST,tag=injected"
        with self.assertRaises(ValueError):
            exporter.render_nodes(self.config, "192.0.2.1", "日本")

    def test_file_output_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "nodes.conf"
            exporter.write_private(file, "test-only\n")
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)


class PublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        raw = "https://raw.githubusercontent.com/example/config/master/"
        files = {
            "profiles/blackmatrix7.json": json.dumps({"raw_base": raw, "config": "main.conf"}),
            "main.conf": "[server_remote]\nhttps://sub.example.com/quanx/nodes.conf,tag=自建\n[filter_remote]\n" + raw + "rule/one.list\n",
            "rule/one.list": "HOST,example.com,direct\n",
            "rewrite/original.conf": "# Original author retained\n",
            "script/one.js": "$done({});\n",
            "dependencies/manifest.json": "{}\n",
            "LICENSES/owner.txt": "Original license\n",
            "UPSTREAM_README.md": "Original author attribution\n",
            "quantumultx/rewrite/one.conf": "# Original author retained\n^https://example.com url script-response-body " + raw + "script/one.js\n",
            "quantumultx/filter_remote.conf": raw + "rule/one.list,tag=one\n",
            "tools/sync_upstream.py": "print('Fixture snapshot validation passed')\n",
        }
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        for command in (["git", "init", "-q"], ["git", "add", "."],
                        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--no-gpg-sign", "-qm", "Fixture"]):
            subprocess.run(command, cwd=self.repo, check=True, capture_output=True)
        self.nodes = self.root / "nodes.conf"
        self.nodes.write_text("anytls=192.0.2.1:31443,password=TEST_ONLY_PASSWORD,tls-verification=true,tag=日本-AnyTLS\n")
        self.settings = {
            "repository": str(self.repo), "destination": str(self.root / "releases"),
            "current": str(self.root / "current"), "public_base": "https://sub.example.com/quanx",
            "access_key": "TEST_ONLY_BEARER_KEY_FOR_UNIT_TESTS",
        }
        # These publication fixtures omit the full upstream manifest; its checks have separate tests.
        self.validation = patch.object(publisher, "validate_repository")
        self.validation.start()
        self.addCleanup(self.validation.stop)

    def test_complete_publication_rewrites_nested_urls_without_exposing_git(self):
        self.assertTrue(publisher.publish(self.settings, [self.nodes]))
        current = self.root / "current"
        prefix = publisher.private_base(self.settings)
        self.assertIn(prefix + "nodes.conf", (current / "main.conf").read_text())
        self.assertIn(prefix + "rule/one.list", (current / "main.conf").read_text())
        self.assertIn(prefix + "script/one.js", (current / "quantumultx/rewrite/one.conf").read_text())
        self.assertEqual((current / "rule/one.list").read_bytes(), (self.repo / "rule/one.list").read_bytes())
        self.assertEqual((current / "UPSTREAM_README.md").read_bytes(), (self.repo / "UPSTREAM_README.md").read_bytes())
        self.assertFalse((current / ".git").exists())
        self.assertEqual((current / "nodes.conf").stat().st_mode & 0o777, 0o640)

    def test_identical_inputs_keep_the_same_publication(self):
        publisher.publish(self.settings, [self.nodes])
        target = (self.root / "current").resolve()
        self.assertFalse(publisher.publish(self.settings, [self.nodes]))
        self.assertEqual((self.root / "current").resolve(), target)

    def test_private_checkout_permissions_do_not_hide_published_resources(self):
        (self.repo / "rule").chmod(0o700)
        (self.repo / "rule/one.list").chmod(0o600)
        previous = os.umask(0o077)
        try:
            publisher.publish(self.settings, [self.nodes])
        finally:
            os.umask(previous)
        self.assertEqual((self.root / "current/rule").stat().st_mode & 0o7777, 0o2750)
        self.assertEqual((self.root / "current/rule/one.list").stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.root / "current/quantumultx/rewrite").stat().st_mode & 0o7777, 0o2750)
        self.assertEqual((self.root / "releases").stat().st_mode & 0o7777, 0o2750)

    def test_source_mutation_cannot_change_a_live_release(self):
        publisher.publish(self.settings, [self.nodes])
        source = self.repo / "rule/one.list"
        previous = (self.root / "current/rule/one.list").read_bytes()
        source.write_text("changed working copy\n")
        self.assertEqual((self.root / "current/rule/one.list").read_bytes(), previous)
        with self.assertRaises(ValueError):
            publisher.publish(self.settings, [self.nodes])

    def test_repository_python_is_never_executed_during_validation(self):
        self.validation.stop()
        marker = self.root / "untrusted-code-ran"
        (self.repo / "tools/sync_upstream.py").write_text(
            "from pathlib import Path\n" + f"Path({str(marker)!r}).touch()\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit",
                        "--no-gpg-sign", "-qm", "Untrusted fixture code"], cwd=self.repo, check=True, capture_output=True)
        with self.assertRaises(ValueError):
            publisher.publish(self.settings, [self.nodes])
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / "current").exists())

    def test_invalid_nodes_leave_last_good_publication_in_place(self):
        publisher.publish(self.settings, [self.nodes])
        previous = (self.root / "current").resolve()
        self.nodes.write_text("anytls=192.0.2.1:31443,password=TEST_ONLY_PASSWORD,tls-verification=false,tag=日本\n")
        with self.assertRaises(ValueError):
            publisher.publish(self.settings, [self.nodes])
        self.assertEqual((self.root / "current").resolve(), previous)

    def test_duplicate_tags_and_empty_sources_are_rejected(self):
        with self.assertRaises(ValueError):
            publisher.collect_nodes([self.nodes, self.nodes])
        self.nodes.write_text("")
        with self.assertRaises(ValueError):
            publisher.collect_nodes([self.nodes])

    def test_nginx_limits_the_private_namespace_and_disables_url_logging(self):
        snippet = publisher.nginx_snippet(self.settings)
        self.assertIn("location ^~ /quanx/TEST_ONLY_BEARER_KEY_FOR_UNIT_TESTS/", snippet)
        self.assertIn("location ^~ /quanx/", snippet)
        self.assertIn("return 404", snippet)
        self.assertEqual(snippet.count("access_log off"), 2)
        self.assertEqual(snippet.count("error_log /dev/null"), 2)
        self.assertIn('Cache-Control "private, no-store"', snippet)

    def test_private_snippet_is_atomic_under_public_umask(self):
        output = self.root / "nginx.conf"
        output.write_text("previous public placeholder\n")
        output.chmod(0o644)
        replace = os.replace
        observed = []

        def check_private(source, target):
            observed.append(Path(source).stat().st_mode & 0o777)
            self.assertEqual(observed[-1], 0o600)
            return replace(source, target)

        previous = os.umask(0o022)
        try:
            with patch.object(publisher.os, "replace", side_effect=check_private):
                publisher.write_private_text(output, publisher.nginx_snippet(self.settings))
        finally:
            os.umask(previous)
        self.assertEqual(observed, [0o600])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertIn(self.settings["access_key"], output.read_text())

    def test_invalid_key_and_unsafe_nginx_paths_are_rejected(self):
        for key in ("short", "invalid;" + "x" * 32):
            settings = dict(self.settings, access_key=key)
            with self.assertRaises(ValueError):
                publisher.private_base(settings)
        with self.assertRaises(ValueError):
            publisher.nginx_snippet(dict(self.settings, current="/tmp/path;injection"))


if __name__ == "__main__":
    unittest.main()
