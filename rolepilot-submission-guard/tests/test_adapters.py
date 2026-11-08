import unittest
from adapters import HybridAdapterRouter

class AdapterTests(unittest.TestCase):
    def test_fallback_assisted(self):
        self.assertEqual(HybridAdapterRouter().prepare('https://jobs.example.com/apply').mode,'ASSISTED')
    def test_allowlisted_automated(self):
        p=HybridAdapterRouter(['jobs.example.com']).prepare('https://jobs.example.com/apply')
        self.assertEqual(p.mode,'AUTOMATED_ELIGIBLE');self.assertFalse(p.submitted)
    def test_unapproved_held(self):
        self.assertEqual(HybridAdapterRouter().prepare('https://jobs.example.com/apply').status,'HOLD_APPROVAL')
    def test_duplicate_blocked(self):
        self.assertEqual(HybridAdapterRouter().prepare('https://jobs.example.com/apply',duplicate=True).status,'BLOCK_DUPLICATE')
    def test_invalid_url(self):
        self.assertEqual(HybridAdapterRouter().prepare('javascript:alert(1)').status,'BLOCK_INVALID_DESTINATION')
    def test_verified_still_not_sent(self):
        p=HybridAdapterRouter().prepare('https://jobs.example.com/apply',approval_verified=True)
        self.assertEqual(p.status,'READY_FOR_MANUAL_REVIEW');self.assertFalse(p.submitted)
    def test_transport_disabled(self):
        with self.assertRaisesRegex(RuntimeError,'LIVE_EMPLOYER_SUBMISSIONS_DISABLED'):
            HybridAdapterRouter().execute()
