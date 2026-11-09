import unittest

from playwright.sync_api import sync_playwright

from ats_browser import preparation_context, prepare_greenhouse, prepare_lever, prepare_workday
from browser_planner import BrowserPreparation
from test_assisted_ats import RESUME


class ResumeAttachmentTests(unittest.TestCase):
    def test_resume_labels_and_missing_control(self):
        playwright = self.enterContext(sync_playwright())
        browser = playwright.chromium.launch()
        self.addCleanup(browser.close)
        cases = (
            ("greenhouse", prepare_greenhouse, "First Name", "Resume/CV"),
            ("lever", prepare_lever, "Full name", "Upload résumé"),
            ("workday", prepare_workday, "First Name", "CV"),
            ("greenhouse", prepare_greenhouse, "First Name", None),
        )
        for provider, prepare, name_label, resume_label in cases:
            with self.subTest(provider=provider, resume_label=resume_label):
                plan = BrowserPreparation(provider, "https://example.test/apply", "READY_FOR_BROWSER_PREPARATION")
                upload = f'<label>{resume_label}<input type="file" required></label>' if resume_label else ""
                form = f'<form><label>{name_label}<input></label><label>Email<input></label>{upload}</form>'
                with preparation_context(browser, plan, form) as context:
                    page = context.new_page()
                    if resume_label is None:
                        with self.assertRaisesRegex(ValueError, "expected one labeled file input"):
                            prepare(page, plan, {}, RESUME)
                    else:
                        self.assertEqual(prepare(page, plan, {}), [resume_label])
                        self.assertEqual(prepare(page, plan, {}, RESUME), [])
                        name = page.locator('input[type="file"]').evaluate("(input) => input.files[0].name")
                        self.assertEqual(name, RESUME["name"])
