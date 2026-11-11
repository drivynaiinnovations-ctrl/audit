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

- Google access is a read-only service account held only as the Worker secret `GOOGLE_SERVICE_ACCOUNT_JSON`; the sheet ID is the secret `COI_SHEET_ID`.
- Import rules (`cloudflare/coi.mjs`): only unapplied, active rows with `Application Authorization` explicitly authorized; applied, rejected,
  closed, withdrawn, duplicate, unauthorized and document-incomplete rows are blocked. Application Manifests are authoritative for the
  résumé, cover letter, supporting documents and approved screening answers.
- Duplicate prevention: in-sheet identity/URL checks, reposts of applied roles, and a D1 registry that blocks re-queuing.
- The runner reuses only exact approved answers, flags new questions, and stops for CAPTCHA, MFA, sign-in, expired sessions,
  legal attestations, missing evidence and employer form changes. It never clicks a final submit control, and the Worker rejects any
  result that reports a submission.
- `audits/e2e_audits.py` runs 25 end-to-end audits against the live Worker/Queue/D1 with synthetic `AUDIT-` data and local employer fixtures.

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
