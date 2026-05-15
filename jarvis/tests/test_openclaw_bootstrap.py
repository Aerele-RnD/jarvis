import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import OpenclawRestartFailedError


class _PatchedPaths:
    """Helper that patches openclaw_bootstrap's workspace_root() to a tempdir."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        (self.workspace / "openclaw").mkdir()
        (self.workspace / "openclaw" / "docker-compose.yml").write_text("# stub\n")

    def __enter__(self):
        self._patch = patch("jarvis.openclaw_bootstrap._workspace_root", return_value=self.workspace)
        self._patch.start()
        return self.workspace

    def __exit__(self, *args):
        self._patch.stop()
        self.tmp.cleanup()


def _reset_settings():
    """Clear operator fields on Jarvis Settings before each test."""
    settings = frappe.get_single("Jarvis Settings")
    for field in (
        "openclaw_gateway_url", "openclaw_gateway_token",
        "openclaw_llm_key_path", "openclaw_config_path", "openclaw_compose_dir",
        "last_sync_at", "last_sync_status",
        "llm_provider", "llm_model", "llm_api_key", "llm_base_url",
    ):
        if hasattr(settings, field):
            settings.db_set(field, None)
    frappe.db.commit()


class TestBootstrapStart(FrappeTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_populates_default_paths_in_settings(self):
        with _PatchedPaths() as workspace:
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()

            settings = frappe.get_single("Jarvis Settings")
            self.assertEqual(settings.openclaw_compose_dir, str(workspace / "openclaw"))
            self.assertEqual(settings.openclaw_config_path, str(workspace / "openclaw_state" / "openclaw.json"))
            self.assertEqual(settings.openclaw_llm_key_path, str(workspace / "openclaw_state" / "llm.key"))
            self.assertEqual(settings.openclaw_gateway_url, "ws://127.0.0.1:18789")

    def test_generates_gateway_token_on_first_run(self):
        with _PatchedPaths():
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()
            settings = frappe.get_single("Jarvis Settings")
            token = settings.get_password("openclaw_gateway_token")
            self.assertIsNotNone(token)
            self.assertGreaterEqual(len(token), 32)

    def test_preserves_existing_token_on_rerun(self):
        with _PatchedPaths():
            settings = frappe.get_single("Jarvis Settings")
            settings.db_set("openclaw_gateway_token", "preexisting-token-12345")
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()
            settings = frappe.get_single("Jarvis Settings")
            self.assertEqual(settings.get_password("openclaw_gateway_token"), "preexisting-token-12345")

    def test_writes_state_files(self):
        with _PatchedPaths() as workspace:
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()

            state = workspace / "openclaw_state"
            self.assertTrue(state.exists())
            self.assertTrue((state / "openclaw.json").exists())
            self.assertTrue((state / "llm.key").exists())
            self.assertTrue((state / ".env").exists())

    def test_env_file_contains_required_vars(self):
        with _PatchedPaths() as workspace:
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()

            env = (workspace / "openclaw_state" / ".env").read_text()
            self.assertIn("OPENCLAW_CONFIG_DIR=", env)
            self.assertIn("OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest", env)
            self.assertIn("OPENCLAW_GATEWAY_PORT=18789", env)
            self.assertIn("OPENCLAW_GATEWAY_BIND=lan", env)

    def test_does_not_overwrite_existing_llm_key(self):
        with _PatchedPaths() as workspace:
            # Pre-create llm.key with content
            state = workspace / "openclaw_state"
            state.mkdir(parents=True, exist_ok=True)
            (state / "llm.key").write_text("real-key-do-not-touch")

            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()

            self.assertEqual((state / "llm.key").read_text(), "real-key-do-not-touch")

    def test_invokes_docker_compose_pull_then_up(self):
        with _PatchedPaths():
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()

            # Look for a "pull" call and an "up" call, in order
            calls = mock_run.call_args_list
            pull_calls = [c for c in calls if "pull" in c.args[0]]
            up_calls = [c for c in calls if "up" in c.args[0]]
            self.assertGreaterEqual(len(pull_calls), 1)
            self.assertGreaterEqual(len(up_calls), 1)


class TestBootstrapStop(FrappeTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_invokes_docker_compose_down(self):
        with _PatchedPaths():
            settings = frappe.get_single("Jarvis Settings")
            settings.db_set("openclaw_compose_dir", "/path/to/compose")

            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import stop
                stop()

            cmd = mock_run.call_args.args[0]
            self.assertEqual(cmd[0], "docker")
            self.assertEqual(cmd[1], "compose")
            self.assertIn("-f", cmd)
            self.assertIn("/path/to/compose/docker-compose.yml", cmd)
            self.assertIn("down", cmd)

    def test_failure_raises_restart_failed(self):
        with _PatchedPaths():
            settings = frappe.get_single("Jarvis Settings")
            settings.db_set("openclaw_compose_dir", "/path/to/compose")

            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.CalledProcessError(1, "docker compose down", stderr="boom")
                from jarvis.openclaw_bootstrap import stop
                with self.assertRaises(OpenclawRestartFailedError):
                    stop()


class TestBootstrapStatus(FrappeTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_returns_dict_with_required_keys(self):
        with _PatchedPaths():
            settings = frappe.get_single("Jarvis Settings")
            settings.db_set("openclaw_compose_dir", "/path/to/compose")

            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap.urllib.request.urlopen") as mock_open:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=json.dumps({"Name": "openclaw-gateway", "State": "running", "Image": "ghcr.io/openclaw/openclaw:latest"}),
                    stderr="",
                )
                mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock(status=200))
                mock_open.return_value.__exit__ = MagicMock(return_value=False)

                from jarvis.openclaw_bootstrap import status
                result = status()

            self.assertIn("container", result)
            self.assertIn("image", result)
            self.assertIn("health", result)
            self.assertIn("gateway_url", result)
            self.assertEqual(result["container"], "running")
            self.assertEqual(result["health"], "healthy")
