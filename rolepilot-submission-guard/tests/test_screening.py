import unittest

from browser_worker import BrowserWorker
from screening import ApprovedAnswerVault, MultiPageWorkflow, SessionGuard


class ScreeningTests(unittest.TestCase):
    def setUp(self):
        self.vault = ApprovedAnswerVault({
            "Are you authorized to work in the United States?": "Yes",
            "Will you now or in the future require sponsorship?": "No",
        })

    def test_reuses_only_approved_answers_and_flags_new_questions(self):
        decisions = self.vault.decide([
            "Are you authorized to work in the United States?",
            "What compensation do you require?",
        ])
        self.assertEqual(decisions[0].status, "APPROVED_REUSE")
        self.assertEqual(decisions[0].answer, "Yes")
        self.assertEqual(decisions[1].status, "NEW_QUESTION")

    def test_multi_page_prepares_standard_answers_and_stops_before_submit(self):
        result = MultiPageWorkflow(self.vault).prepare([
            {"questions": ["Are you authorized to work in the United States?"]},
            {"questions": ["Will you now or in the future require sponsorship?"], "final_submit": True},
        ])
        self.assertEqual(result["status"], "READY_FOR_REVIEW_NOT_SUBMITTED")
        self.assertEqual(len(result["pages"]), 2)

    def test_new_question_stops_current_page(self):
        result = MultiPageWorkflow(self.vault).prepare([{"questions": ["Give a salary number"]}])
        self.assertEqual(result["status"], "HOLD_NEW_QUESTIONS")

    def test_workday_and_security_session_states(self):
        cases = (
            ({"url": "https://tenant.myworkdayjobs.com/login", "has_password": True}, "HOLD_SIGN_IN"),
            ({"page_text": "Enter verification code"}, "HOLD_MFA"),
            ({"page_text": "Session expired. Sign in again."}, "HOLD_SESSION_EXPIRED"),
            ({"page_text": "Verify you are human CAPTCHA"}, "HOLD_CAPTCHA"),
            ({"url": "https://tenant.myworkdayjobs.com/apply"}, "SESSION_READY"),
        )
        for values, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(SessionGuard.classify(**values), expected)


class Queue:
    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.results = []

    def claim(self):
        return self.jobs.pop(0) if self.jobs else None

    def complete(self, job_id, result):
        self.results.append((job_id, result))


class Browser:
    def inspect_pages(self, job):
        return job["pages"]


class BrowserWorkerTests(unittest.TestCase):
    def test_runner_processes_work_and_never_submits(self):
        queue = Queue([{"id": "1", "pages": [{"questions": [], "final_submit": True}]}])
        worker = BrowserWorker(queue, ApprovedAnswerVault(), Browser())
        statuses = worker.run(cycles=25)
        self.assertEqual(statuses[0], "READY_FOR_REVIEW_NOT_SUBMITTED")
        self.assertEqual(statuses[1:], ["IDLE"] * 24)
        self.assertFalse(hasattr(worker, "submit"))

    def test_runner_stops_on_captcha_mfa_and_expired_session(self):
        for marker, expected in (
            ("CAPTCHA", "HOLD_CAPTCHA"),
            ("verification code", "HOLD_MFA"),
            ("session expired", "HOLD_SESSION_EXPIRED"),
        ):
            queue = Queue([{"id": expected, "pages": [{"session": {"page_text": marker}}]}])
            status = BrowserWorker(queue, ApprovedAnswerVault(), Browser()).run_once()
            self.assertEqual(status, expected)

