"""Scheduled browser runner: claims preparation jobs from the Cloudflare Worker and
prepares multi-page applications up to (never including) the final submit control.

Hard boundaries:
  * The runner has no code path that clicks a control matching FINAL_SUBMIT.
  * CAPTCHA, MFA, sign-in, expired sessions, legal attestations, missing evidence,
    employer form changes and unapproved questions all stop the job with a HOLD.
  * Logs print job-ID prefixes and statuses only (the repository and its Actions logs are public).
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from screening import normalize_question

MAX_PAGES = 12
FINAL_SUBMIT = re.compile(r"\b(submit|send application|send my application|finish|complete application|place application)\b", re.I)
START = re.compile(r"^\s*(apply|apply now|apply for this (?:job|position|role)|apply manually|start (?:your )?application)\s*$", re.I)
NEXT = re.compile(r"^\s*(next|continue|save (?:and|&) continue|next step|proceed)\s*(?:>|→)?\s*$", re.I)
CAPTCHA_FRAME = re.compile(r"recaptcha|hcaptcha|challenges\.cloudflare\.com|captcha|arkoselabs|funcaptcha", re.I)
CAPTCHA_TEXT = re.compile(r"verify (?:that )?you(?:'re| are) (?:a )?human|complete (?:the )?captcha|i'?m not a robot|checking your browser|security check", re.I)
MFA_TEXT = re.compile(r"verification code|one[- ]time (?:pass)?code|two[- ]factor|multi[- ]factor|authenticator app|security code", re.I)
EXPIRED_TEXT = re.compile(r"session (?:has )?expired|session has ended|signed out due to inactivity|please sign in again|sign in again", re.I)
SIGN_IN_TEXT = re.compile(r"^\s*(sign in|log in|create account)\s*$", re.I)
LEGAL_LABEL = re.compile(r"i (?:hereby )?(?:certify|attest|declare|affirm)|under penalty|electronic signature|e-?signature|"
                         r"legally binding|true,? (?:accurate,? )?and complete|^\s*signature\s*\*?$|type your full (?:legal )?name to sign", re.I)
RESUME_LABEL = re.compile(r"r[eé]sum[eé]|\bcv\b", re.I)
COVER_LABEL = re.compile(r"cover\s*letter|pitch\s*letter", re.I)

COLLECT_JS = """() => {
  const visible = el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && (r.width > 0 || r.height > 0); };
  const labelOf = el => {
    let t = el.labels?.[0]?.innerText || el.getAttribute('aria-label') ||
      (el.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ') ||
      el.closest('fieldset')?.querySelector('legend')?.innerText || el.placeholder || el.name || '';
    return t.replace(/\\s+/g, ' ').replace(/\\s*\\*\\s*$/, '').trim(); };
  const seen = new Set(); const out = [];
  document.querySelectorAll('input, select, textarea').forEach((el, i) => {
    const type = (el.type || el.tagName).toLowerCase();
    if (['hidden','submit','button','reset','image'].includes(type) || (!visible(el) && type !== 'file')) return;
    if (!el.dataset.rpIndex) el.dataset.rpIndex = String(i);
    const group = (type === 'radio') ? 'radio:' + el.name : null;
    if (group && seen.has(group)) return; if (group) seen.add(group);
    const required = el.required || el.getAttribute('aria-required') === 'true' ||
      (group && [...document.getElementsByName(el.name)].some(r => r.required));
    let label = labelOf(el);
    if (group) label = el.closest('fieldset')?.querySelector('legend')?.innerText?.replace(/\\s*\\*\\s*$/, '').trim() || el.name;
    const filled = type === 'file' ? el.files.length > 0 : group ? [...document.getElementsByName(el.name)].some(r => r.checked)
      : type === 'checkbox' ? el.checked : !!el.value;
    const options = el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).filter(Boolean)
      : group ? [...document.getElementsByName(el.name)].map(r => r.labels?.[0]?.innerText.trim() || r.value) : [];
    out.push({ index: el.dataset.rpIndex, label, type: group ? 'radio' : type, required: !!required, filled, options, name: el.name || '' });
  });
  const buttons = [...document.querySelectorAll('button, input[type=submit], input[type=button], a[role=button], a')]
    .filter(visible).map(b => (b.innerText || b.value || b.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim());
  return { fields: out, buttons, text: document.body ? document.body.innerText.slice(0, 20000) : '',
           password: [...document.querySelectorAll('input[type=password]')].some(visible),
           otp: [...document.querySelectorAll('input[autocomplete=one-time-code]')].some(visible) };
}"""


def fingerprint(fields):
    shape = sorted(f"{normalize_question(f['label'])}:{f['type']}:{int(f['required'])}" for f in fields)
    return hashlib.sha256("|".join(shape).encode()).hexdigest()[:16]


def say(job_id, status, extra=""):
    print(f"[rolepilot] job {str(job_id)[:8]} {status} {extra}".rstrip(), flush=True)


class WorkerClient:
    def __init__(self, base, token, audit=False):
        if not base.startswith("https://") or not token:
            raise ValueError("ROLEPILOT_WORKER_URL and ROLEPILOT_RUNNER_TOKEN are required")
        self.base, self.token, self.audit = base.rstrip("/"), token, audit

    def _post(self, path, body, raw=False):
        req = Request(self.base + path, json.dumps({**body, "audit": self.audit}).encode(), {
            "authorization": "Bearer " + self.token, "content-type": "application/json", "user-agent": "rolepilot-runner/1"})
        try:
            with urlopen(req, timeout=60) as res:
                return res.read() if raw else json.load(res)
        except HTTPError as exc:
            if raw:
                return None
            payload = exc.read()
            try:
                return {"http_status": exc.code, **json.loads(payload)}
            except ValueError:
                return {"http_status": exc.code, "reason": "HTTP_ERROR"}

    def claim(self):
        r = self._post("/api/runner/claim", {})
        return r if r.get("decision") == "CLAIMED" else None

    def complete(self, job_id, result):
        return self._post("/api/runner/complete", {"job_id": job_id, "result": result})

    def document(self, job_id, slot, index, directory):
        data = self._post("/api/runner/document", {"job_id": job_id, "slot": slot, "index": index}, raw=True)
        if not data:
            return None
        path = Path(directory) / f"{slot}-{index}.pdf"
        path.write_bytes(data)
        return str(path)


class Preparer:
    """Drives one application through its pages. Returns a result dict for the Worker."""

    def __init__(self, page, job, documents, *, session_supplied=False):
        self.page = page
        self.job = job
        self.documents = documents  # callable(slot, index) -> local path or None
        self.vault_answers = {normalize_question(q): a for q, a in (job.get("approved_answers") or {}).items() if str(a).strip()}
        self.session_supplied = session_supplied
        expected = job.get("form_fingerprint") or ""
        self.expected_fingerprints = [x.strip() for x in expected.split(",") if x.strip()]

    def result(self, status, pages, **extra):
        return {"status": status, "pages": pages, "submitted": False, "final_submit_clicked": False, **extra}

    def snapshot(self):
        frames_hold = any(CAPTCHA_FRAME.search(f.url or "") for f in self.page.frames if f != self.page.main_frame)
        snap = self.page.evaluate(COLLECT_JS)
        snap["captcha_frame"] = frames_hold
        return snap

    def session_hold(self, snap):
        if snap["captcha_frame"] or CAPTCHA_TEXT.search(snap["text"]):
            return "HOLD_CAPTCHA"
        if snap["otp"] or MFA_TEXT.search(snap["text"]):
            return "HOLD_MFA"
        if EXPIRED_TEXT.search(snap["text"]):
            return "HOLD_SESSION_EXPIRED"
        if snap["password"] or any(SIGN_IN_TEXT.match(b) for b in snap["buttons"]) and not snap["fields"]:
            return "HOLD_SESSION_EXPIRED" if self.session_supplied else "HOLD_SIGN_IN"
        return ""

    def run(self):
        try:
            self.page.goto(self.job["source_url"], wait_until="domcontentloaded", timeout=45000)
        except Exception:
            return self.result("HOLD_SOURCE_UNAVAILABLE", 0)
        seen_form = False
        starts = 0
        page_number = 0
        while page_number < MAX_PAGES:
            self.page.wait_for_timeout(300)
            snap = self.snapshot()
            hold = self.session_hold(snap)
            if hold:
                return self.result(hold, page_number)
            fields = snap["fields"]
            # A job page opens with "Apply"; that link is allowed only before any form page is seen
            # and does not count as an application page.
            if not fields and not seen_form and starts < 2:
                start = next((b for b in snap["buttons"] if START.match(b) and not FINAL_SUBMIT.search(b)), None)
                if start:
                    starts += 1
                    before = (self.page.url, fingerprint(fields))
                    self.click(start)
                    if not self.wait_for_change(before):
                        return self.result("HOLD_NAVIGATION_FAILED", 0)
                    continue
            page_number += 1
            if fields:
                seen_form = True
            if any(LEGAL_LABEL.search(f["label"]) for f in fields) or re.search(r"under penalty of perjury", snap["text"], re.I):
                return self.result("HOLD_LEGAL_ATTESTATION", page_number - 1)
            if self.expected_fingerprints:
                expected = self.expected_fingerprints[page_number - 1] if page_number <= len(self.expected_fingerprints) else None
                if expected and fingerprint(fields) != expected:
                    return self.result("HOLD_FORM_CHANGED", page_number - 1, detail=f"page {page_number}")

            missing_evidence, new_questions = self.fill_page(fields)
            if missing_evidence:
                return self.result("HOLD_MISSING_EVIDENCE", page_number - 1, detail=", ".join(missing_evidence)[:300])
            if new_questions:
                return self.result("HOLD_NEW_QUESTIONS", page_number - 1, new_questions=new_questions)

            buttons = snap["buttons"]
            next_label = next((b for b in buttons if NEXT.match(b) and not FINAL_SUBMIT.search(b)), None)
            if next_label:
                before = (self.page.url, fingerprint(fields))
                self.click(next_label)
                if not self.wait_for_change(before):
                    return self.result("HOLD_NAVIGATION_FAILED", page_number)
                continue
            if any(FINAL_SUBMIT.search(b) for b in buttons):
                # Final review page reached. Stop here; the final control is never touched.
                return self.result("READY_FOR_REVIEW_NOT_SUBMITTED", page_number)
            return self.result("HOLD_UNSUPPORTED_FORM", page_number)
        return self.result("HOLD_PAGE_LIMIT", MAX_PAGES)

    def click(self, label):
        if FINAL_SUBMIT.search(label):
            raise PermissionError("REAL_EMPLOYER_SUBMISSIONS_DISABLED")
        target = self.page.get_by_role("button", name=label, exact=True)
        if target.count() == 0:
            target = self.page.get_by_role("link", name=label, exact=True)
        target.first.click()

    def wait_for_change(self, before, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(250)
            try:
                if (self.page.url, fingerprint(self.page.evaluate(COLLECT_JS)["fields"])) != before:
                    return True
            except Exception:
                continue  # navigation in progress
        return False

    def fill_page(self, fields):
        missing, new_questions = [], []
        supporting_used = 0
        for field in fields:
            control = self.page.locator(f'[data-rp-index="{field["index"]}"]').first
            if field["type"] == "file":
                if field["filled"]:
                    continue
                if RESUME_LABEL.search(field["label"]):
                    slot, index = "resume", 0
                elif COVER_LABEL.search(field["label"]):
                    slot, index = "cover_letter", 0
                elif field["required"]:
                    slot, index = "supporting", supporting_used
                    supporting_used += 1
                else:
                    continue
                path = self.documents(slot, index)
                if not path:
                    if field["required"] or slot == "resume":
                        missing.append(field["label"] or slot)
                    continue
                control.set_input_files(path)
                continue
            if field["filled"]:
                continue
            answer = self.vault_answers.get(normalize_question(field["label"]))
            if answer is None:
                if field["required"]:
                    new_questions.append(field["label"] or field["name"] or "unlabeled field")
                continue
            if not self.apply_answer(control, field, answer):
                new_questions.append(field["label"])
        return missing, new_questions

    def apply_answer(self, control, field, answer):
        kind = field["type"]
        if kind in ("select-one", "select"):
            if answer not in field["options"]:
                return False
            control.select_option(label=answer)
        elif kind == "radio":
            if answer not in field["options"]:
                return False
            group = self.page.locator(f'input[type=radio][name="{field["name"]}"]')
            for i in range(group.count()):
                radio = group.nth(i)
                if (radio.evaluate("r => r.labels?.[0]?.innerText.trim() || r.value")) == answer:
                    radio.check()
                    break
        elif kind == "checkbox":
            if normalize_question(answer) not in ("yes", "true", "checked"):
                return False
            control.check()
        else:
            control.fill(answer)
        return True


class PrepRunner:
    def __init__(self, client, browser, *, router=None, workday_sessions=None, synthetic_documents=False):
        self.client, self.browser, self.router = client, browser, router
        self.workday_sessions = workday_sessions or {}
        self.synthetic_documents = synthetic_documents

    def run_once(self):
        claimed = self.client.claim()
        if not claimed:
            return None
        job_id, job = claimed["id"], claimed["job"]
        host = re.sub(r"^https://([^/]+).*$", r"\1", job["source_url"]).lower()
        state = self.workday_sessions.get(host) if job.get("provider") == "workday" else None
        context = self.browser.new_context(service_workers="block", storage_state=state, accept_downloads=False)
        if self.router:
            context.route("**/*", self.router)
        with tempfile.TemporaryDirectory() as directory:
            def documents(slot, index):
                docs = job.get("documents") or {}
                url = docs.get("supporting", [])[index] if slot == "supporting" and index < len(docs.get("supporting", [])) else (docs.get(slot) if slot != "supporting" else None)
                if not url:
                    return None
                if self.synthetic_documents:
                    path = Path(directory) / f"{slot}-{index}.pdf"
                    path.write_bytes(b"%PDF-1.4\n% RolePilot synthetic audit document\n")
                    return str(path)
                return self.client.document(job_id, slot, index, directory)
            try:
                page = context.new_page()
                result = Preparer(page, job, documents, session_supplied=state is not None).run()
            except Exception as exc:  # never leak page content into public logs
                result = {"status": "HOLD_NAVIGATION_FAILED", "pages": 0, "submitted": False,
                          "final_submit_clicked": False, "detail": type(exc).__name__}
            finally:
                context.close()
        ack = self.client.complete(job_id, result)
        say(job_id, result["status"], f"pages={result['pages']} recorded={ack.get('decision')}")
        return {"job_id": job_id, "opportunity_id": job["opportunity_id"], "result": result, "recorded": ack}


def main():
    from playwright.sync_api import sync_playwright

    client = WorkerClient(os.environ.get("ROLEPILOT_WORKER_URL", ""), os.environ.get("ROLEPILOT_RUNNER_TOKEN", ""))
    sessions = json.loads(os.environ.get("WORKDAY_SESSIONS_JSON") or "{}")
    cycles = max(1, min(int(os.environ.get("ROLEPILOT_MAX_JOBS", "5")), 25))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        runner = PrepRunner(client, browser, workday_sessions=sessions)
        for _ in range(cycles):
            if runner.run_once() is None:
                print("[rolepilot] queue idle", flush=True)
                break
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
