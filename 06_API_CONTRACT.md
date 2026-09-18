# API contract (proposed; reconcile with existing prefix/auth)

All endpoints versioned consistently e.g. `/api/attendance/v1`; JSON except capture multipart and CSV export. Existing auth can replace proposed auth; require server authorization on each route, not merely hidden buttons. Standard errors `{error:{code,message,request_id}}`, 400 invalid, 401 unauthenticated, 403 forbidden, 404 not found/not owned, 409 duplicate/state conflict, 422 validation, 503 real matcher unavailable. OpenAPI generated and tests reflect actual implementation.

- GET `/health` or existing health; indicate identity adapter capability WITHOUT secrets.
- POST/GET `/students`; POST `/students/{id}/consent`, POST `/students/{id}/revoke-consent`; DELETE `/students/{id}/biometric-template` authorized deletion.
- POST `/students/{id}/enroll-face` multipart controlled image from consented capture, local-only inference; require consent, exactly one quality-approved face; respond template metadata only, not embedding.
- POST/GET `/courses`; POST/GET `/courses/{id}/students` roster management.
- POST `/courses/{id}/sessions`; POST `/sessions/{id}/start`; POST `/sessions/{id}/close`; GET `/sessions/{id}`.
- POST `/sessions/{id}/recognize` frame or server-side capture ref + optional idempotency key; only active session; identity matcher reports matched/unknown/ambiguous/unavailable; no leaking other students' identities. Require session access and rate limiting. Response e.g. `{result:"marked"|"already_marked"|"unknown"|"ambiguous"|"review_required", student_id?:...,attendance_id?:...,reason?:...}`. Never trust client-supplied `student_id` as proof of recognition.
- GET `/sessions/{id}/attendance`; PATCH `/sessions/{id}/attendance/{student_id}` teacher only `{status,reason}`; GET `/sessions/{id}/export.csv` authenticated and course-scoped; GET `/sessions/{id}/audit` authorized.

For first MVP keep single-frame inference as session-owner-controlled endpoint or local edge service. Use appropriate payload size/type validation and strip EXIF. CSRF protection if cookie auth; secure token handling if bearer auth; no public registration or exposed debug routes. Rate-limit image ingestion and do not cache raw images. Document exact shapes in generated OpenAPI and update client/types in lockstep.
