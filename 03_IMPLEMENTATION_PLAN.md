# Execution phases and checkpoints

P0 Audit and baseline: repo map, branch safety, dependency environment, existing tests, documented decisions. Keep baseline output.
P1 Domain + migrations: student/teacher/course/enrollment/class-session/attendance/consent/audit data, constraints and indexes; local SQLite first, Postgres-compatible; transaction test.
P2 Recognition adapter: wrap real CamBrain identity matcher; enrollment and template service; unknown, low confidence, ambiguous, multiple faces rejected or explicitly individually reviewed; no detections-only attendance; test adapter with synthetic responses (not synthetic biometric performance).
P3 Backend APIs: auth/authorization, roster, sessions, enroll, attendance events and manual corrections; timezone UTC; idempotency and consistent error handling; API tests.
P4 UI: admin/teacher dashboard, course/roster, consent-aware enrollment, live check-in status, session management, attendance table, correction modal and CSV. Integrate into existing UI and branding.
P5 Real-world run: consented local webcam end-to-end, repeat frames, unknown person, wrong class, ambiguous faces, stale session, API unauthorized, manual fallback. Record actual observations; no performance claims without data.
P6 Cloud readiness: configure managed PostgreSQL via DATABASE_URL, migration and TLS settings, hosted API dashboard deploy example WITHOUT actual deployment; maintain on-device inference, cloud stores minimum attendance data only; test DB switch when database available.
P7 Tests/doc/handoff: lint/typecheck/unit/integration/UI smoke, threat test, full setup, known blockers, evidence and demo script. Every phase leaves code/tests/docs, not only prose.

Proceed phase by phase without requiring user prompts except irreversible actions/credentials. Prioritize working integrated vertical slice over extra animations or advanced analytics. If blocked by model availability, deliver non-biometric app functionality plus honest recognition-disabled state.
