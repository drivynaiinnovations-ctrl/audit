"""Reusable screening answers and safe multi-page workflow state."""

import re
from dataclasses import dataclass


def normalize_question(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


@dataclass(frozen=True)
class ScreeningDecision:
    question: str
    answer: str = ""
    status: str = "NEW_QUESTION"


class ApprovedAnswerVault:
    """Exact normalized matches only; ambiguous questions always stop for review."""

    def __init__(self, approved_answers=None):
        self._answers = {}
        for question, answer in (approved_answers or {}).items():
            self.approve(question, answer)

    def approve(self, question, answer):
        key = normalize_question(question)
        answer = str(answer or "").strip()
        if not key or not answer:
            raise ValueError("Approved questions and answers must be non-empty")
        self._answers[key] = answer

    def decide(self, questions):
        decisions = []
        for question in questions:
            raw = str(question or "").strip()
            key = normalize_question(raw)
            if key in self._answers:
                decisions.append(ScreeningDecision(raw, self._answers[key], "APPROVED_REUSE"))
            else:
                decisions.append(ScreeningDecision(raw))
        return decisions


class SessionGuard:
    CAPTCHA = ("captcha", "verify you are human", "cloudflare challenge")
    MFA = ("verification code", "multi factor", "two factor", "security code")
    EXPIRED = ("session expired", "your session has ended", "sign in again")

    @classmethod
    def classify(cls, *, url="", page_text="", has_password=False):
        content = f"{url} {page_text}".casefold()
        if any(marker in content for marker in cls.CAPTCHA):
            return "HOLD_CAPTCHA"
        if any(marker in content for marker in cls.MFA):
            return "HOLD_MFA"
        if any(marker in content for marker in cls.EXPIRED):
            return "HOLD_SESSION_EXPIRED"
        if has_password or "signin" in content or "sign-in" in content or "/login" in content:
            return "HOLD_SIGN_IN"
        return "SESSION_READY"


class MultiPageWorkflow:
    """Prepare pages while preserving a hard boundary before final submission."""

    def __init__(self, vault, max_pages=12):
        self.vault = vault
        self.max_pages = max_pages

    def prepare(self, pages):
        prepared = []
        for page_number, page in enumerate(pages, start=1):
            if page_number > self.max_pages:
                return {"status": "HOLD_PAGE_LIMIT", "pages": prepared}
            session = SessionGuard.classify(**page.get("session", {}))
            if session != "SESSION_READY":
                return {"status": session, "pages": prepared, "page": page_number}
            decisions = self.vault.decide(page.get("questions", []))
            new_questions = [item.question for item in decisions if item.status == "NEW_QUESTION"]
            prepared.append({"page": page_number, "decisions": decisions})
            if new_questions:
                return {"status": "HOLD_NEW_QUESTIONS", "pages": prepared, "questions": new_questions}
            if page.get("final_submit"):
                return {"status": "READY_FOR_REVIEW_NOT_SUBMITTED", "pages": prepared}
        return {"status": "PREPARED_NEXT_PAGE", "pages": prepared}

