from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectSetupTests(unittest.TestCase):
    def test_python_version_matches_docker_and_local_version(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        runtime = (ROOT / ".python-version").read_text(encoding="utf-8").strip()

        docker_version = re.search(r"^FROM python:(\d+\.\d+\.\d+)-slim$", dockerfile, re.MULTILINE)
        runtime_version = re.fullmatch(r"(\d+\.\d+\.\d+)", runtime)

        self.assertIsNotNone(docker_version)
        self.assertIsNotNone(runtime_version)
        self.assertEqual(docker_version.group(1), runtime_version.group(1))

    def test_credentials_are_mounted_read_only_in_local_compose(self):
        compose = (ROOT / "docker-compose.yaml").read_text(encoding="utf-8")

        self.assertIn(
            "./google-credentials.json:/app/google-credentials.json:ro",
            compose,
        )

    def test_secret_files_are_ignored_by_git_and_docker(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        for ignored_file in (".env", "google-credentials.json", "token.json"):
            with self.subTest(ignored_file=ignored_file):
                self.assertIn(ignored_file, gitignore)
                self.assertIn(ignored_file, dockerignore)


if __name__ == "__main__":
    unittest.main()
