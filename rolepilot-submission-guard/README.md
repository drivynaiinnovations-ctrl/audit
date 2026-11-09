# RolePilot Submission Guard (prototype)

A fail-closed, standard-library Python submission preflight. No ATS submission or email sending is implemented. This repository is public: **do not commit personal data, real applications, API credentials or Google Sheets exports**.

Run `python -m unittest discover -s tests -v`. The service uses SQLite with transactional duplicate reservations. It is a prototype, not a deployed integration with the actual RolePilot executor or Google Sheets. Production submission must remain disabled until authentication, data synchronization and executor enforcement are independently verified.

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
