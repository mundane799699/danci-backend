import unittest
from pathlib import Path

from scripts.configure_douyin_nginx import insert_server_include


INCLUDE = "/www/server/nginx/conf/snippets/douyin-protected-videos.conf"


class NginxConfigTests(unittest.TestCase):
    def test_inserts_include_only_in_matching_server_and_is_idempotent(self):
        source = """server {
  server_name other.example;
  location / { proxy_pass http://127.0.0.1:1; }
}

server {
  server_name danci.mundane.ink;
  location / {
    proxy_pass http://127.0.0.1:3002;
  }
}
"""
        updated = insert_server_include(source)
        directive = f"  include {INCLUDE};\n"
        self.assertEqual(updated.count(directive), 1)
        self.assertGreater(
            updated.index(directive),
            updated.index("server_name danci.mundane.ink;"),
        )
        self.assertEqual(insert_server_include(updated), updated)

    def test_rejects_missing_ambiguous_or_unbalanced_server(self):
        with self.assertRaises(ValueError):
            insert_server_include("server {\n  server_name other.example;\n}\n")
        with self.assertRaises(ValueError):
            insert_server_include(
                "server {\n  server_name danci.mundane.ink;\n}\n" * 2
            )
        with self.assertRaises(ValueError):
            insert_server_include("server {\n  server_name danci.mundane.ink;\n")

    def test_protected_location_is_internal_and_does_not_follow_symlinks(self):
        snippet = (
            Path(__file__).parents[1]
            / "deploy"
            / "nginx"
            / "douyin-protected-videos.conf"
        ).read_text(encoding="utf-8")
        self.assertIn("internal;", snippet)
        self.assertIn("alias /data/remove-watermark/ready/;", snippet)
        self.assertIn("sendfile on;", snippet)
        self.assertIn("disable_symlinks on;", snippet)


if __name__ == "__main__":
    unittest.main()
