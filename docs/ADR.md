# Attendance System — Architecture Decision Record

Date: 2026-09-18 · Standalone project · Scope: `attendance/` package +
`main.py` entry + `templates/attendance.html`

## ADR-001 — Attendance is its own project, decoupled from any engine

**Decision.** This is a SEPARATE repository. The `attendance/` package
(database, auth, schemas, recognition adapter, matcher providers, service,
routers, app assembly, migrate) runs as a standalone FastAPI server via the
repo-root `main.py`. There is no import of, or dependency on, the CamBrain
surveillance engine.

**Why.** The product is a bounded, privacy-first classroom tool. Running it
inside a detection engine couples upgrades, tests (need a heavy Python env) and
deployment to something unrelated to it.

**Consequences.** The matcher is a pluggable provider (ADR-003): the app is
fully testable with $0$ hardware, and `real` matching is opted-in later.

## ADR-002 — Envelope + bearer auth, tokens hashed at rest

**Decision.** Every endpoint answers `{"ok": true, "data": ...}` or
`{"ok": false, "error": {"code", "message", "request_id"}}`. Auth is
`Authorization: Bearer <token>`; the DB stores SHA-256 of the token, 12h TTL.

**Why.** Flat contract for the teacher UI; hashed-at-rest tokens (never the raw
token) keep secrets out of the database.

## ADR-003 — Provider seam; match thresholds owned by the adapter

**Decision.** `RECOGNITION_MODE` ∈ `{auto, demo, real, disabled}`; the adapter
delegates one method — `match(image_bytes) -> ranked[(code, sim)]` — to a
provider (`matcher_providers.py`). The adapter owns the gates:
below `0.45` → unknown, top-vs-second gap `< 0.02` → ambiguous, `≥ 0.55` →
match. Providers raise `NoFaceError / MultiFaceError / LowQualityError /
UnknownFaceError`; none of them fabricate scores. The default provider
(`InsightFaceProvider`) matches the app's OWN enrolled templates (DB stores
only template file paths — never face blobs/embeddings). `real` mode without
an available provider → effective `disabled` (fail-closed).

**Why.** One seam to swap the matcher; consistent fail-closed statuses;
no hard-coded pricing/allocation in the API layer.

## ADR-004 — Consent is a hard prerequisite for biometric enrollment

**Decision.** `POST /biometric-consents` (version, purpose) then `POST
/templates` (student_id + image ≥80×80, ≤1.5MB). Enrolling a template without a
current consent row → `403`. `with_biometric=False` seeding is the default;
nothing is silently enrolled.

**Why.** Privacy posture; avoids orphaned biometric templates.

## ADR-005 — request_id idempotent replay + per-token rate limit

**Decision.** A recognition that carries a `request_id` already seen returns
that original event with `idempotent_replay=True` (no double-marking).
`/recognize` is rate-limited to 6/min/token (sliding, per service instance).

**Why.** UI retries on timeout must not double-count a student; per-token cap
bounds cost exposure without a global lock.

## ADR-006 — CSV export is formula-safe

**Decision.** `export.csv` escapes any field containing `,`, `"`, newline, tab,
or leading `= + - @` by apostrophe-prefixing and quoting. A name like
`=SUM(A1:A9)` ships as `"'=SUM(A1:A9)"` so spreadsheets never evaluate it.

**Why.** Standard CSV-injection hardening; verified by a dedicated test on a
hostile name.

## ADR-007 — Time always stored UTC, display-timezone per session

**Decision.** Rows store `iso_utc()` timestamps. A session carries its course's
`timezone` (seeded `Asia/Kolkata`) and attendance records are bucketed by that
timezone in the summary. No server-local-time assumptions anywhere.

## ADR-008 — Recognition mode is environment-driven, seed is idempotent

**Decision.** `main.py` builds one runtime, applies the demo seed only if no
students exist (idempotent `seed_demo`), and serves the UI at `/`. Effective
recognition mode is exposed at `/attendance/health`. Tests construct apps via
`create_app(runtime)` with their own SQLite files — they never hit `main.py`
or a live network.

**Why.** One reproducible server entry, safe first-boot experience, and tests
that stay deterministic and offline.

## ADR-009 — Demo matching is deterministic, not "fake success"

**Decision.** Demo mode maps a SHA-256 digest of the image bytes to a student by
a stable index. The same image always produces the same student; different
images produce unstable matches by design. Every payload carries the simulation
flag so a demo trace can never be mistaken for identity.

**Why.** Demo must exercise the full pipeline (event, record, summary, export)
without pretending to be a real matcher.