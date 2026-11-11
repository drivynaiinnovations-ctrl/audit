import unittest

from playwright.sync_api import sync_playwright

from ats_browser import (
    preparation_context, prepare_assisted, prepare_greenhouse, prepare_lever, prepare_workday,
)
from browser_planner import BrowserPreparation
from test_assisted_ats import FIXTURE_URLS, RESUME


class LetterPreparationTests(unittest.TestCase):
    def test_file_and_text_by_provider(self):
        playwright = self.enterContext(sync_playwright())
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        providers = {provider: (url, prepare_assisted) for provider, url in FIXTURE_URLS.items()}
        providers.update({
            "greenhouse": ("https://job-boards.greenhouse.io/example/jobs/123", prepare_greenhouse),
            "lever": ("https://jobs.lever.co/example/123/apply", prepare_lever),
            "workday": ("https://example.wd5.myworkdayjobs.com/job/123/apply", prepare_workday),
        })
        text = "Jane Doe is a fictional applicant."
        attachment = {**RESUME, "name": "jane-doe-cover-letter.txt", "buffer": text.encode()}
        for provider, (url, prepare) in providers.items():
            for letter, field_html in (
                (text, '<label>Pitch Letter<textarea required></textarea></label>'),
                (attachment, '<label>Upload Cover Letter<input type="file" required></label>'),
            ):
                with self.subTest(provider=provider, format=type(letter).__name__):
                    plan = BrowserPreparation(provider, url, "READY_FOR_BROWSER_PREPARATION")
                    form = (
                        '<form method="post" action="/submit"><label>Email<input></label>'
                        '<label>Resume<input type="file" required></label>'
                        f'{field_html}<button>Submit</button></form>'
                    )
                    with preparation_context(browser, plan, form) as context:
                        page = context.new_page()
                        self.assertEqual(prepare(page, plan, {}, RESUME, letter=letter), [])
                        self.assertEqual(
                            page.get_by_label("Resume").evaluate("(input) => input.files[0].name"),
                            RESUME["name"],
                        )
                        if isinstance(letter, str):
                            self.assertEqual(page.get_by_label("Pitch Letter").input_value(), text)
                        else:
                            self.assertEqual(
                                page.get_by_label("Upload Cover Letter").evaluate("(input) => input.files[0].name"),
                                attachment["name"],
                            )
                        with page.expect_event("requestfailed", predicate=lambda req: req.method == "POST") as blocked:
                            page.get_by_role("button", name="Submit").click()
                        self.assertIn("ERR_BLOCKED_BY_CLIENT", blocked.value.failure)
            print(f"{provider}: letter text, attachment, and submission lockout passed", flush=True)

    def test_missing_letter_field_requires_review(self):
        playwright = self.enterContext(sync_playwright())
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        plan = BrowserPreparation("greenhouse", "https://example.test/apply", "READY_FOR_BROWSER_PREPARATION")
        form = '<form><label>Email<input></label><label>Other notes<textarea></textarea></label></form>'
        with preparation_context(browser, plan, form) as context:
            with self.assertRaisesRegex(ValueError, "Letter needs review"):
                prepare_greenhouse(context.new_page(), plan, {}, letter="Synthetic pitch")
