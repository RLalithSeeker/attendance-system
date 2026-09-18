# Attendance System — HANDOFF

State as of 2026-09-18 · standalone project at `C:\Users\starl\Downloads\attendance-system`

## What is done
- `attendance/` package (migrate, database, auth, schemas, matcher_providers,
  recognition_adapter, service, routers, app, errors) implementing the
  `CamBrain_Attendance_OneShot` spec as a SEPARATE project — zero dependency on
  the CamBrain engine.
- `main.py` — standalone FastAPI entry: `/` (teacher UI),
  `/attendance/health` (effective mode), router at `/api/attendance/v1`.
- `templates/attendance.html` — teacher UI (courses, students, consent,
  enroll-by-code, sessions, manual mark, live demo recognize, summary, export).
- `tests/test_attendance_api.py` — **18 attendance tests pass**, 100%
  camera-free (demo + disabled runs).
- `docs/` — REPO_AUDIT (provenance of the design), ADR (9), TEST_RESULTS, ENV,
  HANDOFF.

## Run it (NO camera required)
```
python -m pytest tests -q                 # 18 passed
python main.py                            # http://localhost:8000
```
With no insightface installed, `RECOGNITION_MODE=demo` shows full recognition
flow (clearly flagged); unset → effective `disabled`.

## Seed
`teacher@demo.local` / `demo1234` · course CS201 · students S1001–S1003 · no
consents by default (`seed_demo(db, with_biometric=False)`), applied idempotently
on first boot by `main.py`.

## Tests exploit
- `tests/test_attendance_api.py` fixtures: `demo_ctx` (demo matcher, seeded),
  `disabled_ctx` (no matcher), `rate_ctx` — all module-scoped, isolated SQLite
  files, built via `create_app(runtime)` — never hit `main.py`.
- `_open_session(c,h,course_id)` closes any active session for a course before
  opening a fresh one (one active session per course is enforced → 409).

## Known limits / next steps (out of scope for this ship)
1. **Real recognition is the user's camera step** — `InsightFaceProvider` is
   lazy and fail-closed when `insightface` is absent. To activate later:
   `pip install insightface onnxruntime`, `RECOGNITION_MODE=real`, restart, and
   only then enroll real templates + recognize real frames. Health reports
   `"mode":"real"` when armed.
2. **UI browser smoke** — hand-tested via API contract; drive it at 390px even
   though it is not deployed (repo rule: mobile-friendly before any web deploy).
3. **Cost throttle** — 6/min/token cap is the only `/recognize` throttle today;
   revisit when pricing lands.
4. `docs/REPO_AUDIT.md` retains the original CamBrain checkout audit it was
   derived from; it is provenance, not a live claim about this repo.

## Repo hygiene reminders
- Commit with targeted `git add <paths>` — never `add -A`.
- System python 3.13.5 (fastapi/pydantic/pytest/httpx/cv2/numpy) runs the suite;
  insightface NOT importable here by design.
- No secrets in the repo; tokens hashed at rest in SQLite.