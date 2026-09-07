"""Source revision reporting is exact and fails soft outside a Git checkout."""

import subprocess
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from jarvis import source_version


class TestSourceDetails(TestCase):
	def tearDown(self):
		source_version.source_details.cache_clear()

	def test_reports_branch_and_exact_release_tag(self):
		with patch.object(source_version, "_git_value", side_effect=["version-16", "v16.1.0"]):
			self.assertEqual(
				source_version.source_details(),
				{"branch": "version-16", "tag": "v16.1.0"},
			)

	def test_values_are_cached_for_repeated_connection_polls(self):
		with patch.object(source_version, "_git_value", side_effect=["develop", None]) as git_value:
			source_version.source_details()
			source_version.source_details()
		self.assertEqual(git_value.call_count, 2)

	def test_git_failure_and_detached_head_are_unknown(self):
		with patch.object(
			source_version.subprocess,
			"run",
			side_effect=[
				SimpleNamespace(returncode=0, stdout="\n"),
				subprocess.TimeoutExpired("git", 2),
			],
		):
			self.assertIsNone(source_version._git_value("branch", "--show-current"))
			self.assertIsNone(source_version._git_value("describe", "--tags", "--exact-match"))
