"""Regression fixtures for patterns observed on live employer forms (2026-11-16, observe-only check):
  * Greenhouse job-boards: file inputs labelled "Attach"; the slot is only in the input id (resume / cover_letter).
  * Lever: invisible hCaptcha iframes (visibility:hidden) are present on every apply page; they only challenge at
    submit, so preparation must continue. A visible challenge must still stop.
  * Workday: the Apply control renders ~2s after DOMContentLoaded.
All data is synthetic and pages are served through Playwright routing; no network access.
"""

import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from prep_runner import Preparer

ANSWERS = {"First Name": "Synthetic", "Email": "synthetic@example.test"}

GREENHOUSE = """<!doctype html><form onsubmit="return false">
<label for=first_name>First Name *</label><input id=first_name required>
<label for=email>Email *</label><input id=email type=email required>
<div role=group aria-labelledby=upload-label-resume><div id=upload-label-resume>Resume/CV *</div>
  <label for=resume>Attach</label><input id=resume type=file style="display:none" required></div>
<div role=group aria-labelledby=upload-label-cover_letter><div id=upload-label-cover_letter>Cover Letter</div>
  <label for=cover_letter>Attach</label><input id=cover_letter type=file style="display:none"></div>
<button type=submit>Submit application</button></form>"""

LEVER = """<!doctype html><form onsubmit="return false">
<label for=n>First Name</label><input id=n name=name required>
<label for=e>Email</label><input id=e name=email type=email required>
<label for=r>Resume/CV</label><input id=r name=resume type=file required>
<iframe src="https://newassets.hcaptcha.com/captcha/v1/x/static/hcaptcha.html" style="visibility:hidden;width:1280px;height:720px"></iframe>
<button type=submit>Submit application</button></form>"""

LEVER_CHALLENGE = LEVER.replace("visibility:hidden;width:1280px;height:720px", "width:400px;height:580px")

WORKDAY = """<!doctype html><main id=app></main><script>
setTimeout(() => { app.innerHTML = '<h1>Role</h1><a role=button href="#a" id=a>Apply</a>';
  a.onclick = () => setTimeout(() => app.innerHTML = '<h2>Sign In</h2><label for=p>Password</label><input id=p type=password><button>Sign In</button>', 50);
}, 2000);</script>"""


class LivePatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def run_page(self, html, url, documents=("resume", "cover_letter")):
        context = self.browser.new_context()
        posts = []

        def route(r):
            if r.request.method != "GET":
                posts.append(r.request.url)
                return r.abort()
            if r.request.url.startswith(url.split("#")[0]):
                return r.fulfill(status=200, content_type="text/html", body=html)
            return r.fulfill(status=200, content_type="text/html", body="<html></html>")
        context.route("**/*", route)

        def docs(slot, index):
            if slot not in documents:
                return None
            path = Path(self.tmp.name) / f"{slot}.pdf"
            path.write_bytes(b"%PDF-1.4\n% synthetic\n")
            return str(path)
        page = context.new_page()
        job = {"source_url": url, "approved_answers": ANSWERS, "documents": {}}
        result = Preparer(page, job, docs).run()
        files = page.evaluate("() => Object.fromEntries([...document.querySelectorAll('input[type=file]')].map(e => [e.id, e.files.length]))")
        context.close()
        return result, files, posts

    def test_greenhouse_attach_buttons_receive_resume_and_cover(self):
        result, files, posts = self.run_page(GREENHOUSE, "https://job-boards.greenhouse.io/synthetic/jobs/1")
        self.assertEqual(result["status"], "READY_FOR_REVIEW_NOT_SUBMITTED")
        self.assertEqual(files, {"resume": 1, "cover_letter": 1})
        self.assertEqual(result["attached"], ["cover_letter", "resume"])
        self.assertFalse(result["submitted"])
        self.assertEqual(posts, [])

    def test_lever_invisible_hcaptcha_does_not_block_preparation(self):
        result, files, posts = self.run_page(LEVER, "https://jobs.lever.co/synthetic/1/apply")
        self.assertEqual(result["status"], "READY_FOR_REVIEW_NOT_SUBMITTED")
        self.assertEqual(files, {"r": 1})
        self.assertEqual(posts, [])

    def test_lever_visible_hcaptcha_challenge_still_stops(self):
        result, _, _ = self.run_page(LEVER_CHALLENGE, "https://jobs.lever.co/synthetic/2/apply")
        self.assertEqual(result["status"], "HOLD_CAPTCHA")

    def test_workday_delayed_render_reaches_sign_in_hold(self):
        result, _, posts = self.run_page(WORKDAY, "https://synthetic.wd115.myworkdayjobs.com/en-US/Careers/job/1")
        self.assertEqual(result["status"], "HOLD_SIGN_IN")
        self.assertEqual(posts, [])


if __name__ == "__main__":
    unittest.main()
