import unittest
from ats_transport import SandboxATS,ProductionATS

class ATSTests(unittest.TestCase):
    def test_sandbox_receipt(self):
        r=SandboxATS().submit({'opportunity':'test-1'},'key-1')
        self.assertEqual(r.status,'SIMULATED');self.assertTrue(r.sandbox)
    def test_idempotent_replay(self):
        a=SandboxATS();first=a.submit({'opportunity':'test-1'},'key-1');second=a.submit({'opportunity':'test-1'},'key-1')
        self.assertEqual(first,second);self.assertEqual(len(a.receipts),1)
    def test_invalid_payload_rejected(self):
        with self.assertRaises(ValueError):SandboxATS().submit({},'key-1')
    def test_production_transport_disabled(self):
        with self.assertRaisesRegex(PermissionError,'REAL_EMPLOYER_SUBMISSIONS_DISABLED'):
            ProductionATS().submit({'opportunity':'test-1'},'key-1')
