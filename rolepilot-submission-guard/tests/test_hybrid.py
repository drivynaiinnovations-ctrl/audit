import unittest
from hybrid import HybridExecutor
from executor import SubmissionRequest

class Guard:
    def __init__(self,decision): self.decision=decision; self.approvals=[]
    def preflight(self,*args): self.approvals.append(args[5]); return self.decision

class HybridTests(unittest.TestCase):
    def setUp(self): self.req=SubmissionRequest('o','employer','role','req','https://jobs.example.com/role',True)
    def test_assisted_fallback(self):
        g=Guard('HOLD_APPROVAL'); p=HybridExecutor(g).plan(self.req)
        self.assertEqual(p.mode,'ASSISTED');self.assertFalse(p.submission_enabled);self.assertEqual(g.approvals,[False])
    def test_automation_eligibility_does_not_submit(self):
        p=HybridExecutor(Guard('HOLD_APPROVAL'),['jobs.example.com']).plan(self.req)
        self.assertEqual(p.mode,'AUTOMATED_ELIGIBLE');self.assertFalse(p.submission_enabled)
    def test_duplicate_blocks(self):
        p=HybridExecutor(Guard('BLOCK_DUPLICATE')).plan(self.req)
        self.assertEqual(p.mode,'BLOCKED')
    def test_live_execution_always_disabled(self):
        with self.assertRaisesRegex(RuntimeError,'LIVE_EMPLOYER_SUBMISSIONS_DISABLED'):
            HybridExecutor(Guard('HOLD_APPROVAL')).execute(self.req)
