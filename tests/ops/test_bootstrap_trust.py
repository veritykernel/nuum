"""Offline checks for the source trust anchors and no-trust bootstrap hold."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class BootstrapTrustTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nuum-bootstrap-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_verifier(self, name: str, option: str, fixture: str):
        script = ROOT / "ops" / name
        source = FIXTURES / fixture
        accepted = subprocess.run(("bash", str(script), option, str(source)), capture_output=True, text=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        altered = self.root / fixture
        altered.write_bytes(source.read_bytes() + b"\n# altered\n")
        rejected = subprocess.run(("bash", str(script), option, str(altered)), capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)

    def test_reviewed_caddy_key_and_tampered_key(self):
        self.run_verifier("install_caddy_signed.sh", "--verify-key", "caddy-stable.asc")

    def test_reviewed_cloudflare_ca_and_tampered_ca(self):
        self.run_verifier("install_cloudflare_aop_ca.sh", "--verify-file", "authenticated-origin-pull-ca.pem")

    def test_bootstrap_exits_before_network_without_verified_host_keys(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        secret_tool = fake_bin / "nuum-secrets-env"
        secret_tool.write_text("#!/bin/sh\nexit 0\n")
        secret_tool.chmod(0o700)
        marker = self.root / "network-attempted"
        for name in ("ssh", "hcloud", "curl"):
            fake = fake_bin / name
            fake.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 97\n")
            fake.chmod(0o700)
        environment = {
            **os.environ,
            "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
            "NUUM_KNOWN_HOSTS": str(self.root / "missing-known-hosts"),
            "HCLOUD_TOKEN": "fixture", "CF_API_TOKEN": "fixture", "CF_ZONE_ID": "fixture",
            "ORIGIN_CERT_PEM_B64": "Zml4dHVyZQ==", "ORIGIN_CERT_KEY_B64": "Zml4dHVyZQ==",
        }
        held = subprocess.run(
            ("bash", str(ROOT / "ops" / "bootstrap_v2.sh")),
            cwd=ROOT, env=environment, capture_output=True, text=True,
        )
        self.assertNotEqual(held.returncode, 0)
        self.assertIn("NUUM_KNOWN_HOSTS", held.stderr)
        self.assertFalse(marker.exists())

    def test_rendered_remote_blocks_parse_with_strict_storage_trust(self):
        source = (ROOT / "ops" / "bootstrap_v2.sh").read_text()
        variables = (
            "SSH_USER=monkey; SB_MOUNT_POINT=/mnt/storagebox; SB_USER=u490628; "
            "SB_HOST=u490628.your-storagebox.de; "
            "SB_KNOWN_HOSTS_REMOTE=/etc/ssh/nuum_storagebox_known_hosts; "
            "RELAY_FQDN=relay.example.test; RELAY_BACKEND_HOST=127.0.0.1; "
            "RELAY_BACKEND_PORT=8080; ORIGIN_CERT_PEM_B64=Zml4dHVyZQ==; "
            "ORIGIN_CERT_KEY_B64=Zml4dHVyZQ==; "
        )
        for name in ("TLS_BLOCK", "SB_SETUP"):
            match = re.search(r"(?ms)^" + name + r'=\".*?^\"\n', source)
            self.assertIsNotNone(match)
            rendered = subprocess.run(
                ("bash", "-c", variables + match.group(0) + f'printf %s "${name}"'),
                capture_output=True, text=True, check=True,
            ).stdout
            parsed = subprocess.run(("bash", "-n"), input=rendered, capture_output=True, text=True)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            if name == "SB_SETUP":
                self.assertIn("StrictHostKeyChecking=yes", rendered)
                self.assertIn("SHA256:XqONwb1S0zuj5A1CDxpOSuD2hnAArV1A3wKY7Z3sdgM", rendered)

    def test_bootstrap_retires_legacy_source_before_lake_packages_and_hides_token(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        (fake_bin / "nuum-secrets-env").write_text("#!/bin/sh\nexit 0\n")
        (fake_bin / "ssh-keygen").write_text("#!/bin/sh\nexit 0\n")
        for name in ("nuum-secrets-env", "ssh-keygen"):
            (fake_bin / name).chmod(0o700)
        fake_command = r'''#!/usr/bin/env python3
import json
import os
import sys

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
entry = {"command": name, "args": args}
if name == "ssh":
    if args[-1] == "bash -Eeuo pipefail -s":
        entry["body"] = sys.stdin.read()
    elif args[-2:] == ["hostname", "-I"]:
        print("10.0.0.4")
    else:
        print("mock-host")
elif name == "hcloud":
    if args[:2] == ["firewall", "list"]:
        print("1 nuum-relay-fw\n2 nuum-exec-fw")
    elif args[:2] == ["floating-ip", "list"]:
        print("3 nuum-exec-fip-ash-1")
    elif args[:2] == ["floating-ip", "describe"]:
        print('{"ip":"203.0.113.1"}')
    elif args[:2] == ["server", "list"]:
        print("4 10.0.0.4")
elif name == "curl":
    entry["stdin"] = sys.stdin.read()
    if "-X" not in args:
        print('{"result":[{"id":"record-1"}]}')
    else:
        print('{"success":true}')
with open(os.environ["MOCK_LOG"], "a", encoding="utf-8") as out:
    out.write(json.dumps(entry) + "\n")
'''
        for name in ("ssh", "hcloud", "curl"):
            fake = fake_bin / name
            fake.write_text(fake_command)
            fake.chmod(0o700)
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text("verified fixture host key\n")
        log = self.root / "calls.jsonl"
        fixture_token = "fixture-token-not-for-argv"
        environment = {
            **os.environ,
            "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
            "MOCK_LOG": str(log), "NUUM_KNOWN_HOSTS": str(known_hosts),
            "HCLOUD_TOKEN": "fixture", "CF_API_TOKEN": fixture_token, "CF_ZONE_ID": "fixture",
            "ORIGIN_CERT_PEM_B64": "Zml4dHVyZQ==", "ORIGIN_CERT_KEY_B64": "Zml4dHVyZQ==",
        }
        result = subprocess.run(
            ("bash", str(ROOT / "ops" / "bootstrap_v2.sh")),
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        lake_scripts = [call["body"] for call in calls if call["command"] == "ssh"
                        and "monkey@lake" in call["args"] and "body" in call]
        self.assertIn("caddy.list.disabled", lake_scripts[0])
        self.assertIn("apt-get update", lake_scripts[0])
        self.assertIn("unattended-upgrades", lake_scripts[1])
        self.assertIn("apt-get install -y ufw", lake_scripts[2])
        mount = next(script for script in lake_scripts if "storagebox.mount" in script)
        self.assertNotIn("allow_other", mount)
        self.assertNotIn("users,", mount)
        for call in (call for call in calls if call["command"] == "curl"):
            self.assertNotIn(fixture_token, " ".join(call["args"]))
            self.assertIn("--header", call["args"])
            self.assertIn("@-", call["args"])
            self.assertEqual(call["stdin"], f"Authorization: Bearer {fixture_token}\n")


if __name__ == "__main__":
    unittest.main()
