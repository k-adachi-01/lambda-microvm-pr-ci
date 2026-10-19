"""Hostile-PR probe: the guest test itself tries to find AWS credentials and
control-plane access. Written as an assertion suite — it PASSES only when the
VM is creds-free, so a green check is evidence of the boundary."""
import os
import socket
import unittest
import urllib.request


class TestNoAwsCredentials(unittest.TestCase):
    def test_no_aws_env(self):
        leaks = [k for k in os.environ if k.startswith(("AWS_", "AMAZON_"))]
        self.assertEqual(leaks, [], f"AWS env vars present in guest: {leaks}")

    def test_no_aws_config_files(self):
        import glob
        paths = glob.glob(os.path.expanduser("~/.aws/*")) + glob.glob("/root/.aws/*")
        self.assertEqual(paths, [], f"aws config files present: {paths}")

    def test_no_imds(self):
        try:
            urllib.request.urlopen("http://169.254.169.254/latest/meta-data/", timeout=2)
        except Exception:
            return  # unreachable — expected
        self.fail("IMDS reachable from inside the MicroVM")

    def test_no_metadata_on_169254170253(self):
        # Lambda-style metadata endpoint probe
        try:
            urllib.request.urlopen("http://169.254.170.2/v2/credentials", timeout=2)
        except Exception:
            return
        self.fail("task-metadata endpoint reachable from inside the MicroVM")

    def test_no_process_environ_leak(self):
        import glob, re
        leaks = []
        for env in glob.glob("/proc/[0-9]*/environ"):
            try:
                data = open(env, "rb").read().decode(errors="replace")
            except Exception:
                continue
            if re.search(r"AWS_(SECRET_ACCESS_KEY|SESSION_TOKEN|ACCESS_KEY_ID)=", data):
                leaks.append(env)
        self.assertEqual(leaks, [], f"creds visible via /proc: {leaks}")


if __name__ == "__main__":
    unittest.main()
