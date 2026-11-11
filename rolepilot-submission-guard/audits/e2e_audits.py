"""25 end-to-end audits against the LIVE Cloudflare Worker, Queue and D1.

Flow per run: synthetic AUDIT- COI rows -> live /api/coi/import -> Cloudflare Queue ->
queue consumer -> D1 jobs -> runner claim -> Chromium preparation -> runner complete.

Employer forms are served from local fixtures through Playwright routing; every other
request is aborted, so no real employer site is contacted. All data is synthetic.

Env: ROLEPILOT_WORKER_URL, ROLEPILOT_OPERATOR_TOKEN, ROLEPILOT_RUNNER_TOKEN
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prep_runner import PrepRunner, WorkerClient, fingerprint  # noqa: E402

BASE = os.environ.get("ROLEPILOT_WORKER_URL", "https://rolepilot-staging-guard.drivyn-ai-innovations.workers.dev").rstrip("/")
OPERATOR = os.environ["ROLEPILOT_OPERATOR_TOKEN"]
RUNNER = os.environ["ROLEPILOT_RUNNER_TOKEN"]
SITE = "audit.rolepilot.test"
WD_VALID, WD_NONE, WD_EXPIRED = (f"rolepilot-audit-{x}.wd1.myworkdayjobs.com" for x in ("valid", "none", "expired"))
RUN = time.strftime("%H%M%S")


def call(path, body=None, token=OPERATOR, method="POST"):
    req = Request(BASE + path, None if body is None else json.dumps(body).encode(), method=method,
                  headers={"content-type": "application/json", "user-agent": "rolepilot-audit/1",
                           **({"authorization": "Bearer " + token} if token else {})})
    try:
        with urlopen(req, timeout=60) as res:
            return res.status, json.load(res)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


# ---------------------------------------------------------------- fixtures
F = lambda label, type="text", required=True, options=None, name=None: {  # noqa: E731
    "label": label, "type": type, "required": required, "options": options or [], "name": name or label.lower().replace(" ", "_")[:30]}
CONTACT = [F("First Name"), F("Email", "email"), F("Resume", "file"), F("Cover Letter", "file", required=False)]
WORK_AUTH = [F("Are you legally authorized to work in the United States?", "select", options=["", "Yes", "No"]),
             F("Will you now or in the future require sponsorship?", "select", options=["", "Yes", "No"])]
REVIEW = {"fields": [], "button": "Submit Application"}
STEP = lambda fields: {"fields": fields, "button": "Next"}  # noqa: E731

FORMS = {
    "/multipage": {"steps": [STEP(CONTACT), STEP(WORK_AUTH), REVIEW]},
    "/answers": {"steps": [STEP(WORK_AUTH), REVIEW]},
    "/newq": {"steps": [STEP(CONTACT), STEP([F("Describe your experience leading a cross-functional launch", "textarea")]), REVIEW]},
    "/captcha": {"gate": "captcha", "steps": [STEP(CONTACT), REVIEW]},
    "/mfa": {"gate": "mfa", "steps": [STEP(CONTACT), REVIEW]},
    "/legal": {"steps": [STEP(CONTACT), STEP([F("I certify that the information provided is true and complete", "checkbox")]), REVIEW]},
    "/evidence": {"steps": [STEP(CONTACT + [F("Portfolio", "file")]), REVIEW]},
    "/changed": {"steps": [STEP(CONTACT + [F("Salary expectations")]), REVIEW]},
    "/docs": {"steps": [STEP(CONTACT), REVIEW]},
    "/probe": {"steps": [STEP(CONTACT), REVIEW]},
    "/workday": {"workday": True, "steps": [STEP(CONTACT), STEP(WORK_AUTH), REVIEW]},
}
ORIGINAL_CONTACT_FINGERPRINT = fingerprint([
    {"label": f["label"], "type": {"select": "select-one"}.get(f["type"], f["type"]), "required": f["required"]} for f in CONTACT])

ENGINE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Audit Employer</title></head><body><main id="app"></main>
<script>
const spec = __SPEC__; let step = 0; const app = document.getElementById('app');
const post = (path, data) => fetch(path, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(data)});
const cookie = n => (document.cookie.split('; ').find(c => c.startsWith(n + '=')) || '').split('=')[1];
function job() { app.innerHTML = '<h1>Audit Role</h1><p>Job description.</p><a href="#apply" id="apply">Apply</a>';
  document.getElementById('apply').onclick = () => setTimeout(spec.workday ? chooser : render, 0); }
function chooser() { app.innerHTML = '<h2>Start Your Application</h2><a href="#manual" id="m">Apply Manually</a>';
  document.getElementById('m').onclick = () => setTimeout(gate, 0); }
function gate() { const s = cookie('wd-session');
  if (!s) { app.innerHTML = '<h2>Sign In</h2><label for=u>Email Address</label><input id=u type=email><label for=p>Password</label><input id=p type=password><button>Sign In</button>'; return; }
  if (s !== 'valid') { app.innerHTML = '<h2>Your session has expired. Please sign in again.</h2><label for=p>Password</label><input id=p type=password><button>Sign In</button>'; return; }
  render(); }
function render() {
  if (spec.gate === 'captcha') { app.innerHTML = '<p>Please verify you are human to continue.</p><iframe src="https://www.google.com/recaptcha/api2/anchor?k=audit"></iframe>'; return; }
  if (spec.gate === 'mfa') { app.innerHTML = '<p>Enter the verification code we sent to your phone.</p><label for=c>Code</label><input id=c autocomplete="one-time-code">'; return; }
  const s = spec.steps[step]; const f = document.createElement('form'); f.onsubmit = e => e.preventDefault();
  s.fields.forEach((x, i) => { const id = 's' + step + 'f' + i; const l = document.createElement('label'); l.htmlFor = id; l.textContent = x.label;
    let el; if (x.type === 'select') { el = document.createElement('select'); x.options.forEach(o => el.add(new Option(o, o))); }
    else if (x.type === 'textarea') el = document.createElement('textarea'); else { el = document.createElement('input'); el.type = x.type; }
    el.id = id; el.name = x.name; el.required = x.required; f.append(l, el); });
  const b = document.createElement('button'); b.type = 'button'; b.textContent = s.button; f.append(b); app.replaceChildren(f);
  b.onclick = async () => {
    if (s.button !== 'Next') { await post('/audit/final', {step}); app.innerHTML = '<h1>Application submitted</h1>'; return; }
    const values = {}; [...f.elements].filter(e => e.name).forEach(e => values[e.name] = e.type === 'file' ? [...e.files].map(x => x.name) : e.type === 'checkbox' ? e.checked : e.value);
    await post('/audit/step', {step, values}); step += 1; render(); }; }
spec.start === false ? render() : job();
</script></body></html>"""


class FixtureSite:
    def __init__(self):
        self.steps, self.finals, self.escapes = [], [], []

    def route(self, route):
        req = route.request
        host = req.url.split("/")[2].lower()
        path = "/" + req.url.split("/", 3)[3].split("#")[0].split("?")[0] if req.url.count("/") >= 3 else "/"
        if host not in (SITE, WD_VALID, WD_NONE, WD_EXPIRED):
            if not req.url.startswith(("data:", "blob:")):
                self.escapes.append(host)
            return route.abort("blockedbyclient")
        if req.method == "POST" and path == "/audit/step":
            self.steps.append({"host": host, "path": req.headers.get("referer", ""), **json.loads(req.post_data or "{}")})
            return route.fulfill(status=200, content_type="application/json", body="{}")
        if req.method == "POST" and path == "/audit/final":
            self.finals.append(req.url)
            return route.fulfill(status=200, content_type="application/json", body="{}")
        key = path.rsplit("/", 1)[0] if path.count("/") > 1 else path
        spec = FORMS.get(key)
        if req.method == "GET" and spec:
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=ENGINE.replace("__SPEC__", json.dumps(spec)))
        return route.abort("blockedbyclient")


# ---------------------------------------------------------------- COI fixture
OPP_H = ["Opportunity ID", "Company", "Role", "Direct Source URL", "Status", "Applied", "Application Authorization", "Resume URL"]
MAN_H = ["Manifest ID", "Opportunity ID", "Approved Resume", "Approved Cover Letter", "Cover Letter Required",
         "Cross-Table Duplicate Gate", "Submission Gate Decision", "Approved Screening Answers", "Supporting Documents", "Form Fingerprint"]
RESUME = "https://drive.google.com/file/d/AUDITRESUMEAPPROVED01/view"
OLD_RESUME = "https://drive.google.com/file/d/AUDITRESUMESTALE0001/view"
COVER = "https://docs.google.com/document/d/AUDITCOVERAPPROVED01/edit"
ANSWERS = json.dumps({"First Name": "Audit", "Email": "audit@example.test",
                      "Are you legally authorized to work in the United States?": "Yes",
                      "Will you now or in the future require sponsorship?": "No"})


def oid(name):
    return f"AUDIT-{RUN}-{name}"


def coi():
    opp, man = [OPP_H], [MAN_H]

    def add(name, company, path, status="Ready", applied="FALSE", auth="Authorized", host=SITE, manifest=True, **m):
        opp.append([oid(name), f"{company} {RUN}", "Audit Analyst", f"https://{host}{path}/{RUN}-{name}", status, applied, auth, OLD_RESUME])
        if manifest:
            man.append([f"M-{oid(name)}", oid(name), m.get("resume", RESUME), m.get("cover", COVER), m.get("cover_required", ""),
                        m.get("dup", "CLEAR"), "HOLD_MANUAL_PREFLIGHT", m.get("answers", ANSWERS), m.get("supporting", ""), m.get("fp", "")])

    add("MULTIPAGE", "Multipage Co", "/multipage")
    add("ANSWERS", "Answers Co", "/answers")
    add("NEWQ", "NewQ Co", "/newq")
    add("CAPTCHA", "Captcha Co", "/captcha")
    add("MFA", "MFA Co", "/mfa")
    add("LEGAL", "Legal Co", "/legal")
    add("EVIDENCE", "Evidence Co", "/evidence")
    add("CHANGED", "Changed Co", "/changed", fp=ORIGINAL_CONTACT_FINGERPRINT)
    add("DOCS", "Docs Co", "/docs", cover="", cover_required="Optional")
    add("PROBE", "Probe Co", "/probe")
    add("WD-VALID", "Workday Valid Co", "/workday", host=WD_VALID)
    add("WD-NONE", "Workday None Co", "/workday", host=WD_NONE)
    add("WD-EXPIRED", "Workday Expired Co", "/workday", host=WD_EXPIRED)
    # Rows that must never reach the queue.
    add("APPLIED", "Applied Co", "/docs", applied="TRUE")
    add("REJECTED", "Rejected Co", "/docs", status="Rejected")
    add("CLOSED", "Closed Co", "/docs", status="Role closed")
    add("WITHDRAWN", "Withdrawn Co", "/docs", status="Withdrawn")
    add("DUPSTATUS", "DupStatus Co", "/docs", status="Duplicate")
    add("UNAUTH", "Unauth Co", "/docs", auth="")
    add("NOTAUTH", "NotAuth Co", "/docs", auth="Not authorized")
    add("NORESUME", "NoResume Co", "/docs", resume="")
    add("NOMANIFEST", "NoManifest Co", "/docs", manifest=False)
    add("PRIOR", "Prior Co", "/docs", status="Applied", applied="TRUE")
    add("PRIOR-AGAIN", "Prior Co", "/docs-repost")
    add("TWIN-A", "Twin Co", "/docs")
    add("TWIN-B", "Twin Co", "/docs-other")
    return {"opportunities": opp, "manifests": man}


# ---------------------------------------------------------------- audits
results = []


def audit(number, name, ok, detail=""):
    results.append((number, name, bool(ok), detail))
    print(f"A{number:02d} {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""), flush=True)


def main():
    from playwright.sync_api import sync_playwright

    site = FixtureSite()
    status, _ = call("/api/audit/purge", {})
    assert status == 200, "purge failed"

    # A01 connectivity and lockouts on the live Worker
    s_health, health = call("/health", None, token=None, method="GET")
    s_exec, ex = call("/api/execute", {}, token=None)
    s_claim, _ = call("/api/runner/claim", {"audit": True}, token=OPERATOR)
    audit(1, "Live Worker reachable; /api/execute locked; runner route rejects operator token",
          s_health == 200 and health.get("submissions_enabled") is False and s_exec == 403 and ex.get("reason") == "LIVE_SUBMISSION_DISABLED" and s_claim == 401,
          f"{s_health} {s_exec} {s_claim}")

    fixture = coi()
    s_imp, imp = call("/api/coi/import", {"audit": True, "fixture": fixture})
    queued, reasons = set(imp.get("queued", [])), {b["opportunity_id"]: b["reason"] for b in imp.get("blocked", [])}
    expected_queue = {oid(n) for n in ("MULTIPAGE", "ANSWERS", "NEWQ", "CAPTCHA", "MFA", "LEGAL", "EVIDENCE", "CHANGED", "DOCS",
                                       "PROBE", "WD-VALID", "WD-NONE", "WD-EXPIRED", "TWIN-A")}

    # Wait for the live queue consumer to persist jobs.
    deadline, ready = time.monotonic() + 120, 0
    while time.monotonic() < deadline:
        ready = call("/api/prep/summary", {"audit": True})[1].get("jobs", {}).get("READY", 0)
        if ready >= len(expected_queue):
            break
        time.sleep(3)
    # The live Career Opportunity Database must also be readable server-side (dry run: read + filter, no enqueue).
    s_live, live = call("/api/coi/import", {"dry_run": True})
    live_ok = s_live == 200 and live.get("dry_run") is True and live.get("counts", {}).get("rows", 0) > 0
    audit(2, "Live COI read via Google service account + fixture import -> Cloudflare Queue -> consumer -> D1 jobs",
          live_ok and s_imp == 200 and queued == expected_queue and ready == len(expected_queue),
          f"live_coi={s_live}:{live.get('reason') or live.get('counts')} import={s_imp} queued={len(queued)} ready={ready}")
    if live_ok:
        print(f"     live COI: {live['counts']} eligible={live['eligible']} blocked={live['blocked_summary']}")

    for n, (row, reason, label) in enumerate([
        ("APPLIED", "BLOCK_APPLIED", "Applied rows blocked"),
        ("REJECTED", "BLOCK_REJECTED", "Rejected rows blocked"),
        ("CLOSED", "BLOCK_CLOSED", "Closed rows blocked"),
        ("WITHDRAWN", "BLOCK_WITHDRAWN", "Withdrawn rows blocked"),
        ("DUPSTATUS", "BLOCK_DUPLICATE", "Duplicate-status rows blocked"),
    ], start=3):
        audit(n, label, reasons.get(oid(row)) == reason and oid(row) not in queued, reasons.get(oid(row)))
    audit(8, "Unauthorized rows blocked (blank and 'Not authorized')",
          reasons.get(oid("UNAUTH")) == reasons.get(oid("NOTAUTH")) == "BLOCK_UNAUTHORIZED", f"{reasons.get(oid('UNAUTH'))} {reasons.get(oid('NOTAUTH'))}")
    audit(9, "Document-incomplete rows blocked (no approved résumé; no manifest)",
          reasons.get(oid("NORESUME")) == reasons.get(oid("NOMANIFEST")) == "BLOCK_DOCUMENTS_INCOMPLETE")
    audit(11, "Unapplied repost of an applied role blocked as duplicate", reasons.get(oid("PRIOR-AGAIN")) == "BLOCK_DUPLICATE_OF_APPLIED",
          reasons.get(oid("PRIOR-AGAIN")))

    s_re, again = call("/api/coi/import", {"audit": True, "fixture": fixture})
    re_reasons = {b["opportunity_id"]: b["reason"] for b in again.get("blocked", [])}
    ready_after = call("/api/prep/summary", {"audit": True})[1].get("jobs", {}).get("READY", 0)
    audit(12, "Re-import creates no second queue entry (BLOCK_ALREADY_QUEUED, job count unchanged)",
          s_re == 200 and not again.get("queued") and all(re_reasons.get(i) == "BLOCK_ALREADY_QUEUED" for i in expected_queue) and ready_after == ready,
          f"queued={again.get('queued')} ready={ready_after}")
    audit(13, "Same company+role twice in one import: second row blocked", reasons.get(oid("TWIN-B")) == "BLOCK_DUPLICATE", reasons.get(oid("TWIN-B")))

    # Run the browser runner against the live queue.
    client = WorkerClient(BASE, RUNNER, audit=True)
    sessions = {
        WD_VALID: {"cookies": [{"name": "wd-session", "value": "valid", "domain": WD_VALID, "path": "/", "expires": -1,
                                "httpOnly": False, "secure": True, "sameSite": "Lax"}], "origins": []},
        WD_EXPIRED: {"cookies": [{"name": "wd-session", "value": "expired", "domain": WD_EXPIRED, "path": "/", "expires": -1,
                                  "httpOnly": False, "secure": True, "sameSite": "Lax"}], "origins": []},
    }
    outcomes, payloads = {}, {}
    original_claim = client.claim
    probe = None

    def capture_claim():
        # The PROBE job is held back so A25 can attempt a forged "submitted" completion on it.
        nonlocal probe
        claimed = original_claim()
        if claimed and probe is None and claimed["job"]["opportunity_id"] == oid("PROBE"):
            probe = claimed
            claimed = original_claim()
        if claimed:
            payloads[claimed["job"]["opportunity_id"]] = claimed["job"]
        return claimed
    client.claim = capture_claim

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        runner = PrepRunner(client, browser, router=site.route, workday_sessions=sessions, synthetic_documents=True)
        for _ in range(40):
            out = runner.run_once()
            if out is None:
                break
            outcomes[out["opportunity_id"]] = out
        browser.close()

    st = lambda name: outcomes.get(oid(name), {}).get("result", {}).get("status")  # noqa: E731
    steps_for = lambda name: [s for s in site.steps if f"{RUN}-{name}" in s["path"]]  # noqa: E731

    multipage = steps_for("MULTIPAGE")
    job_docs = payloads.get(oid("MULTIPAGE"), {}).get("documents", {})
    docs_job = payloads.get(oid("DOCS"), {}).get("documents", {})
    audit(10, "Manifest is authoritative: approved résumé selected over the Opportunities résumé; files attached",
          job_docs.get("resume") == RESUME and job_docs.get("cover_letter") == COVER and docs_job.get("cover_letter") == ""
          and multipage and multipage[0]["values"].get("resume") == ["resume-0.pdf"] and multipage[0]["values"].get("cover_letter") == ["cover_letter-0.pdf"],
          f"{job_docs} {multipage[:1]}")
    answers = steps_for("ANSWERS")
    audit(14, "Approved screening answers reused verbatim",
          st("ANSWERS") == "READY_FOR_REVIEW_NOT_SUBMITTED" and answers and answers[0]["values"].get(WORK_AUTH[0]["name"]) == "Yes"
          and answers[0]["values"].get(WORK_AUTH[1]["name"]) == "No", f"{st('ANSWERS')} {answers}")
    newq = outcomes.get(oid("NEWQ"), {}).get("result", {})
    audit(15, "Genuinely new question flagged, not answered",
          newq.get("status") == "HOLD_NEW_QUESTIONS" and newq.get("new_questions") == ["Describe your experience leading a cross-functional launch"]
          and len(steps_for("NEWQ")) == 1, f"{newq}")
    mp = outcomes.get(oid("MULTIPAGE"), {}).get("result", {})
    audit(16, "Multi-page navigation reaches review page and stops (3 pages)",
          mp.get("status") == "READY_FOR_REVIEW_NOT_SUBMITTED" and mp.get("pages") == 3 and len(multipage) == 2, f"{mp}")
    wd = outcomes.get(oid("WD-VALID"), {}).get("result", {})
    audit(17, "Workday with approved session: Apply -> Apply Manually -> 3 pages -> stop",
          wd.get("status") == "READY_FOR_REVIEW_NOT_SUBMITTED" and wd.get("pages") == 3 and len(steps_for("WD-VALID")) == 2, f"{wd}")
    audit(18, "Workday without session stops at sign-in", st("WD-NONE") == "HOLD_SIGN_IN", st("WD-NONE"))
    audit(19, "Workday expired session stops", st("WD-EXPIRED") == "HOLD_SESSION_EXPIRED", st("WD-EXPIRED"))
    audit(20, "CAPTCHA stops safely (not solved, not bypassed)", st("CAPTCHA") == "HOLD_CAPTCHA" and not steps_for("CAPTCHA"), st("CAPTCHA"))
    audit(21, "MFA stops safely", st("MFA") == "HOLD_MFA" and not steps_for("MFA"), st("MFA"))
    audit(22, "Legal attestation stops before the box is checked",
          st("LEGAL") == "HOLD_LEGAL_ATTESTATION" and len(steps_for("LEGAL")) == 1, st("LEGAL"))
    audit(23, "Missing evidence (required portfolio, none approved) stops", st("EVIDENCE") == "HOLD_MISSING_EVIDENCE" and not steps_for("EVIDENCE"),
          st("EVIDENCE"))
    audit(24, "Employer form change detected against manifest fingerprint", st("CHANGED") == "HOLD_FORM_CHANGED" and not steps_for("CHANGED"),
          st("CHANGED"))

    # A25: submission lockout end to end.
    bad = {"status": "READY_FOR_REVIEW_NOT_SUBMITTED", "pages": 1, "submitted": True, "final_submit_clicked": True}
    s_probe, probe_resp = (call("/api/runner/complete", {"job_id": probe["id"], "result": bad, "audit": True}, token=RUNNER)
                           if probe else (0, {}))
    summary = call("/api/prep/summary", {"audit": True})[1]
    all_false = all(o["result"]["submitted"] is False and o["result"]["final_submit_clicked"] is False for o in outcomes.values())
    audit(25, "No application submitted: zero final-submit requests, all results submitted=false, Worker rejects a submitted claim",
          not site.finals and all_false and len(outcomes) == 13 and s_probe == 422
          and probe_resp.get("reason") == "SUBMISSION_VIOLATION" and summary.get("submission_violations") == 1
          and summary.get("jobs", {}).get("VIOLATION") == 1 and call("/api/execute", {}, token=None)[0] == 403,
          f"finals={len(site.finals)} escapes={set(site.escapes)} outcomes={len(outcomes)} probe={s_probe} summary={summary}")

    results.sort()
    passed = sum(ok for _, _, ok, _ in results)
    print(f"\n{passed}/{len(results)} audits passed (run {RUN}); live summary: {summary}")
    call("/api/audit/purge", {})
    return 0 if passed == len(results) == 25 else 1


if __name__ == "__main__":
    sys.exit(main())
