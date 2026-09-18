# Tests and truthful evidence

Unit: roster restrictions, session transitions, consent state machine, timezone UTC, attendance status, correction reason required, recognition adapter outcomes. DB: unique(session_id,student_id), race between simultaneous requests, rollback on partial failure, FK, migrations SQLite; PostgreSQL tests if available.

API: 401/403 for all sensitive routes, unauthorized course enumeration prevented, student_id forgery not accepted, no consent rejects enrollment, closed sessions reject marks, absent→present updates audited, CSV course-scoped/sanitized; 503 if matcher missing, malformed/oversized image rejected.

Recognition with injectable deterministic fake adapter: matched enrolled, unknown, ambiguous, multiple/no face, out-of-roster, withdrawn consent, same face across frames marked once, model unavailable. These prove app behavior only, not actual recognition accuracy.

Real E2E (only permissioned subjects): consent/enroll → capture → identity match → check-in → duplicate → unknown person → close/export; log model, hardware, sample counts, observations and failures. Evaluate thresholds with a separate consented validation split; don't invent accuracy. If camera/weights missing, mark BLOCKED.

Frontend smoke: sign-in, roster, session start, camera permission denied, webcam cleanup, status states, manual correction, download; accessibility keyboard and error states. Run existing suite + new suite + formatter/lint/typecheck, capture exact commands and results. CI optionally runs no-camera deterministic tests.

Acceptance gate in `12_ACCEPTANCE_AND_HANDOFF.md`; save report `docs/attendance/TEST_RESULTS.md` with PASSED/FAILED/BLOCKED and actual logs. No fabricated test output.
