"""Static regression checks for the privileged workflow.

The workflow must never interpolate event-controlled values directly into a
shell script. These tests fail if the label JSON or the fork archive URL is
moved back into a `run:` body.
"""
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "microvm-ci.yml"


class WorkflowTrustTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_labels_are_passed_through_env_not_shell_interpolation(self):
        self.assertIn("LABELS_JSON: ${{ toJSON(github.event.pull_request.labels.*.name) }}", self.text)
        self.assertNotIn("labels='${{", self.text)
        self.assertIn("jq -e 'index(\"microvm-ci-ok\")'", self.text)

    def test_fork_archive_uses_head_repository(self):
        self.assertIn("HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name || github.repository }}", self.text)
        self.assertIn('gh api "repos/$HEAD_REPO/tarball/$HEAD_SHA"', self.text)

    def test_dispatch_inputs_are_not_interpolated_into_shell(self):
        self.assertNotIn('"${{ inputs.simulate_fork_gate }}"', self.text)
        self.assertNotIn('"${{ inputs.tamper_sha }}"', self.text)
        self.assertNotIn('"${{ inputs.boto_max_attempts', self.text)


if __name__ == "__main__":
    unittest.main()
