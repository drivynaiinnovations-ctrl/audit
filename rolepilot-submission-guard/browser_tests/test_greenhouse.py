import unittest

from playwright.sync_api import sync_playwright

from browser_planner import BrowserPreparation
from ats_browser import preparation_context, prepare_greenhouse


FORM = """
<form method="post" action="/submit">
  <label>First Name<input name="first_name" required></label>
  <label>Last Name<input name="last_name" required></label>
  <label>Email<input name="email" type="email" required></label>
  <label>Why this role?<select name="motivation" required><option value="">Choose</option><option value="test">Synthetic test answer</option></select></label>
  <button type="submit">Submit</button>
</form>
"""


class GreenhouseBrowserTest(unittest.TestCase):
    def test_preparation_and_submission_lockout(self):
        preparation = BrowserPreparation(
            "greenhouse",
            "https://job-boards.greenhouse.io/example/jobs/123",
            "READY_FOR_BROWSER_PREPARATION",
        )
        profile = {
            "First Name": "Sample",
            "Last Name": "Applicant",
            "Email": "applicant@example.test",
        }

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = preparation_context(browser, preparation, FORM)
            try:
                page = context.new_page()
                self.assertEqual(prepare_greenhouse(page, preparation, profile), ["Why this role?"])
                for label, value in profile.items():
                    self.assertEqual(page.get_by_label(label, exact=True).input_value(), value)

                self.assertEqual(page.url, preparation.url)
                self.assertEqual(page.get_by_label("Why this role?").input_value(), "")
                page.get_by_label("Why this role?").select_option("test")
                with page.expect_event("requestfailed", predicate=lambda request: request.method == "POST") as blocked:
                    page.get_by_role("button", name="Submit").click(no_wait_after=True)
                self.assertEqual(blocked.value.url, "https://job-boards.greenhouse.io/submit")
                self.assertIn("ERR_BLOCKED_BY_CLIENT", blocked.value.failure)
            finally:
                context.close()
                browser.close()
