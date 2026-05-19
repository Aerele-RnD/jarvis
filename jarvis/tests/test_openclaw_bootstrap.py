import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import OpenclawRestartFailedError


def _make_fake_plugin(workspace: Path) -> Path:
    """Create a minimal fake plugin tree at <workspace>/jarvis-openclaw-plugin/."""
    plugin_dir = workspace / "jarvis-openclaw-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "package.json").write_text('{"name": "jarvis-openclaw-plugin", "version": "0.0.1"}\n')
    (plugin_dir / "openclaw.plugin.json").write_text('{"id": "jarvis-openclaw-plugin"}\n')
    dist_dir = plugin_dir / "dist"
    dist_dir.mkdir(exist_ok=True)
    (dist_dir / "index.js").write_text("// stub\n")
    # Stub the runtime deps that _install_plugin copies (production deps listed
    # in the plugin's package.json). Keep this in sync with openclaw_bootstrap's
    # runtime_deps tuple.
    typebox_dir = plugin_dir / "node_modules" / "typebox"
    typebox_dir.mkdir(parents=True, exist_ok=True)
    (typebox_dir / "package.json").write_text('{"name": "typebox", "version": "1.1.38"}\n')
    return plugin_dir


class _PatchedPaths:
    """Helper that patches openclaw_bootstrap's workspace_root() to a tempdir.

    Also creates a minimal fake plugin source so _install_plugin() doesn't fail.
    """

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        (self.workspace / "openclaw").mkdir()
        (self.workspace / "openclaw" / "docker-compose.yml").write_text("# stub\n")
        _make_fake_plugin(self.workspace)

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
        "agent_url", "agent_token",
        "agent_llm_key_path", "agent_config_path", "agent_compose_dir",
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
            self.assertEqual(settings.agent_compose_dir, str(workspace / "openclaw"))
            self.assertEqual(settings.agent_config_path, str(workspace / "openclaw_state" / "openclaw.json"))
            self.assertEqual(settings.agent_llm_key_path, str(workspace / "openclaw_state" / "llm.key"))
            self.assertEqual(settings.agent_url, "ws://127.0.0.1:18789")

    def test_generates_gateway_token_on_first_run(self):
        with _PatchedPaths():
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()
            settings = frappe.get_single("Jarvis Settings")
            token = settings.get_password("agent_token")
            self.assertIsNotNone(token)
            self.assertGreaterEqual(len(token), 32)

    def test_preserves_existing_token_on_rerun(self):
        with _PatchedPaths():
            settings = frappe.get_single("Jarvis Settings")
            settings.db_set("agent_token", "preexisting-token-12345")
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()
            settings = frappe.get_single("Jarvis Settings")
            self.assertEqual(settings.get_password("agent_token"), "preexisting-token-12345")

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
            self.assertIn("OPENCLAW_WORKSPACE_DIR=", env)
            self.assertIn("openclaw_state/workspace", env)
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
            settings.db_set("agent_compose_dir", "/path/to/compose")

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
            settings.db_set("agent_compose_dir", "/path/to/compose")

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
            settings.db_set("agent_compose_dir", "/path/to/compose")

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


class TestInstallPlugin(FrappeTestCase):
    """Unit tests for _install_plugin() — uses tempdir with a fake plugin source."""

    def _make_workspace(self):
        """Return a TemporaryDirectory; caller must clean it up."""
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        workspace = Path(tmp.name)
        state_dir = workspace / "openclaw_state"
        state_dir.mkdir()
        return tmp, workspace, state_dir

    def test_missing_plugin_source_raises(self):
        from jarvis.openclaw_bootstrap import _install_plugin
        tmp, workspace, state_dir = self._make_workspace()
        try:
            # No plugin source directory created
            with self.assertRaises(OpenclawRestartFailedError) as cm:
                _install_plugin(workspace, state_dir)
            self.assertIn("plugin source not found", str(cm.exception))
            self.assertIn("jarvis-openclaw-plugin", str(cm.exception))
        finally:
            tmp.cleanup()

    def test_plugin_not_built_raises(self):
        from jarvis.openclaw_bootstrap import _install_plugin
        tmp, workspace, state_dir = self._make_workspace()
        try:
            # Create plugin source directory but no dist/
            plugin_dir = workspace / "jarvis-openclaw-plugin"
            plugin_dir.mkdir()
            (plugin_dir / "package.json").write_text('{"name": "jarvis-openclaw-plugin"}\n')
            with self.assertRaises(OpenclawRestartFailedError) as cm:
                _install_plugin(workspace, state_dir)
            self.assertIn("pnpm", str(cm.exception))
        finally:
            tmp.cleanup()

    def test_plugin_dist_exists_but_no_index_js_raises(self):
        from jarvis.openclaw_bootstrap import _install_plugin
        tmp, workspace, state_dir = self._make_workspace()
        try:
            plugin_dir = workspace / "jarvis-openclaw-plugin"
            plugin_dir.mkdir()
            (plugin_dir / "package.json").write_text('{"name": "jarvis-openclaw-plugin"}\n')
            (plugin_dir / "dist").mkdir()
            # dist/ exists but index.js is absent
            with self.assertRaises(OpenclawRestartFailedError) as cm:
                _install_plugin(workspace, state_dir)
            self.assertIn("pnpm", str(cm.exception))
        finally:
            tmp.cleanup()

    def test_happy_path_copies_files_to_extensions(self):
        from jarvis.openclaw_bootstrap import _install_plugin
        tmp, workspace, state_dir = self._make_workspace()
        try:
            _make_fake_plugin(workspace)
            _install_plugin(workspace, state_dir)

            target = state_dir / "extensions" / "jarvis-openclaw-plugin"
            self.assertTrue((target / "package.json").exists())
            self.assertTrue((target / "openclaw.plugin.json").exists())
            self.assertTrue((target / "dist" / "index.js").exists())
        finally:
            tmp.cleanup()

    def test_idempotent_second_run_succeeds_and_updates(self):
        from jarvis.openclaw_bootstrap import _install_plugin
        tmp, workspace, state_dir = self._make_workspace()
        try:
            _make_fake_plugin(workspace)
            _install_plugin(workspace, state_dir)

            # Modify the built dist — simulate a rebuild
            plugin_dir = workspace / "jarvis-openclaw-plugin"
            (plugin_dir / "dist" / "index.js").write_text("// updated build\n")

            # Second run should succeed
            _install_plugin(workspace, state_dir)

            target = state_dir / "extensions" / "jarvis-openclaw-plugin"
            self.assertEqual((target / "dist" / "index.js").read_text(), "// updated build\n")
        finally:
            tmp.cleanup()

    def test_only_listed_runtime_deps_are_copied(self):
        """_install_plugin copies only the explicit runtime_deps (typebox today),
        not arbitrary contents of source node_modules. This protects against
        pnpm's symlink farm (which would otherwise pull in the entire openclaw
        source via the link: dep)."""
        from jarvis.openclaw_bootstrap import _install_plugin
        tmp, workspace, state_dir = self._make_workspace()
        try:
            plugin_dir = _make_fake_plugin(workspace)
            # _make_fake_plugin already creates node_modules/typebox; add a
            # non-runtime dep that should be excluded.
            (plugin_dir / "node_modules" / "some-dep").mkdir()
            (plugin_dir / "node_modules" / "some-dep" / "index.js").write_text("// dep\n")
            _install_plugin(workspace, state_dir)

            target = state_dir / "extensions" / "jarvis-openclaw-plugin"
            self.assertTrue((target / "node_modules" / "typebox").exists())
            self.assertFalse((target / "node_modules" / "some-dep").exists())
        finally:
            tmp.cleanup()

    def test_start_installs_plugin_before_docker_commands(self):
        """Integration check: start() installs the plugin into the state dir."""
        _reset_settings()
        with _PatchedPaths() as workspace:
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()

            state = workspace / "openclaw_state"
            target = state / "extensions" / "jarvis-openclaw-plugin"
            self.assertTrue(target.exists(), "plugin directory must exist after start()")
            self.assertTrue((target / "package.json").exists())
            self.assertTrue((target / "dist" / "index.js").exists())


class TestSeedWorkspace(FrappeTestCase):
    """Exercises _seed_workspace() — the function that drops Jarvis persona
    files into the agent workspace so a fresh container boots with identity.
    """

    def test_seeds_all_persona_files_on_first_run(self):
        from jarvis.openclaw_bootstrap import (
            WORKSPACE_SEED_FILES,
            _seed_workspace,
        )

        tmp = tempfile.TemporaryDirectory()
        try:
            workspace = Path(tmp.name) / "workspace"
            _seed_workspace(workspace)
            for fname in WORKSPACE_SEED_FILES:
                self.assertTrue(
                    (workspace / fname).exists(),
                    f"{fname} should be seeded into the workspace",
                )
        finally:
            tmp.cleanup()

    def test_does_not_overwrite_existing_files(self):
        """If the agent has already edited IDENTITY.md, seeding must not
        clobber it on subsequent bootstrap.start() calls.
        """
        from jarvis.openclaw_bootstrap import _seed_workspace

        tmp = tempfile.TemporaryDirectory()
        try:
            workspace = Path(tmp.name) / "workspace"
            workspace.mkdir(parents=True)
            user_content = "# IDENTITY\n\n- Name: Custom Name\n"
            (workspace / "IDENTITY.md").write_text(user_content)

            _seed_workspace(workspace)

            self.assertEqual(
                (workspace / "IDENTITY.md").read_text(),
                user_content,
                "existing IDENTITY.md must be preserved",
            )
            # Files that didn't exist still get seeded
            self.assertTrue((workspace / "SOUL.md").exists())
        finally:
            tmp.cleanup()

    def test_removes_stale_bootstrap_md_when_identity_present(self):
        """The bootstrap ritual is only meaningful for a workspace with no
        identity. If our seeds are present, BOOTSTRAP.md should be removed
        so the agent doesn't run the "who am I?" ritual.
        """
        from jarvis.openclaw_bootstrap import _seed_workspace

        tmp = tempfile.TemporaryDirectory()
        try:
            workspace = Path(tmp.name) / "workspace"
            workspace.mkdir(parents=True)
            (workspace / "BOOTSTRAP.md").write_text("# Bootstrap ritual…\n")

            _seed_workspace(workspace)

            self.assertFalse(
                (workspace / "BOOTSTRAP.md").exists(),
                "BOOTSTRAP.md should be removed once identity is seeded",
            )
        finally:
            tmp.cleanup()

    def test_start_seeds_workspace(self):
        """Integration check: start() creates the agent workspace with seeds."""
        _reset_settings()
        with _PatchedPaths() as workspace:
            with patch("jarvis.openclaw_bootstrap.subprocess.run") as mock_run, \
                 patch("jarvis.openclaw_bootstrap._poll_healthz", return_value=None):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                from jarvis.openclaw_bootstrap import start
                start()

            agent_ws = workspace / "openclaw_state" / "workspace"
            self.assertTrue((agent_ws / "IDENTITY.md").exists())
            self.assertTrue((agent_ws / "SOUL.md").exists())
            self.assertTrue((agent_ws / "AGENTS.md").exists())
            self.assertTrue((agent_ws / "USER.md").exists())
            # And the identity is actually Jarvis-flavored
            self.assertIn("Jarvis", (agent_ws / "IDENTITY.md").read_text())
