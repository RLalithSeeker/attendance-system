# Attendance System

Standalone, privacy-first facial-recognition class attendance — a separate
project, deliberately decoupled from any surveillance engine.

**No camera, no matcher hardware needed for the shipped modes.** The API, the
teacher UI and the full pipeline run in `demo` (deterministic simulation,
flagged in every payload) and `disabled` (recognition off, manual marks only)
out of the box. Real InsightFace matching is a pluggable, lazy provider you can
turn on later.

## Quick start (no camera)

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py                 # http://localhost:8000
```

- UI: http://localhost:8000 — login `teacher@demo.local` / `demo1234`
- Health: http://localhost:8000/attendance/health → shows `"mode":"demo"` (or
  `disabled` if `RECOGNITION_MODE` unset and insightface absent)

Demo seed is applied idempotently on first boot: course `CS201`, students
`S1001..S1003`, **no biometric consent rows** (nothing is ever silently
enrolled).

## Recognition modes (`RECOGNITION_MODE`)

| Mode | Behaviour | Needs camera/matcher? |
|---|---|---|
| `auto` (default) | real if insightface importable, else `disabled` | no |
| `demo` | deterministic hash-match, `DEMO / SIMULATED RECOGNITION` flag | no |
| `real` | InsightFace buffalo_l vs enrolled templates; fails closed if unavailable | yes |
| `disabled` | recognize always `503 matcher_unavailable`; manual works | no |

Fail-closed: only a `matched` recognition for an enrolled + consented student
writes an attendance record. `unknown` / `ambiguous` / `no_face` / `multi_face`
/ `low_quality` / `unavailable` are logged as events, never as attendance.

## Real matching (your camera step — later)

```powershell
pip install insightface onnxruntime
$env:RECOGNITION_MODE="real"
python main.py                  # health now reports "mode":"real"
```

The matcher is a provider implementing the contract in
`attendance/matcher_providers.py`. `InsightFaceProvider` is the reference
provider: it embeds the app's OWN enrolled templates on disk (DB stores only
file paths, never blobs), CPU by default (`INSIGHT_CUDA=1` for GPU). Swap in a
custom provider by passing one to `build_runtime(db, provider=...)`.

## Test

```powershell
python -m pytest tests -q      # 18 tests; 100% camera-free (demo + disabled)
```

## API (`/api/attendance/v1`)

Bearer-token auth (`POST /auth/login`, SHA-256-hashed tokens at rest, 12h TTL).
Envelope: `{"ok":true,"data":...}` / `{"ok":false,"error":{...}}`. Courses,
students, consents, templates (≥80×80, ≤1.5MB, consent required), sessions,
`/recognize` (request_id idempotent replay, 6/min/token rate limit), manual
marks, summary, `export.csv` (formula-injection-escaped).

## Docs
- `docs/ADR.md` — architecture decisions
- `docs/ENV.md` — environment variables
- `docs/TEST_RESULTS.md` — test matrix and scope
- `docs/HANDOFF.md` — where the project stands
- `docs/REPO_AUDIT.md` — security/data-model audit