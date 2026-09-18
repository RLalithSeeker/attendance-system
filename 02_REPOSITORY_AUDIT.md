# Mandatory repository discovery before coding

Record evidence and actual paths in `docs/attendance/REPO_AUDIT.md`. Inspect: git status/remote/branch/license, `cambrain/` nesting, package manager, backend route registration and app entrypoint, recognition model imports/weights/license, face detection vs identity matching functions, enrollment/embedding index, storage and migrations, existing authentication, UI routes, websocket feed, camera abstraction, tests, configuration, CI. Locate privacy mode and ensure attendance storage is an explicit, consented exception without disabling zero-disk modes globally.

Run safe existing lint/unit tests and note exact command, output and environment. Inspect recognition capabilities: returns stable student identity? enrolled gallery? unknown rejection? thresholds? multi-face? GPU/CPU? If absent build adapter + documented production-unavailable error and mock-based integration tests; implement real integration if supported by installed dependencies/weights. Verify licenses and permissible reuse; no unauthorized license stripping. For third-party public repo or collaborators' work, retain provenance and comply with license.

Make a reuse map: existing symbol/path → attendance use → modification necessary → proof/test. No assertions based solely on README. Don't clone another whole attendance project or introduce unrelated tracking features.
