# REPO_AUDIT — provenance for the standalone attendance design (recorded 2026-09-18)

This doc records the source CamBrain checkout this feature was originally
benchmarked against. It is PROVENANCE ONLY — the standalone project here has no
CamBrain code paths; nothing below is a claim about this repo's runtime.

Original evidence from the local checkout at `C:\Users\starl\Downloads\CamBrain`
(branch `feat/attendance-system` at commit `fc7f626`). No claim relies on the
public README alone.

## Git state (start of session)
- Branch: `main`, clean of *my* changes; **user WIP present + preserved**:
  modified `BUSINESS.md`, `CLAUDE.md`, `cambrain/face_recognizer.py`
  (only change: `SIMILARITY_THRESHOLD` 0.50 → 0.45 + comment — identity matcher
  threshold tuning by user), untracked `PLAN.html`, `VISION_AI_RESEARCH.md`,
  `VISION_UPGRADE_HANDOFF.md`, `cambrain/clip_reid_embedder.py`,
  `cambrain/fall_transformer_infer.py`, `eval/`.
- Action: created `feat/attendance-system` branch with the dirty tree carried
  over (no stash/overwrite). WIP files listed in `.git/info/exclude` so they are
  never swept into an attendance commit. Commits on the new branch are targeted
  (`git add <specific paths>` only — never `add -A`, per project CLAB).
- Remote: `origin https://github.com/RLalithSeeker/cambrain.git`.

## Layout / packaging
- App library = `cambrain/` package (28 modules). Entrypoint `main.py` (FastAPI,
  root), dashboard `templates/index.html` (+ sandbox), marketing site `web/`
  (Next.js 16, separate, Vercel).
- No ORM in the app path. Persistence = `cambrain/database_manager.py` using raw
  `sqlite3` (SQLite dev) with a hand-written PostgreSQL branch via `psycopg2`
  when `DATABASE_URL` is set (dual-dialect SQL with `?` vs `%s`). Thread-safe
  write queue, background purge (DPDP retention).
- `pyproject.toml`: FastAPI ≥0.136, pydantic ≥2, `uvicorn[standard]`, psycopg2,
  python-multipart, numpy 2, opencv 4.13. pytest testpaths = `tests/` (CI runs
  weight-free suite). Ruff/mypy configured.
- `.gitignore`: `*.db`, `my_faces/`, `*.jpg/png`, `screenshots/`, `.env.*`,
  `cb_env/` all ignored.

## Auth (existing)
- Global API-key gate: when `CAMBRAIN_API_KEY` is set, every `/api` + `/ws` path
  needs `X-API-Key` or `?token=` (constant-time compare). `_AUTH_OPEN_PATHS` =
  dashboard shells, `/docs`, `/health*`, `/version`, `/sandbox`.
- **There is NO user login / role system anywhere.** Attendance therefore adds
  its own teacher auth (salted password hashing + bearer sessions) as a bounded
  module; the global API key still applies on top where set (belt + suspenders).
- CORS locked to `CAMBRAIN_ALLOWED_ORIGINS` (defaults localhost + vercel).

## Recognition (the identity matcher to wrap)
- `cambrain/face_recognizer.py`: `FaceRecognizer` singleton via
  `get_face_recognizer()`. InsightFace `buffalo_l` (`FaceAnalysis`,
  det_size 640×640) if importable; falls back to `deepface.VGG-Face` `find()`.
  Gallery = folder-of-photos under `my_faces/<name>/*.jpg`, embeddings
  normalised L2; `recognize(crop)` does nearest-cosine; returns
  `KNOWN: <name>` or `UNKNOWN`. `reload_embeddings()` rescans for new people.
  Threshold: `SIMILARITY_THRESHOLD = 0.45` (user-lowered from 0.50).
- **Verified live in this environment: `insightface` and `mediapipe` are NOT
  importable** — system Python 3.13.5 · cv2 4.13.0 · numpy 2.1.1 · fastapi
  0.115.6 · pydantic 2.10.5 · pytest 8.3.4 · httpx 0.27.2. The `cb_env` venv that
  held torch/insightface is **absent from disk** (cleaned). Consequences:
  - Real recognition E2E = **BLOCKED on this box** (no weights, no insightface).
  - The adapter is built for the REAL InsightFace path but fails closed
    (`available()==False`) here; app stays fully usable in roster/manual mode.
  - Optional vendor demo adapter exists only for `RECOGNITION_MODE=demo`.
- Face detection ≠ recognition: the app's `ai_engine` YOLO/ByteTrack person
  tracks and HSV/OSNet Re-ID are person-appearance tracking, **not** identity.
  They are NOT used to decide attendance identity.

## Storage to touch
- `cambrain_events.db` (SQLite) holds forensic alerts, separate concern.
- Attendance gets its OWN bounded DB: SQLite by default
  (`attendance_data/attendance.db`), Postgres-capable via the same dual-dialect
  pattern P1-adapter, at `ATTENDANCE_DB_DSN`. NOT routed into `cambrain_events.db`;
  does not override `DATABASE_URL`/root env.

## Frontend to integrate with
- Server-rendered `templates/*.html` + vanilla JS fetch/WebSocket; `_inject_key`
  shim auto-attaches the API key. No build step. Attendance UI = new
  `templates/attendance.html` served at `/attendance`, reusing this pattern and
  existing tokens (cream/ink/flame). No new JS framework.

## Baseline tests
- `python -m pytest tests -q` → **4 passed** (0.09 s), weight-free hygiene suite,
  no failures to separate.
- System python has a broken pre-existing combo for the HEAVY engine (`import
  main` needs cb_env torch stack; attendance router avoids importing the engine,
  so it is testable standalone — verify only via the attendance ASGI app built
  from the same router, not a second deployed server).

## License / provenance
- Repo `LICENSE` = proprietary (CamBrain). InsightFace buffalo_l is a pretrained
  detector/recogniser loaded by import; weights download from the InsightFace
  registry on first use (subject to its own licence). No new models downloaded,
  nothing retrained, nothing stripped.