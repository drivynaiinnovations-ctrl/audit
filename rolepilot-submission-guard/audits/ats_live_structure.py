"""Observe-only check of CURRENT employer routes and form structure (Greenhouse, Lever, Workday).

Runs the real prep_runner.Preparer against one live public posting per ATS with every data-entry path disabled:
  * no approved answers and no documents are supplied, and fill/upload methods raise if reached;
  * any POST/PUT/PATCH whose URL looks like an application/apply/submit endpoint is aborted;
  * the runner's own guard still forbids clicking a final submit control.
So nothing is typed, uploaded or submitted. Output: route status, field shape, résumé/cover detection, stop state.
Uses only public job-board APIs to pick a posting. Run manually: python audits/ats_live_structure.py
"""

import json
import re
import sys
import time
from urllib.error import HTTPError
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prep_runner import COLLECT_JS, COVER_LABEL, RESUME_LABEL, Preparer  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
WRITE_PATH = re.compile(r"appl(y|ication)|submit|candidate|upload|resume", re.I)


def get_json(url, body=None):
    req = Request(url, None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
                  headers={"user-agent": UA, "accept": "application/json", "content-type": "application/json"})
    for attempt in range(4):  # public job-board APIs rate-limit; back off politely
        try:
            with urlopen(req, timeout=30) as res:
                return json.load(res)
        except HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))


def postings():
    gh = get_json("https://boards-api.greenhouse.io/v1/boards/doordashusa/jobs")["jobs"][0]["absolute_url"]
    lv = get_json("https://api.lever.co/v0/postings/vida?mode=json&limit=1")[0]["applyUrl"]
    wd = get_json("https://openlane.wd115.myworkdayjobs.com/wday/cxs/openlane/OPENLANE_Careers/jobs",
                  {"limit": 1, "offset": 0, "appliedFacets": {}, "searchText": ""})["jobPostings"][0]["externalPath"]
    return [("greenhouse", "DoorDash", gh), ("lever", "Vida", lv),
            ("workday", "OPENLANE", "https://openlane.wd115.myworkdayjobs.com/en-US/OPENLANE_Careers" + wd)]


class ObserveOnly(Preparer):
    def apply_answer(self, *a, **k):
        raise PermissionError("OBSERVE_ONLY_NO_DATA_ENTRY")


def main():
    from playwright.sync_api import sync_playwright

    blocked, report = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for provider, employer, url in postings():
            context = browser.new_context(user_agent=UA, accept_downloads=False, service_workers="block")

            def guard(route, _blocked=blocked):
                r = route.request
                if r.method not in ("GET", "HEAD", "OPTIONS") and WRITE_PATH.search(r.url.split("?")[0]):
                    _blocked.append(f"{r.method} {r.url.split('?')[0][:90]}")
                    return route.abort("blockedbyclient")
                return route.continue_()
            context.route("**/*", guard)
            page = context.new_page()
            job = {"source_url": url, "provider": provider, "approved_answers": {}, "documents": {}}
            prep = ObserveOnly(page, job, lambda slot, index: None)
            try:
                result = prep.run()
                snap = page.evaluate(COLLECT_JS)
            except Exception as exc:  # report, keep going
                result, snap = {"status": "ERROR " + type(exc).__name__, "pages": 0}, {"fields": [], "buttons": []}
            fields = snap["fields"]
            report.append({
                "ats": provider, "employer": employer, "route": re.sub(r"(/jobs?/)[^/?]+.*$", r"\1…", url),
                "stop": result["status"], "pages": result["pages"], "submitted": result.get("submitted", False),
                "fields": len(fields), "required": sum(f["required"] for f in fields),
                "file_inputs": sum(f["type"] == "file" for f in fields),
                "resume_detected": any(f["type"] == "file" and RESUME_LABEL.search(f.get("hint") or f["label"]) for f in fields),
                "cover_detected": any(f["type"] == "file" and COVER_LABEL.search(f.get("hint") or f["label"]) for f in fields),
                "field_types": sorted({f["type"] for f in fields}),
                "missing": result.get("detail", ""), "new_questions": len(result.get("new_questions", [])),
                "final_url_host": page.url.split("/")[2],
            })
            context.close()
        browser.close()
    for r in report:
        print(json.dumps(r))
    print(json.dumps({"blocked_write_requests": blocked}))
    ok = all(r["submitted"] is False for r in report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
