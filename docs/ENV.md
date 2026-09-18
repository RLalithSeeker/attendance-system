# Environment Variables

All optional. `.env` is gitignored; export in your shell or dotenv.

| Var | Default | Effect |
|---|---|---|
| `RECOGNITION_MODE` | `auto` | `auto` = real matcher if importable else `disabled`; `demo` = deterministic simulated matching (flagged in every payload); `real` = require real matcher, fail closed if absent; `disabled` = recognize always `503 matcher_unavailable` |
| `ATTENDANCE_DB_PATH` | `attendance.db` (repo local) | SQLite file for the attendance app |
| `ATTENDANCE_TOKEN_TTL_HOURS` | `12` | Bearer-token lifetime |
| `INSIGHT_CUDA` | `0` | Set `1` to run InsightFace on CUDA GPU instead of CPU |

Demo seed (no env needed; applied on first boot): `teacher@demo.local` /
`demo1234`, course `CS201`, students `S1001..S1003`, **no consent rows**.

For a full camera-free demo: `RECOGNITION_MODE=demo`. For real matching later:
install `insightface` + `onnxruntime` and set `RECOGNITION_MODE=real`.