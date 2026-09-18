# Demo / troubleshooting quick runbook

Before demo: inspect env for secrets, start actual documented backend/frontend, verify `/health` and DB migrations, teacher login, allow browser camera, have consented volunteer, check model availability, confirm class time and timezone. Show manual fallback if GPU/model absent. Use separate disposable dummy records; no real student data in screenshots/repo.

Troubleshoot: face detected but not recognized → inspect adapter/galleries/model version and enrollment, don't lower threshold blindly; all unknown → inspect calibration and metric direction; repeated attendance → verify UNIQUE constraint and upsert transaction; webcam denied → camera permission/HTTPS secure context; blank UI → check API origin/CORS and startup logs; SQLite/Postgres differences → run migration tests; no cloud creds → mark NOT DEPLOYED.

Collect actual console output, screen evidence without biometrics, and note tested commit/date/hardware. Delete volunteer templates after test if requested.
