import unittest
from ats_providers import ATSProviderRouter

class ProviderTests(unittest.TestCase):
    def setUp(self):self.router=ATSProviderRouter()
    def test_greenhouse(self):self.assertEqual(self.router.classify('https://job-boards.greenhouse.io/acme/jobs/123').provider,'greenhouse')
    def test_lever(self):self.assertEqual(self.router.classify('https://jobs.lever.co/acme/123').provider,'lever')
    def test_workday(self):self.assertEqual(self.router.classify('https://acme.wd5.myworkdayjobs.com/en-US/jobs/job/123').provider,'workday')
    def test_workday_root_rejected(self):self.assertEqual(self.router.classify('https://myworkdayjobs.com').provider,'unknown')
    def test_fake_host_not_trusted(self):self.assertEqual(self.router.classify('https://jobs.lever.co.attacker.test/job').provider,'unknown')
    def test_invalid_scheme_blocked(self):self.assertEqual(self.router.classify('javascript:alert(1)').mode,'BLOCKED')
    def test_all_disabled(self):
        for url in ('https://job-boards.greenhouse.io/acme/jobs/123','https://jobs.lever.co/acme/123','https://acme.wd5.myworkdayjobs.com/job'):
            self.assertFalse(self.router.classify(url).submission_enabled)
    def test_submit_denied(self):
        with self.assertRaisesRegex(PermissionError,'REAL_EMPLOYER_SUBMISSIONS_DISABLED'):self.router.submit({})
