"""Business layer for attendance.

Owns the *only* place attendance facts are written. Kept deliberately free of
FastAPI imports so it is unit-testable in isolation.

Audit discipline: every state-changing call appends to audit_logs with a
reason. ``request_id`` is threaded through attendance_events for idempotency.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from .auth import TeacherAuth
from .database import AttendanceDB, iso_utc, utcnow, _uuid
from .errors import (
    ConflictError, ForbiddenError, NotFoundError, ValidationError,
    MatcherUnavailableError,
)
from .recognition_adapter import RecognitionAdapter

IMG_EXTENSIONS = (".jpg", ".jpeg", ".png")
FALLBACK_TZ = "Asia/Kolkata"


class AttendanceService:
    def __init__(self, db: AttendanceDB, auth: TeacherAuth, adapter: RecognitionAdapter):
        self.db = db
        self.auth = auth
        self.adapter = adapter
        self.template_dir = os.environ.get(
            "FACE_TEMPLATE_DIR", os.path.join("attendance_data", "templates"))

    # ── audit helper ─────────────────────────────────────────────────────────
    def _audit(self, conn, actor_id: Optional[str], action: str, object_type: str,
               object_id: Optional[str], reason: Optional[str],
               before: Optional[str] = None, after: Optional[str] = None) -> None:
        self.db.tx_execute(conn, 
            "INSERT INTO audit_logs (id, actor_id, action, object_type, object_id, reason, before_s, after_s, timestamp)"
            " VALUES (:id, :actor, :action, :otype, :oid, :reason, :before, :after, :ts)",
            {"id": _uuid(), "actor": actor_id, "action": action, "otype": object_type,
             "oid": object_id, "reason": reason, "before": before, "after": after,
             "ts": iso_utc()},
        )

    def _active_student(self, conn, student_id: str) -> dict:
        row = self.db.tx_execute(conn, 
            "SELECT * FROM students WHERE id = :id AND active = 1",
            {"id": student_id}).fetchone()
        if not row:
            raise NotFoundError("Student not found or inactive.")
        return dict(row)

    def _active_course(self, conn, course_id: str) -> dict:
        row = self.db.tx_execute(conn, 
            "SELECT * FROM courses WHERE id = :id", {"id": course_id}).fetchone()
        if not row:
            raise NotFoundError("Course not found.")
        return dict(row)

    # ── students / courses / enrollments ─────────────────────────────────────
    def create_student(self, code: str, full_name: str, actor_id: Optional[str]) -> dict:
        code = code.strip().upper()
        with self.db.transaction() as conn:
            if self.db.tx_execute(conn, "SELECT 1 FROM students WHERE student_code = :c",
                            {"c": code}).fetchone():
                raise ConflictError("Student code already exists.")
            sid = _uuid()
            self.db.tx_execute(conn, 
                "INSERT INTO students (id, student_code, full_name, active, created_at)"
                " VALUES (:id, :code, :name, 1, :ts)",
                {"id": sid, "code": code, "name": full_name.strip(),
                 "ts": iso_utc()})
            self._audit(conn, actor_id, "student.create", "student", sid,
                        reason="new student added")
            return {"id": sid, "student_code": code, "full_name": full_name.strip(),
                    "active": True}

    def list_students(self) -> List[dict]:
        return self.db.query(
            "SELECT id, student_code, full_name, active FROM students ORDER BY student_code")

    def create_course(self, code: str, name: str, teacher_id: Optional[str],
                      timezone: str, late_after_minutes: Optional[int],
                      actor_id: Optional[str]) -> dict:
        code = code.strip().upper()
        with self.db.transaction() as conn:
            if self.db.tx_execute(conn, "SELECT 1 FROM courses WHERE code = :c",
                            {"c": code}).fetchone():
                raise ConflictError("Course code already exists.")
            if teacher_id:
                t = self.db.tx_execute(conn, 
                    "SELECT id FROM users WHERE id = :id AND active = 1",
                    {"id": teacher_id}).fetchone()
                if not t:
                    raise NotFoundError("Teacher not found.")
            cid = _uuid()
            self.db.tx_execute(conn, 
                "INSERT INTO courses (id, code, name, teacher_id, timezone, late_after_minutes, created_at)"
                " VALUES (:id, :code, :name, :tid, :tz, :late, :ts)",
                {"id": cid, "code": code, "name": name.strip(), "tid": teacher_id,
                 "tz": timezone or FALLBACK_TZ, "late": late_after_minutes,
                 "ts": iso_utc()})
            self._audit(conn, actor_id, "course.create", "course", cid,
                        reason="new course")
            return {"id": cid, "code": code, "name": name.strip(),
                    "teacher_id": teacher_id, "timezone": timezone,
                    "late_after_minutes": late_after_minutes}

    def enroll_students(self, course_id: str, student_ids: List[str],
                        actor_id: Optional[str]) -> dict:
        with self.db.transaction() as conn:
            self._active_course(conn, course_id)
            added = 0
            for sid in dict.fromkeys(student_ids):
                st = self.db.tx_execute(conn, 
                    "SELECT id FROM students WHERE id = :id AND active = 1",
                    {"id": sid}).fetchone()
                if not st:
                    continue
                existing = self.db.tx_execute(conn, 
                    "SELECT 1 FROM course_enrollments WHERE course_id = :c AND student_id = :s",
                    {"c": course_id, "s": sid}).fetchone()
                if existing:
                    continue
                self.db.tx_execute(conn, 
                    "INSERT INTO course_enrollments (id, course_id, student_id, active, created_at)"
                    " VALUES (:id, :c, :s, 1, :ts)",
                    {"id": _uuid(), "c": course_id, "s": sid, "ts": iso_utc()})
                added += 1
            self._audit(conn, actor_id, "course.enroll", "course", course_id,
                        reason=f"enrolled {added} student(s)")
            return {"course_id": course_id, "added": added}

    def course_summary(self, course_id: str) -> dict:
        course = self.db.query_one("SELECT * FROM courses WHERE id = :id",
                                   {"id": course_id})
        if not course:
            raise NotFoundError("Course not found.")
        students = self.db.query(
            "SELECT s.* FROM students s JOIN course_enrollments ce ON ce.student_id = s.id"
            " WHERE ce.course_id = :c AND ce.active = 1 ORDER BY s.student_code",
            {"c": course_id})
        return {"course": course, "students": students}

    # ── consent + face templates (enrollment) ────────────────────────────────
    def record_consent(self, student_id: str, consent_version: str, purpose: str,
                       evidence_ref: Optional[str], actor_id: Optional[str]) -> dict:
        with self.db.transaction() as conn:
            self._active_student(conn, student_id)
            now = iso_utc()
            # revoke any outstanding previous consent
            self.db.tx_execute(conn, 
                "UPDATE biometric_consents SET revoked_at = :ts"
                " WHERE student_id = :s AND revoked_at IS NULL",
                {"ts": now, "s": student_id})
            cid = _uuid()
            self.db.tx_execute(conn, 
                "INSERT INTO biometric_consents"
                " (id, student_id, consent_version, purpose, consented_at, collected_by_id, evidence_ref)"
                " VALUES (:id, :s, :v, :p, :ts, :by, :ev)",
                {"id": cid, "s": student_id, "v": consent_version, "p": purpose,
                 "ts": now, "by": actor_id, "ev": evidence_ref})
            self._audit(conn, actor_id, "consent.record", "student", student_id,
                        reason=f"biometric consent v{consent_version} ({purpose})")
            return {"student_id": student_id, "consent_version": consent_version,
                    "consented_at": now, "revoked_at": None, "active": True}

    def revoke_consent(self, student_id: str, actor_id: Optional[str]) -> dict:
        with self.db.transaction() as conn:
            self._active_student(conn, student_id)
            now = iso_utc()
            self.db.tx_execute(conn, 
                "UPDATE biometric_consents SET revoked_at = :ts"
                " WHERE student_id = :s AND revoked_at IS NULL",
                {"ts": now, "s": student_id})
            # also drop any live templates
            self._delete_template_rows(conn, student_id)
            self.db.tx_execute(conn, 
                "DELETE FROM face_templates WHERE student_id = :s", {"s": student_id})
            self._audit(conn, actor_id, "consent.revoke", "student", student_id,
                        reason="consent revoked; templates deleted")
            return {"student_id": student_id, "revoked_at": now, "active": False}

    def _delete_template_rows(self, conn, student_id: str) -> None:
        rows = self.db.tx_execute(conn, 
            "SELECT template_ref FROM face_templates WHERE student_id = :s",
            {"s": student_id}).fetchall()
        for r in rows:
            ref = r[0]
            if ref and ref.startswith(self.template_dir):
                try:
                    os.remove(ref)
                except OSError:
                    pass
        # remove empty student dir
        d = os.path.join(self.template_dir, student_id)
        try:
            os.rmdir(d)
        except OSError:
            pass

    def enroll_face(self, student_id: str, image_bytes: bytes,
                    actor_id: Optional[str]) -> dict:
        """Store one face image for a consenting student.

        Real mode computes + persists the embedding into the recognizer gallery
        (so the NEXT frame can match). Demo mode stores the file (deterministic
        hash-matching later). Disabled mode 503s — enrolment is biometric work.
        """
        with self.db.transaction() as conn:
            self._active_student(conn, student_id)
            st = self.db.tx_execute(conn, 
                "SELECT 1 FROM biometric_consents WHERE student_id = :s AND revoked_at IS NULL"
                " ORDER BY consented_at DESC LIMIT 1",
                {"s": student_id}).fetchone()
            if not st:
                raise ForbiddenError("No active biometric consent for this student.")

            if len(image_bytes) > 1_500_000:
                raise ValidationError("Image too large (max 1.5MB).")
            import cv2
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                raise ValidationError("Could not decode image (send base64 JPEG/PNG).")
            if frame.shape[0] < 80 or frame.shape[1] < 80:
                raise ValidationError("Image too small (min 80x80).")

            mode = self.adapter.effective_mode()
            if mode == "disabled":
                raise MatcherUnavailableError(
                    "Face enrolment unavailable (matcher disabled). Enable RECOGNITION_MODE.")

            os.makedirs(os.path.join(self.template_dir, student_id), exist_ok=True)
            path = os.path.join(self.template_dir, student_id,
                                f"img-{_uuid()[:8]}-{self.adapter.model_version if mode == 'real' else 'demo'}.jpg")
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if not ok:
                raise ValidationError("Failed to encode image.")
            with open(path, "wb") as f:
                f.write(buf.tobytes())

            tid = _uuid()
            self.db.tx_execute(conn, 
                "INSERT INTO face_templates (id, student_id, template_ref, model_version, quality_meta, enrolled_at)"
                " VALUES (:id, :s, :ref, :mv, :qm, :ts)",
                {"id": tid, "s": student_id, "ref": path,
                 "mv": self.adapter.model_version if mode == "real" else "demo-model",
                 "qm": "{0}x{1}".format(frame.shape[1], frame.shape[0]),
                 "ts": iso_utc()})
            self._audit(conn, actor_id, "face.enroll", "student", student_id,
                        reason=f"new face template stored ({mode})")

        # rebuild the live gallery so the provider sees the new face now
        if mode == "real":
            self.adapter.reload_gallery()
        return {"template_id": tid, "student_id": student_id,
                "model_version": self.adapter.model_version if mode == "real" else "demo-model",
                "enrolled_at": iso_utc()}

    def list_templates(self, student_id: str) -> List[dict]:
        return self.db.query(
            "SELECT id, student_id, model_version, enrolled_at, revoked_at"
            " FROM face_templates WHERE student_id = :s ORDER BY enrolled_at DESC",
            {"s": student_id})

    # ── sessions ─────────────────────────────────────────────────────────────
    def start_session(self, course_id: str, starts_at: Optional[str],
                      actor_id: Optional[str]) -> dict:
        with self.db.transaction() as conn:
            course = self._active_course(conn, course_id)
            active = self.db.tx_execute(conn, 
                "SELECT id FROM class_sessions WHERE course_id = :c AND status = 'active'",
                {"c": course_id}).fetchone()
            if active:
                raise ConflictError("Course already has an active session.")
            sid = _uuid()
            self.db.tx_execute(conn, 
                "INSERT INTO class_sessions (id, course_id, starts_at, status, created_by, created_at)"
                " VALUES (:id, :c, :ts, 'active', :by, :ts)",
                {"id": sid, "c": course_id, "ts": starts_at or iso_utc(),
                 "by": actor_id})
            self._audit(conn, actor_id, "session.start", "session", sid,
                        reason=f"started session for {course['code']}")
            return {"id": sid, "course_id": course_id, "starts_at": starts_at or iso_utc(),
                    "status": "active"}

    def close_session(self, session_id: str, actor_id: Optional[str]) -> dict:
        with self.db.transaction() as conn:
            s = self.db.tx_execute(conn, "SELECT * FROM class_sessions WHERE id = :id",
                             {"id": session_id}).fetchone()
            if not s:
                raise NotFoundError("Session not found.")
            self.db.tx_execute(conn, 
                "UPDATE class_sessions SET status = 'closed', ends_at = :ts WHERE id = :id",
                {"ts": iso_utc(), "id": session_id})
            self._audit(conn, actor_id, "session.close", "session", session_id,
                        reason="session closed")
            return {"id": session_id, "status": "closed"}

    def list_sessions(self) -> List[dict]:
        rows = self.db.query(
            "SELECT cs.id, cs.course_id, cs.starts_at, cs.status,"
            " c.code AS course_code,"
            " COUNT(ce.student_id) AS student_count,"
            " (SELECT COUNT(*) FROM attendance_records ar"
            "   WHERE ar.session_id = cs.id AND ar.status IN ('present','late'))"
            "   AS present_count"
            " FROM class_sessions cs"
            " JOIN courses c ON c.id = cs.course_id"
            " LEFT JOIN course_enrollments ce ON ce.course_id = c.id AND ce.active = 1"
            " GROUP BY cs.id ORDER BY cs.starts_at DESC")
        return [dict(r) for r in rows]

    def session_detail(self, session_id: str) -> dict:
        s = self.db.query_one(
            "SELECT cs.*, c.code AS course_code, c.name AS course_name,"
            " c.teacher_id AS course_teacher FROM class_sessions cs"
            " JOIN courses c ON c.id = cs.course_id WHERE cs.id = :id",
            {"id": session_id})
        if not s:
            raise NotFoundError("Session not found.")
        records = self.db.query(
            "SELECT ar.status, ar.method, ar.first_seen_at, ar.updated_at, ar.marked_by,"
            " s.student_code, s.full_name, s.id AS student_id"
            " FROM attendance_records ar JOIN students s ON s.id = ar.student_id"
            " WHERE ar.session_id = :s ORDER BY s.student_code",
            {"s": session_id})
        return {"session": s, "records": records}

    # ── attendance core ──────────────────────────────────────────────────────
    def _fallback_late_minutes(self, conn, session_id: str) -> int:
        row = self.db.tx_execute(conn, 
            "SELECT c.late_after_minutes FROM class_sessions cs"
            " JOIN courses c ON c.id = cs.course_id WHERE cs.id = :id",
            {"id": session_id}).fetchone()
        if row and row[0] is not None:
            return int(row[0])
        return int(os.environ.get("LATE_AFTER_MINUTES", "10"))

    def _enrolled_ids(self, conn, session_id: str) -> set:
        rows = self.db.tx_execute(conn, 
            "SELECT s.id FROM students s"
            " JOIN course_enrollments ce ON ce.student_id = s.id"
            " JOIN class_sessions cs ON cs.course_id = ce.course_id"
            " WHERE cs.id = :id AND ce.active = 1 AND s.active = 1",
            {"id": session_id}).fetchall()
        return {r[0] for r in rows}

    def recognize_event(self, session_id: str, image_bytes: bytes,
                        request_id: Optional[str], actor_id: Optional[str]) -> dict:
        """Recognize + record in ONE transaction. Never fabricates attendance.

        Decision rules (fail-closed):
        - unavailable / no_face / low_quality / multi_face  -> no record, event
          with ``action="reject"``.
        - unknown -> no record; ``action="unknown"``.
        - ambiguous -> no record (human must pick); ``action="ambiguous"``.
        - matched -> ONLY then mark present/late (or already_recorded).
        """
        mode = self.adapter.effective_mode()
        if mode == "disabled":
            raise MatcherUnavailableError("Recognition disabled. Enable RECOGNITION_MODE.")
        result = self.adapter.recognize(image_bytes)

        with self.db.transaction() as conn:
            s = self.db.tx_execute(conn, "SELECT * FROM class_sessions WHERE id = :id",
                             {"id": session_id}).fetchone()
            if not s:
                raise NotFoundError("Session not found.")
            enrolled = self._enrolled_ids(conn, session_id)

            status = result.status
            student_id = None
            outcome = "no_action"
            event_id = None
            if status == "matched" and result.student_id:
                student_id = result.student_id
                if student_id not in enrolled:
                    outcome = "unknown"
                    self._audit(conn, actor_id, "attendance.reject", "session",
                                session_id, reason="recognized but not enrolled")
                else:
                    existing = self.db.tx_execute(conn, 
                        "SELECT status FROM attendance_records"
                        " WHERE session_id = :sid AND student_id = :stu",
                        {"sid": session_id, "stu": student_id}).fetchone()
                    if existing:
                        outcome = "already_recorded"
                    else:
                        late_min = self._fallback_late_minutes(conn, session_id)
                        outcome = self._mark_present(conn, session_id, student_id,
                                                     late_min, s["starts_at"])
            event_id = self._log_event(conn, session_id, student_id, status, outcome,
                                       request_id, actor_id, reason=result.reason,
                                       model_version=result.model_version)

        return {
            "event_id": event_id,
            "session_id": session_id,
            "result": result,
            "status_outcome": self._outcome_from_result(outcome, status,
                                                        result.student_id),
        }

    def _mark_present(self, conn, session_id: str, student_id: str,
                      late_min: int, starts_at: Optional[str]) -> str:
        """Insert an attendance record. Returns the outcome string."""
        import datetime as _dt
        late = False
        if starts_at:
            try:
                t0 = _dt.datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                if t0.tzinfo is None:
                    t0 = t0.replace(tzinfo=_dt.timezone.utc)
                late = (utcnow() - t0).total_seconds() > (late_min * 60)
            except ValueError:
                late = False
        else:
            late = False
        status = "late" if late else "present"
        self.db.tx_execute(conn, 
            "INSERT INTO attendance_records (id, session_id, student_id, status, method, first_seen_at, marked_by, updated_at)"
            " VALUES (:id, :sid, :stu, :st, 'face', :ts, NULL, :ts)",
            {"id": _uuid(), "sid": session_id, "stu": student_id,
             "st": status, "ts": iso_utc()})
        self._audit(conn, None, "attendance.auto", "attendance", session_id,
                    reason=f"{status} via face match")
        return status

    def _log_event(self, conn, session_id: str, student_id: Optional[str],
                   recognition_status: str, action: str, request_id: Optional[str],
                   actor_id: Optional[str], reason: Optional[str],
                   model_version: Optional[str]) -> str:
        event_id = _uuid()
        self.db.tx_execute(conn, 
            "INSERT INTO attendance_events"
            " (id, session_id, student_id, recognition_status, action, request_id, actor_id, timestamp, reason, model_version)"
            " VALUES (:id, :sid, :stu, :rs, :act, :req, :actor, :ts, :reason, :mv)",
            {"id": event_id, "sid": session_id, "stu": student_id,
             "rs": recognition_status, "act": action, "req": request_id,
             "actor": actor_id, "ts": iso_utc(), "reason": reason, "mv": model_version})
        return event_id

    def _outcome_from_result(self, outcome: str, status: str,
                             student_id: Optional[str]) -> str:
        if outcome in ("present", "late", "already_recorded"):
            return outcome
        if status == "matched" and student_id:
            return "unknown"
        if status == "ambiguous":
            return "ambiguous"
        if status == "unknown":
            return "unknown"
        if status == "no_face":
            return "no_face"
        if status in ("multi_face", "low_quality"):
            return "no_action"
        return "unavailable"

    # ── manual marking ───────────────────────────────────────────────────────
    def manual_mark(self, session_id: str, student_id: str, status: str,
                    reason: Optional[str], actor_id: Optional[str]) -> dict:
        with self.db.transaction() as conn:
            s = self.db.tx_execute(conn, "SELECT id FROM class_sessions WHERE id = :id",
                             {"id": session_id}).fetchone()
            if not s:
                raise NotFoundError("Session not found.")
            self._active_student(conn, student_id)
            existing = self.db.tx_execute(conn, 
                "SELECT id, status FROM attendance_records"
                " WHERE session_id = :sid AND student_id = :stu",
                {"sid": session_id, "stu": student_id}).fetchone()
            if existing:
                self.db.tx_execute(conn, 
                    "UPDATE attendance_records SET status = :st, method = 'manual',"
                    " marked_by = :mb, updated_at = :ts WHERE id = :rid",
                    {"st": status, "mb": actor_id, "ts": iso_utc(), "rid": existing[0]})
                self._audit(conn, actor_id, "attendance.manual_update", "attendance",
                            session_id, reason=reason or f"override to {status}")
                return {"student_id": student_id, "status": status, "overridden": True}
            self.db.tx_execute(conn, 
                "INSERT INTO attendance_records (id, session_id, student_id, status, method, first_seen_at, marked_by, updated_at)"
                " VALUES (:id, :sid, :stu, :st, 'manual', :ts, :mb, :ts)",
                {"id": _uuid(), "sid": session_id, "stu": student_id,
                 "st": status, "ts": iso_utc(), "mb": actor_id})
            self._audit(conn, actor_id, "attendance.manual", "attendance",
                        session_id, reason=reason or f"marked {status} manually")
            return {"student_id": student_id, "status": status, "overridden": False}

    def attendance_summary(self, session_id: str) -> dict:
        s = self.db.query_one("SELECT * FROM class_sessions WHERE id = :id",
                              {"id": session_id})
        if not s:
            raise NotFoundError("Session not found.")
        enrolled = self.db.query(
            "SELECT s.id FROM students s"
            " JOIN course_enrollments ce ON ce.student_id = s.id"
            " JOIN class_sessions cs ON cs.course_id = ce.course_id"
            " WHERE cs.id = :id AND ce.active = 1 AND s.active = 1",
            {"id": session_id})
        total = len(enrolled)
        rows = self.db.query(
            "SELECT status, COUNT(*) AS c FROM attendance_records"
            " WHERE session_id = :s GROUP BY status",
            {"s": session_id})
        counts = {r["status"]: r["c"] for r in rows}
        accounted = sum(counts.get(k, 0) for k in ("present", "late", "absent", "excused"))
        return {
            "session_id": session_id,
            "course_id": s["course_id"],
            "status": s["status"],
            "total_enrolled": total,
            "present": counts.get("present", 0),
            "late": counts.get("late", 0),
            "absent": counts.get("absent", 0),
            "excused": counts.get("excused", 0),
            "unaccounted": max(0, total - accounted),
        }

    # ── CSV export (hardened) ────────────────────────────────────────────────
    def export_csv(self, session_id: str) -> Tuple[str, str]:
        s = self.db.query_one("SELECT * FROM class_sessions WHERE id = :id",
                              {"id": session_id})
        if not s:
            raise NotFoundError("Session not found.")
        rows = self.db.query(
            "SELECT s.student_code AS code, s.full_name AS name, ar.status,"
            " ar.method, ar.first_seen_at, ar.updated_at"
            " FROM students s"
            " LEFT JOIN attendance_records ar ON ar.session_id = :sid AND ar.student_id = s.id"
            " JOIN course_enrollments ce ON ce.student_id = s.id"
            " JOIN class_sessions cs ON cs.course_id = ce.course_id"
            " WHERE cs.id = :sid"
            " ORDER BY s.student_code",
            {"sid": session_id})
        lines = ["student_code,full_name,status,method,first_seen_at,updated_at"]
        for r in rows:
            lines.append(",".join(self._csv_escape(v) for v in (
                r["code"], r["name"], r["status"] or "",
                r["method"] or "", r["first_seen_at"] or "", r["updated_at"] or "")))
        return "\n".join(lines) + "\n", f"attendance-{session_id[:8]}.csv"

    @staticmethod
    def _csv_escape(value: str) -> str:
        v = str(value)
        if any(ch in v for ch in (",", '"', "\n", "\r", "=", "+", "-", "@", "\t")):
            if v.startswith(("=", "+", "-", "@", "\t")):
                v = "'" + v
            return '"' + v.replace('"', '""') + '"'
        return v