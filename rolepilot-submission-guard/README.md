# RolePilot Submission Guard (prototype)

A fail-closed, standard-library Python submission preflight. No ATS submission or email sending is implemented. This repository is public: **do not commit personal data, real applications, API credentials or Google Sheets exports**.

Run `python -m unittest discover -s tests -v`. The service uses SQLite with transactional duplicate reservations. It is a prototype, not a deployed integration with the actual RolePilot executor or Google Sheets. Production submission must remain disabled until authentication, data synchronization and executor enforcement are independently verified.
