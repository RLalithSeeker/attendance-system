# Functional UI specification

Integrate with repo's actual frontend; avoid duplicate design system. Responsive, calm, minimal dashboard. Pages/components:
1. Teacher sign-in (or existing auth) and authorized dashboard: today’s courses, active session, session count, no biometric thumbnails by default.
2. Student roster: add/edit/import small CSV with validation, roster-to-course mapping, show consent/enrollment states; no public searchable directory.
3. Consent/enroll: clearly state purpose, retention/deletion/contact, explicit authorization recorded; camera permission prompt only on action, capture locally, face quality feedback, never silently upload. Revoke/delete buttons.
4. Session management: create/start/close, live webcam preview, camera source selection if existing capability; visual status `ready`, `matching`, `marked`, `already marked`, `unknown`, `ambiguous`, `needs review`, `matcher unavailable`. Show student's name only to authorized teacher after matched identity. Manual check-in with reason.
5. Attendance table: present/late/absent/excused, filter/search, timestamps, override dialog with mandatory reason, audit indicator.
6. Report: per-session summary and authorized CSV download. Show local-vs-cloud connection state honestly; no fictional live analytics.
7. Settings/help: model readiness, configured thresholds with calibration warning, course timezone, privacy settings and troubleshooting.

Avoid endless auto-posting of frames: bounded sampling, explicit start/stop and visible camera state; pause on tab hidden if possible, terminate media tracks on unmount. Show empty/loading/error states and accessible labels. Mock mode must have persistent `DEMO / SIMULATED RECOGNITION` banner. Unknown faces never appear as student identities. If identity matcher unavailable, keep roster/manual-attendance mode usable.
