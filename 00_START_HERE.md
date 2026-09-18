# CamBrain → Cloud Attendance: START HERE

## Objective
Turn the EXISTING CamBrain repository into a demonstrable cloud-based facial-recognition attendance system. User confirms face detection works. **Do not equate detection with identity recognition.** Reuse recognition only if validated; implement a clean adapter and a fallback demo/mock if unavailable, clearly labelled. Build student enrollment, class sessions, attendance, teacher UI, API, reports and deployable cloud data plane. Preserve original CamBrain capabilities.

## Source of truth
Repository: https://github.com/RLalithSeeker/nextgen2026-cambrain . Public README claims source under `cambrain/`, FastAPI, YOLO11, DeepFace/InsightFace, SQLite/Postgres, WebSocket dashboard; claims are NOT verified implementation. Always inspect actual local checkout and tests. This ZIP is a specification, not audited implementation or actual source fork.

## Run
1. Place/unzip this folder adjacent to your local `nextgen2026-cambrain` checkout, not on top of it.
2. In Claude Code, open the CamBrain checkout, give it the absolute path to this folder and paste `01_CLAUDE_ONE_SHOT_PROMPT.md`.
3. Follow `02_REPOSITORY_AUDIT.md` before edits and execute phases in `03_IMPLEMENTATION_PLAN.md`.
4. Read `04_ARCHITECTURE.md` through `12_ACCEPTANCE_AND_HANDOFF.md` as binding spec. Contracts under `contracts/` are proposed; adapt to repo consistently.
5. Keep all changes on a new git branch. No Docker requirement. No push, publishing, cloud spend, or personal biometric upload without explicit user authorization.

## Definition of mostly done
Real identity matching where supported; consent-based enrollment; unknown/ambiguous faces rejected; session-specific, duplicate-free marking; teacher review/edit with audit; functional dashboard and CSV; local end-to-end tests and a documented optional cloud DB configuration. A purely local build must NOT be described as deployed cloud-based.
