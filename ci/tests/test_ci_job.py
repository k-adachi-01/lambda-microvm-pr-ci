"""Regression tests for the orchestrator's fail-closed checks.

These tests deliberately live outside ``tests/`` because ``tests/`` is the
project-under-test that runs inside the guest VM (which has no boto3). Run:

    uv run python -m unittest discover -s ci/tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))

import ci_job  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402


def client_error(code: str, operation: str = "GetMicrovm") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class FakeVm:
    """Minimal stand-in for the lambda-microvms client."""

    def __init__(self, states=None, errors=None):
        self.states = list(states or [])
        self.errors = list(errors or [])

    def get_microvm(self, **_kwargs):
        if self.errors:
            raise self.errors.pop(0)
        if len(self.states) > 1:
            return {"state": self.states.pop(0)}
        return {"state": self.states[0]}


class WaitTerminatedTests(unittest.TestCase):
    def test_terminated_is_verified(self):
        state, verified = ci_job.wait_terminated(FakeVm(["TERMINATED"]), "m", timeout=5)
        self.assertEqual(state, "TERMINATED")
        self.assertTrue(verified)

    def test_not_found_is_verified_gone(self):
        vm = FakeVm(errors=[client_error("ResourceNotFoundException")])
        state, verified = ci_job.wait_terminated(vm, "m", timeout=5)
        self.assertIn("gone", state)
        self.assertTrue(verified)

    def test_access_denied_is_unverified(self):
        vm = FakeVm(errors=[client_error("AccessDeniedException")])
        state, verified = ci_job.wait_terminated(vm, "m", timeout=5)
        self.assertIn("unverified", state)
        self.assertFalse(verified)

    def test_non_client_error_is_unverified(self):
        vm = FakeVm(errors=[RuntimeError("network")])
        state, verified = ci_job.wait_terminated(vm, "m", timeout=5)
        self.assertIn("unverified", state)
        self.assertFalse(verified)

    def test_timeout_is_unverified(self):
        state, verified = ci_job.wait_terminated(FakeVm(["RUNNING"]), "m", timeout=0)
        self.assertEqual(state, "still-not-TERMINATED")
        self.assertFalse(verified)


class ResultBundleTests(unittest.TestCase):
    def test_present_bundle_is_verified(self):
        s3 = mock.Mock()
        s3.head_object.return_value = {"ContentLength": 123}
        rec = ci_job.verify_result_bundle(s3, "b", "k")
        self.assertTrue(rec["verified"])
        self.assertEqual(rec["bytes"], 123)

    def test_missing_bundle_is_unverified(self):
        s3 = mock.Mock()
        s3.head_object.side_effect = client_error("NotFound", "HeadObject")
        rec = ci_job.verify_result_bundle(s3, "b", "k")
        self.assertFalse(rec["verified"])
        self.assertIn("error", rec)

    def test_empty_bundle_is_unverified(self):
        s3 = mock.Mock()
        s3.head_object.return_value = {"ContentLength": 0}
        rec = ci_job.verify_result_bundle(s3, "b", "k")
        self.assertFalse(rec["verified"])


class ExitCodeTests(unittest.TestCase):
    @staticmethod
    def base(**overrides):
        summary = {
            "jobStatus": "succeeded",
            "createdVm": True,
            "resultBundle": {"verified": True, "bytes": 10},
            "terminationVerified": True,
        }
        summary.update(overrides)
        return summary

    def test_verified_success_is_zero(self):
        self.assertEqual(ci_job.determine_exit_code(self.base()), 0)

    def test_missing_result_bundle_is_not_success(self):
        self.assertEqual(
            ci_job.determine_exit_code(self.base(resultBundle={"verified": False})), 2
        )

    def test_unverified_termination_is_not_success(self):
        self.assertEqual(ci_job.determine_exit_code(self.base(terminationVerified=False)), 2)

    def test_reused_vm_does_not_require_termination(self):
        self.assertEqual(
            ci_job.determine_exit_code(self.base(createdVm=False, terminationVerified=False)), 0
        )

    def test_failed_job_is_one(self):
        self.assertEqual(ci_job.determine_exit_code(self.base(jobStatus="failed")), 1)

    def test_missing_status_is_infra_error(self):
        summary = self.base()
        del summary["jobStatus"]
        self.assertEqual(ci_job.determine_exit_code(summary), 2)


class ErrorClassificationTests(unittest.TestCase):
    def test_service_quota_is_retryable(self):
        self.assertTrue(
            ci_job.is_throttle(client_error("ServiceQuotaExceededException", "RunMicrovm"))
        )

    def test_access_denied_is_not_retryable(self):
        self.assertFalse(ci_job.is_throttle(client_error("AccessDeniedException", "RunMicrovm")))

    def test_only_not_found_codes_prove_gone(self):
        self.assertTrue(ci_job.is_not_found(client_error("ResourceNotFoundException")))
        self.assertFalse(ci_job.is_not_found(client_error("AccessDeniedException")))


if __name__ == "__main__":
    unittest.main()
