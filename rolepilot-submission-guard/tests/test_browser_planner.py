import unittest
from browser_planner import BrowserApplicationPlanner
from executor import SubmissionRequest
class Guard:
    def __init__(self,result='HOLD_APPROVAL'):self.result=result;self.approvals=[]
    def preflight(self,*args):self.approvals.append(args[5]);return self.result
class BrowserTests(unittest.TestCase):
    def setUp(self):self.req=SubmissionRequest('opp','Acme','Engineer','123','https://jobs.lever.co/acme/123',True)
    def test_lever_preparation(self):
        p=BrowserApplicationPlanner(Guard()).prepare(self.req)
        self.assertEqual(p.provider,'lever');self.assertEqual(p.status,'READY_FOR_BROWSER_PREPARATION');self.assertFalse(p.submitted)
    def test_greenhouse_preparation(self):
        q=SubmissionRequest('opp','Acme','Engineer','123','https://job-boards.greenhouse.io/acme/jobs/123',True)
        self.assertEqual(BrowserApplicationPlanner(Guard()).prepare(q).provider,'greenhouse')
    def test_workday_preparation(self):
        q=SubmissionRequest('opp','Acme','Engineer','123','https://acme.wd5.myworkdayjobs.com/job/123',True)
        self.assertEqual(BrowserApplicationPlanner(Guard()).prepare(q).provider,'workday')
    def test_duplicate_stops(self):self.assertEqual(BrowserApplicationPlanner(Guard('BLOCK_DUPLICATE')).prepare(self.req).status,'BLOCK_DUPLICATE')
    def test_caller_approval_ignored(self):
        g=Guard();BrowserApplicationPlanner(g).prepare(self.req);self.assertEqual(g.approvals,[False])
    def test_invalid_url_stops(self):
        q=SubmissionRequest('opp','Acme','Engineer','123','javascript:alert(1)',True)
        self.assertEqual(BrowserApplicationPlanner(Guard()).prepare(q).status,'BLOCK_INVALID_URL')
    def test_submit_disabled(self):
        with self.assertRaises(PermissionError):BrowserApplicationPlanner(Guard()).submit(self.req)
