# Attendance Suite — Test Results

Run: `python -m pytest tests -q` (system Python 3.13.5, no camera, no insightface)

**Result: 18 passed** (all attendance; 100% camera-free demo + disabled runs).

## Tests (`tests/test_attendance_api.py`)

| Group | Tests | What they prove |
|---|---|---|
| Auth | `test_login_ok`, `test_login_bad_password` | token issue + envelope; bad creds 401 |
| Guard rails | `test_requires_auth_401`, `test_requires_valid_token_401` | no/malformed token refused |
| Students | `test_students_seeded`, `test_student_duplicate_409` | seed S1001–S1003; dup code 409 |
| Enrollment | `test_enroll_by_code_lowercase`, `test_enroll_requires_identifier`, `test_enroll_unknown_code_422` | `student_ids` OR `student_codes` (case-insensitive); neither → 422 |
| Consent + templates | `test_consent_then_template_flow`, `test_consent_version_min_length`, `test_template_requires_consent_403` | consent → template ok; short version 422; no consent → 403 |
| Full session flow | `test_full_session_demo_flow` | open session → recognize `matched` (demo) → request_id replay idempotent → summary counts+records → close |
| Manual | `test_manual_mark_by_code`, `test_manual_unknown_code_422` | manual mark w/ student_code; unknown 422 |
| Export | `test_export_csv_injection_escaped` | hostile name `=SUM(A1:A9)` apostrophe-prefixed, never a live formula |
| Fail-closed | `test_recognize_fail_closed_when_disabled` | matcher disabled → 503 `matcher_unavailable`, no record written (manual still works, close works) |
| Rate limit | `test_recognize_rate_limited` | 6×200 then 429 `rate_limited` per token |
| Misc | `test_session_not_found`, `test_courses_listing` | 404 unknown session; courses carry `enrolled_count` |

## Coverage notes
- Isolated file-backed SQLite per fixture (`demo_ctx`, `disabled_ctx`,
  `rate_ctx`), module-scoped `TestClient` via `create_app(runtime)` — no server
  boot, no engine, no network.
- `test_recognize_fail_closed_when_disabled` asserts **503**, not 200: disabled
  mode refuses at the router before event logging (deliberate fail-closed).
- `_open_session` helper closes any active session for a course first because
  the shared demo fixture forbids two concurrent active sessions per course.

## What is NOT covered (honest scope)
- Real InsightFace recognition — NO camera on this machine by design; the
  `real` matcher path is unexercised here. Demo-only matching is what the suite
  drives, and `real` is fail-closed until the user turns the camera on later.
- Web UI (`templates/attendance.html`) — no browser automation in this suite.