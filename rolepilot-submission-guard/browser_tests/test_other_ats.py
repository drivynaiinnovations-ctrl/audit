import unittest

from playwright.sync_api import sync_playwright

from ats_browser import preparation_context, prepare_lever, prepare_workday
from browser_planner import BrowserPreparation


class OtherATSBrowserTests(unittest.TestCase):
    def open_fixture(self, provider, url, html):
        playwright = self.enterContext(sync_playwright())
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        plan = BrowserPreparation(provider, url, "READY_FOR_BROWSER_PREPARATION")
        context = preparation_context(browser, plan, html)
        self.addCleanup(context.close)
        return context.new_page(), plan

    def test_lever_preparation_and_submission_lockout(self):
        page, plan = self.open_fixture("lever", "https://jobs.lever.co/example/123/apply", """
            <form method="post" action="/submit">
              <label>Full name<input required name="name"></label>
              <label>Email<input required type="email" name="email"></label>
              <label>Phone<input name="phone"></label>
              <label>Portfolio<input required name="portfolio"></label>
              <button>Submit application</button>
            </form>
        """)
        profile = {"Full name": "Sample Applicant", "Email": "sample@example.test", "Phone": "555-0100"}
        self.assertEqual(prepare_lever(page, plan, profile), ["Portfolio"])
        for label, value in profile.items():
            self.assertEqual(page.get_by_label(label, exact=True).input_value(), value)

        page.get_by_label("Portfolio").fill("https://example.test")
        with page.expect_event("requestfailed", predicate=lambda request: request.method == "POST") as blocked:
            page.get_by_role("button", name="Submit application").click()
        self.assertEqual(blocked.value.url, "https://jobs.lever.co/submit")
        self.assertIn("ERR_BLOCKED_BY_CLIENT", blocked.value.failure)

    def test_workday_stops_at_sign_in(self):
        page, plan = self.open_fixture("workday", "https://example.wd5.myworkdayjobs.com/job/123/apply", """
            <form method="post" action="/login">
              <label>Email<input name="email"></label>
              <label>Password<input name="password" type="password"></label>
              <button>Sign In</button>
            </form>
            <a href="/create-account">Create Account</a>
        """)
        self.assertEqual(prepare_workday(page, plan), "HOLD_SIGN_IN")
        self.assertEqual(page.get_by_label("Email").input_value(), "")
        self.assertEqual(page.get_by_label("Password").input_value(), "")
        self.assertEqual(page.url, plan.url)
        with page.expect_event("requestfailed", predicate=lambda request: request.method == "POST") as blocked:
            page.get_by_role("button", name="Sign In").click()
        self.assertIn("ERR_BLOCKED_BY_CLIENT", blocked.value.failure)

    def test_workday_prepares_open_application_and_blocks_submission(self):
        page, plan = self.open_fixture("workday", "https://example.wd5.myworkdayjobs.com/job/123/apply", """
            <form method="post" action="/submit">
              <label>First Name<input required name="first_name"></label>
              <label>Last Name<input required name="last_name"></label>
              <label>Email<input required name="email" type="email"></label>
              <label>City<input required name="city"></label>
              <button>Submit application</button>
            </form>
        """)
        profile = {"First Name": "Sample", "Last Name": "Applicant", "Email": "sample@example.test"}
        self.assertEqual(prepare_workday(page, plan, profile), ["City"])
        for label, value in profile.items():
            self.assertEqual(page.get_by_label(label, exact=True).input_value(), value)
        page.get_by_label("City").fill("Sample City")
        with page.expect_event("requestfailed", predicate=lambda request: request.method == "POST") as blocked:
            page.get_by_role("button", name="Submit application").click()
        self.assertIn("ERR_BLOCKED_BY_CLIENT", blocked.value.failure)
