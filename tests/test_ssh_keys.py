import unittest

from bootstrap.ssh import parse_github_keys, ssh_fingerprint


KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINBbCfb+WmiX3sbFKT8weE9KCJ66FtN3C42nxEkueumS fixture"


class SshKeyTests(unittest.TestCase):
    def test_parser_deduplicates_valid_keys_and_fingerprint_is_stable(self):
        self.assertEqual(parse_github_keys(f"{KEY}\n{KEY}\n"), (KEY,))
        self.assertEqual(
            ssh_fingerprint(KEY),
            "SHA256:+HZV1Z3cJfpHMojtVaG58byhDxnxqDWAvm+6BTT0tEo",
        )

    def test_parser_rejects_empty_and_malformed_payloads(self):
        with self.assertRaisesRegex(RuntimeError, "no SSH"):
            parse_github_keys("\n")
        with self.assertRaisesRegex(RuntimeError, "invalid SSH"):
            parse_github_keys("ssh-ed25519 not-base64")


if __name__ == "__main__":
    unittest.main()
