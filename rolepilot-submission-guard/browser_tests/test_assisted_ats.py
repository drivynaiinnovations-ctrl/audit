import unittest

from playwright.sync_api import sync_playwright

from ats_browser import preparation_context, prepare_assisted
from browser_planner import BrowserApplicationPlanner
from executor import SubmissionRequest


FIXTURE_URLS = {
    "ashby": "https://jobs.ashbyhq.com/example/123/application",
    "ukg": "https://recruiting.ultipro.com/example/JobBoard/123",
    "rippling": "https://ats.rippling.com/example/jobs/123/apply",
    "harri": "https://harri.com/example/job/123",
    "workable": "https://apply.workable.com/example/j/123/apply/",
    "icims": "https://careers-example.icims.com/jobs/123/login",
    "teamtailor": "https://example.teamtailor.com/jobs/123/applications/new",
    "successfactors": "https://career5.successfactors.eu/career?career_job_req_id=123",
    "adp": "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html",
    "jobvite": "https://jobs.jobvite.com/example/job/123/apply",
    "careerplug": "https://example.careerplug.com/jobs/123/apps/new",
    "smartrecruiters": "https://jobs.smartrecruiters.com/Example/123",
}

FORM = """
<form method="post" action="/submit" enctype="multipart/form-data">
  <label>First Name<input name="first_name" required></label>
  <label>Last Name<input name="last_name" required></label>
  <label>Email<input name="email" type="email" required></label>
  <label>Resume<input name="resume" type="file" required></label>
  <label>Why this role?<textarea name="motivation" required></textarea></label>
  <button>Submit application</button>
</form>
"""

PROFILE = {"First Name": "Sample", "Last Name": "Applicant", "Email": "sample@example.test"}
RESUME = {"name": "sample-resume.txt", "mimeType": "text/plain", "buffer": b"Synthetic resume fixture"}


class ClearPreflight:
    def preflight(self, *args):
        return "HOLD_APPROVAL"


class AssistedATSBrowserTests(unittest.TestCase):
    def test_preparation_and_lockout_by_provider(self):
        planner = BrowserApplicationPlanner(ClearPreflight())
        playwright = self.enterContext(sync_playwright())
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        for provider, url in FIXTURE_URLS.items():
            with self.subTest(provider=provider):
                request = SubmissionRequest("opp", "Example", "Engineer", "123", url, False)
                plan = planner.prepare(request)
                self.assertEqual(plan.provider, provider)
                self.assertTrue(plan.requires_human_review)
                self.assertFalse(plan.submitted)
                context = preparation_context(browser, plan, FORM)
                try:
                    page = context.new_page()
                    self.assertEqual(prepare_assisted(page, plan, PROFILE), ["Resume", "Why this role?"])
                    self.assertEqual(prepare_assisted(page, plan, PROFILE, RESUME), ["Why this role?"])
                    for label, value in PROFILE.items():
                        self.assertEqual(page.get_by_label(label, exact=True).input_value(), value)
                    self.assertEqual(page.get_by_label("Resume").evaluate("(input) => input.files[0].name"), RESUME["name"])
                    self.assertEqual(page.get_by_label("Why this role?").input_value(), "")
                    page.get_by_label("Why this role?").fill("Synthetic answer")
                    with page.expect_event("requestfailed", predicate=lambda req: req.method == "POST") as blocked:
                        page.get_by_role("button", name="Submit application").click()
                    self.assertIn("ERR_BLOCKED_BY_CLIENT", blocked.value.failure)
                    print(f"{provider}: preparation, local attachment, required-field check, submission block passed", flush=True)
                finally:
                    context.close()
