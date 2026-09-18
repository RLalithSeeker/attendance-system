# Database requirements and invariants

Use repo's existing ORM/migrations if present; otherwise add minimal SQLAlchemy + Alembic if compatible. IDs use UUID or existing consistent IDs. Schema logical entities:
- users(id, email unique, password_hash or trusted auth_subject, role admin|teacher, active, created_at)
- students(id, student_code unique, full_name, active, created_at)
- courses(id, code unique, name, teacher_id FK, timezone)
- course_enrollments(id, course_id FK, student_id FK, active, UNIQUE(course_id,student_id))
- biometric_consents(id, student_id FK, consent_version, consented_at, revoked_at nullable, purpose, collected_by_id, evidence_ref optional); documented permission process for actual students.
- face_templates(id, student_id FK, template_ref/secure local path, model_version, enrolled_at, revoked_at, quality metadata). Never store embeddings as plaintext in cloud; locally protect access/at-rest where supported.
- class_sessions(id, course_id FK, starts_at UTC, ends_at UTC, status scheduled|active|closed, created_by FK)
- attendance_records(id, session_id FK, student_id FK, status present|late|absent|excused, method face|manual, first_seen_at UTC nullable, marked_by FK nullable, updated_at, UNIQUE(session_id,student_id))
- attendance_events(id, session_id FK, student_id nullable, recognition_status, action, request_id unique nullable, actor_id nullable, timestamp UTC, minimal reason, model_version optional); avoid unnecessary biometric scores over long retention.
- audit_logs(id, actor_id, action, object_type, object_id, reason nullable, timestamp UTC, safe before_after summary)

Rules: enforce FKs and unique constraints in DB, not just client. An event can mark present only for consented, active, enrolled student in an active session; teacher must own course (unless authorized admin). Late threshold configured per course/session; never auto-mark absent until explicit session close/teacher action. Repeated matching returns existing record without increment. Enroll/withdraw/revoke/delete must support removing matching templates and stop future recognition. Course deletion follows explicitly documented retention policy. Teacher correction requires reason and preserves history. No face image blobs in events or logs.

Migration from pre-existing schemas must be non-destructive; write rollback steps and local sample seed of FICTIONAL students without biometric data.
