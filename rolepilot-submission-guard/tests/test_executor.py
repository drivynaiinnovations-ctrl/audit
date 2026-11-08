import unittest
from executor import ApplicationExecutor, SubmissionRequest, SubmissionBlocked

class GuardStub:
    def __init__(self, result): self.result = result; self.calls = 0
    def preflight(self, *args): self.calls += 1; return self.result

class ExecutorTests(unittest.TestCase):
    def test_block_duplicate(self):
        g=GuardStub('BLOCK_DUPLICATE')
        with self.assertRaisesRegex(SubmissionBlocked,'BLOCK_DUPLICATE'):
            ApplicationExecutor(g).submit(SubmissionRequest('a','b','c','d','https://example.com',True))
        self.assertEqual(g.calls,1)
    def test_block_unapproved(self):
        with self.assertRaisesRegex(SubmissionBlocked,'HOLD_APPROVAL'):
            ApplicationExecutor(GuardStub('HOLD_APPROVAL')).submit(SubmissionRequest('a','b','c','d','https://example.com'))
    def test_block_database_failure(self):
        with self.assertRaisesRegex(SubmissionBlocked,'HOLD_INCOMPLETE'):
            ApplicationExecutor(GuardStub('HOLD_INCOMPLETE')).submit(SubmissionRequest('a','b','c','d','https://example.com',True))
    def test_approved_still_cannot_send(self):
        with self.assertRaisesRegex(SubmissionBlocked,'PRODUCTION_TRANSPORT_DISABLED'):
            ApplicationExecutor(GuardStub('READY_FOR_HUMAN_APPROVED_SUBMISSION')).submit(SubmissionRequest('a','b','c','d','https://example.com',True))
