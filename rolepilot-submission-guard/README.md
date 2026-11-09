# RolePilot Submission Guard (prototype)

A fail-closed, standard-library Python submission preflight. No ATS submission or email sending is implemented. This repository is public: **do not commit personal data, real applications, API credentials or Google Sheets exports**.

Run `python -m unittest discover -s tests -v`. The service uses SQLite with transactional duplicate reservations. It is a prototype, not a deployed integration with the actual RolePilot executor or Google Sheets. Production submission must remain disabled until authentication, data synchronization and executor enforcement are independently verified.

## ATS inventory from prior searches

| ATS | Example | Browser test scope |
| --- | --- | --- |
| Greenhouse | DoorDash | Simulated form preparation and submission block |
| Lever | Vida | Simulated form preparation and submission block |
| Workday | OPENLANE | Simulated sign-in handoff and request block |
| Ashby | Promise, Prelim | Backlog |
| UKG | Tatte Bakery | Backlog |
| Rippling | WPM Real Estate | Backlog |
| Harri | CAVA | Backlog |
| Workable | Checkmate, HeyTaco | Backlog |
| iCIMS | LMI | Backlog |
| Teamtailor | AllTech, SafelyYou | Backlog |
| SAP SuccessFactors | Wyndham | Backlog |
| ADP | WesBanco | Backlog |
| Jobvite | Manhattan Strategy Group | Backlog |
| CareerPlug | GoIntellects | Backlog |

LinkedIn, Indeed, and SimplyHired are tracked as job sources. SmartRecruiters is a candidate for the inventory pending an employer example.
