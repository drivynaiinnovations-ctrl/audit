# RolePilot Submission Guard (prototype)

A fail-closed, standard-library Python submission preflight. No ATS submission or email sending is implemented. This repository is public: **do not commit personal data, real applications, API credentials or Google Sheets exports**.

Run `python -m unittest discover -s tests -v`. The service uses SQLite with transactional duplicate reservations. `coi_connector.py` imports unapplied COI roles through an injected authenticated Sheets reader, reads current status and duplicate gates, and selects the latest approved manifest résumé and supporting documents. It contains no credentials and no submission method. Production submission remains disabled.

## COI database contract

- Role source: `Opportunities!A1:AP5003`
- Document authority: `Application Manifests!A1:AP250`
- Excludes applied, closed, rejected, withdrawn, duplicate, invalid-source, and document-incomplete records
- Prefers the latest manifest-approved résumé and cover letter, then falls back to the opportunity package
- Requires an HTTPS source and résumé; otherwise it fails closed
- CI repeats the complete import and selection audit 25 times and verifies deterministic, submission-free output

## Screening and browser runner

- Exact normalized matching reuses only explicitly approved screening answers
- Genuinely new questions stop the workflow and are returned for approval
- Multi-page preparation has a bounded page limit and always stops before final submission
- Workday sign-in, CAPTCHA, MFA, and expired sessions produce distinct safe hold states
- The scheduled GitHub browser-runner audit executes every 15 minutes with concurrency control
- Cloudflare remains the authenticated planning/queue boundary; live submissions remain disabled

## Production preparation pipeline (submission disabled)

`Career Opportunity Database` -> Worker `/api/coi/import` (cron every 30 min) -> Cloudflare Queue `rolepilot-prep`
(DLQ `rolepilot-prep-dlq`) -> queue consumer -> D1 `prep_jobs` -> scheduled GitHub runner (`prep_runner.py`, every 15 min).

- Google access is a dedicated service account (no project roles) held only as the Worker secret `GOOGLE_SERVICE_ACCOUNT_JSON`. It is shared as
  Editor on the one COI spreadsheet (for write-back) and as Viewer on approved documents; the sheet ID is the secret `COI_SHEET_ID`.
- Import rules (`cloudflare/coi.mjs`): only unapplied, active rows with `Application Authorization` explicitly authorized; applied, rejected,
  closed, withdrawn, duplicate, unauthorized and document-incomplete rows are blocked. Application Manifests are authoritative for the
  résumé, cover letter, supporting documents and approved screening answers.
- Duplicate prevention: in-sheet identity/URL checks, reposts of applied roles, and a D1 registry that blocks re-queuing.
- The runner reuses only exact approved answers, flags new questions, and stops for CAPTCHA, MFA, sign-in, expired sessions,
  legal attestations, missing evidence and employer form changes. It never clicks a final submit control, and the Worker rejects any
  result that reports a submission.
- `audits/e2e_audits.py` runs 25 end-to-end audits against the live Worker/Queue/D1 with synthetic `AUDIT-` data and local employer fixtures.

## Tracker write-back (`cloudflare/writeback.mjs`)

Runner result -> `/api/runner/complete` -> D1 `prep_writeback` (one row per job) -> queue message `{kind:"writeback"}` (+ cron sweep)
-> Opportunities columns `RolePilot Prep Status`, `RolePilot Prep Updated At`, `RolePilot Prep Result` only.

- The row is located by `Opportunity ID` on every attempt and its company/role identity is verified, so sorting/moving rows is safe.
  The ID is re-checked immediately before writing and the write is verified afterwards; a sort that lands in between is detected,
  the wrong row is restored from the pre-write snapshot, and the attempt is retried.
- Idempotent: a repeated runner completion is acknowledged as a duplicate; a redelivered write-back with the same job marker performs no update.
- Newer timestamps and manual edits (any value RolePilot did not write) are preserved (`SKIPPED_NEWER` / `SKIPPED_MANUAL`).
- Status, Applied, Applied At, Application Authorization and every other column are never written. A result claiming a submission is
  rejected before write-back. Status values are always `PREP <status>`; `READY_FOR_REVIEW_NOT_SUBMITTED` never means submitted.
- `PREP_IMPORT_SCOPE` (Worker var): unset = live imports queue only `RP-SYNTH-` verification rows; `all` = every eligible row.
- Approved answers come from the manifest's structured columns (Full Name, Email, Phone, Street Address, Candidate Location;
  Work Authorization / Sponsorship only when literally yes/no) and the `Live Field Inventory / Answer Map` (explicit entries win).
- Operator routes: `/api/coi/writeback/setup` (adds the three headers once), `/api/coi/writeback/status`, `/api/coi/writeback/sweep`,
  `/api/coi/synthetic/seed` (appends a labeled `RP-SYNTH-` role whose form is served by the Worker at `/synthetic/apply/<id>`).
- `audits/ats_live_structure.py` checks current Greenhouse/Lever/Workday routes and form structure observe-only (no data entry,
  application POSTs blocked). Patterns it found are pinned in `browser_tests/test_live_patterns.py`.

## ATS inventory from prior searches

| ATS | Example | Browser test scope |
| --- | --- | --- |
| Greenhouse | DoorDash | Simulated form preparation and submission block |
| Lever | Vida | Simulated form preparation and submission block |
| Workday | OPENLANE | Simulated sign-in handoff, open form preparation, and submission block |
| Ashby | Promise, Prelim | Shared simulated form, résumé attachment, submission block |
| UKG | Tatte Bakery | Shared simulated form, résumé attachment, submission block |
| Rippling | WPM Real Estate | Shared simulated form, résumé attachment, submission block |
| Harri | CAVA | Shared simulated form, résumé attachment, submission block |
| Workable | Checkmate, HeyTaco | Shared simulated form, résumé attachment, submission block |
| iCIMS | LMI | Shared simulated form, résumé attachment, submission block |
| Teamtailor | AllTech, SafelyYou | Shared simulated form, résumé attachment, submission block |
| SAP SuccessFactors | Wyndham | Shared simulated form, résumé attachment, submission block |
| ADP | WesBanco | Shared simulated form, résumé attachment, submission block |
| Jobvite | Manhattan Strategy Group | Shared simulated form, résumé attachment, submission block |
| CareerPlug | GoIntellects | Shared simulated form, résumé attachment, submission block |

LinkedIn, Indeed, and SimplyHired are tracked as job sources. SmartRecruiters passes the shared simulated form test. Its employer example is pending.
