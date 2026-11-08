import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from guard import Guard, BLOCK, HOLD, APPROVAL, READY

BASE=dict(opportunity="old-001",employer="Example Retail",role="Store Systems Manager",requisition="JR-100",url="https://example.com/jobs/100")

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.guard=Guard()
        self.guard.import_existing(**BASE)

    def check(self, **changes):
        candidate={**BASE,**changes}
        return self.guard.preflight(**candidate,approved=True)

    def test_01_opportunity(self): self.assertEqual(self.check(),BLOCK)
    def test_02_requisition(self): self.assertEqual(self.check(opportunity="new",role="Other",url="https://example.com/jobs/200"),BLOCK)
    def test_03_url(self): self.assertEqual(self.check(opportunity="new",role="Other",requisition="JR-200",url="https://www.example.com/jobs/100?ref=abc"),BLOCK)
    def test_04_employer_role(self): self.assertEqual(self.check(opportunity="new",requisition="JR-200",url="https://example.com/jobs/200"),BLOCK)
    def test_05_no_approval(self):
        self.assertEqual(self.guard.preflight("new","Other Inc","Other","JR-200","https://other.com/jobs/200"),APPROVAL)
    def test_06_missing_identity(self): self.assertEqual(self.check(opportunity=""),HOLD)
    def test_07_reserve_and_block(self):
        candidate=("new","Other Inc","Other","JR-200","https://other.com/jobs/200")
        self.assertEqual(self.guard.preflight(*candidate,approved=True),READY)
        self.assertEqual(self.guard.preflight(*candidate,approved=True),BLOCK)
    def test_08_idempotency(self):
        candidate=("new","Other Inc","Other","JR-200","https://other.com/jobs/200")
        self.assertEqual(self.guard.preflight(*candidate,approved=True,key="abc"),READY)
        self.assertEqual(self.guard.preflight(*candidate,approved=True,key="abc"),READY)
    def test_09_fail_closed(self):
        self.guard.db.close()
        self.assertEqual(self.check(opportunity="new"),HOLD)
    def test_10_audit_immutable(self):
        self.check()
        with self.assertRaises(Exception): self.guard.db.execute("DELETE FROM audit")

if __name__=="__main__": unittest.main()
