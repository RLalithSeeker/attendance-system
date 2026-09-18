"""HTTP layer for attendance — FastAPI router mounted under /api/attendance/v1.

Auth: `Authorization: Bearer <token>` (issuer: POST /auth/login) for everything
state-changing. The envelope stays Flat:
  HTTP 200 → {"ok": true, "data": ...}
  HTTP non-2xx → {"ok": false, "error": {"code", "message", "request_id"}}
"""

from __future__ import annotations

import base64
import binascii
import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import JSONResponse

from . import schemas
from .database import AttendanceDB
from .errors import AttendanceError, ValidationError
from .recognition_adapter import RecognitionAdapter
from .auth import TeacherAuth
from .service import AttendanceService

MAX_IMAGE_BYTES = 1_500_000


def _b64decode(image_b64: str) -> bytes:
    body = image_b64.split(",", 1)[-1]
    body = re.sub(r"\s+", "", body)
    try:
        raw = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise ValidationError("Image must be valid base64.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValidationError("Image too large (max 1.5MB).")
    return raw


class _RateLimit:
    """Crude per-token sliding window (default 6 recognize-calls/min)."""

    def __init__(self, rate: int = 6, window: float = 60.0):
        self.rate = rate
        self.window = window
        self.hits: dict[str, list[float]] = {}
        self.stamp = time.monotonic

    def allow(self, key: str) -> bool:
        now = self.stamp()
        bucket = [t for t in self.hits.get(key, []) if now - t < self.window]
        self.hits[key] = bucket
        if len(bucket) >= self.rate:
            return False
        bucket.append(now)
        self.hits[key] = bucket
        return True


class _RouterState:
    def __init__(self, db: AttendanceDB, auth: TeacherAuth, adapter: RecognitionAdapter,
                 service: AttendanceService):
        self.db = db
        self.auth = auth
        self.adapter = adapter
        self.service = service
        self.rate = _RateLimit()


def build_router(db: AttendanceDB, auth: TeacherAuth, adapter: RecognitionAdapter,
                 service: AttendanceService) -> APIRouter:
    state = _RouterState(db, auth, adapter, service)
    router = APIRouter(prefix="/api/attendance/v1")

    def _teacher(authorization: Optional[str] = Header(default=None)) -> dict:
        token = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        user = state.auth.validate_token(token) if token else None
        return state.auth.require_role(user, ("teacher", "admin"))

    def errp(e: AttendanceError) -> JSONResponse:
        e.request_id = str(uuid.uuid4())
        return JSONResponse(status_code=e.http, content={
            "ok": False,
            "error": {"code": e.code, "message": e.message,
                      "request_id": e.request_id},
        })

    # ── status / me ─────────────────────────────────────────────────────────
    @router.get("/status")
    def status():
        mode = state.adapter.effective_mode()
        return {"ok": True, "data": {
            "mode": mode,
            "demo_banner": mode == "demo",
            "matcher_available": state.adapter.available(),
            "model_version": state.adapter.model_version if state.adapter.available() else None,
            "rate_limit": "6/min per token on /recognize",
        }}

    @router.get("/me")
    def me(user: dict = Depends(_teacher)):
        return {"ok": True, "data": {
            "user_id": user["user_id"], "email": user["email"], "role": user["role"],
        }}

    # ── auth ────────────────────────────────────────────────────────────────
    @router.post("/auth/login")
    def login(body: schemas.LoginIn):
        sess = state.auth.authenticate_password(body.email, body.password)
        if not sess:
            return errp(AttendanceError(code="invalid_credentials", http=401,
                                        message="Bad email or password."))
        return {"ok": True, "data": sess}

    @router.post("/auth/logout")
    def logout(authorization: Optional[str] = Header(default=None), user: dict = Depends(_teacher)):
        if authorization and authorization.lower().startswith("bearer "):
            state.auth.revoke_token(authorization[7:].strip())
        return {"ok": True, "data": {"revoked": True}}

    # ── students ────────────────────────────────────────────────────────────
    @router.get("/students")
    def list_students(user: dict = Depends(_teacher)):
        return {"ok": True, "data": {"students": state.service.list_students()}}

    @router.post("/students")
    def create_student(body: schemas.StudentIn, user: dict = Depends(_teacher)):
        try:
            st = state.service.create_student(body.student_code, body.full_name,
                                              user["user_id"])
            return {"ok": True, "data": st}
        except AttendanceError as e:
            return errp(e)

    # ── courses ─────────────────────────────────────────────────────────────
    @router.get("/courses")
    def list_courses(user: dict = Depends(_teacher)):
        rows = state.db.query(
            "SELECT c.*, u.email AS teacher_email,"
            " (SELECT COUNT(*) FROM course_enrollments ce"
            "   WHERE ce.course_id = c.id AND ce.active = 1) AS enrolled_count"
            " FROM courses c"
            " LEFT JOIN users u ON u.id = c.teacher_id ORDER BY c.code")
        return {"ok": True, "data": {"courses": rows}}

    @router.post("/courses")
    def create_course(body: schemas.CourseIn, user: dict = Depends(_teacher)):
        try:
            tid = body.teacher_id or user["user_id"]
            c = state.service.create_course(body.code, body.name, tid,
                                            body.timezone, body.late_after_minutes,
                                            user["user_id"])
            return {"ok": True, "data": c}
        except AttendanceError as e:
            return errp(e)

    @router.get("/courses/{course_id}")
    def course_detail(course_id: str, user: dict = Depends(_teacher)):
        try:
            summary = state.service.course_summary(course_id)
            return {"ok": True, "data": {
                "course": summary["course"],
                "students": summary["students"],
            }}
        except AttendanceError as e:
            return errp(e)

    @router.post("/courses/{course_id}/enroll")
    def enroll(course_id: str, body: schemas.EnrollIn, user: dict = Depends(_teacher)):
        try:
            ids = list(body.student_ids or [])
            for code in (body.student_codes or []):
                row = state.db.query_one(
                    "SELECT id FROM students WHERE student_code = :c AND active = 1",
                    {"c": code.strip().upper()})
                if row:
                    ids.append(row["id"])
            if not ids:
                return errp(AttendanceError(code="validation_error", http=422,
                                            message="No students matched the given codes/ids."))
            res = state.service.enroll_students(course_id, ids, user["user_id"])
            return {"ok": True, "data": res}
        except AttendanceError as e:
            return errp(e)

    # ── consent + templates ─────────────────────────────────────────────────
    @router.post("/students/{student_id}/consent")
    def record_consent(student_id: str, body: schemas.ConsentIn,
                       user: dict = Depends(_teacher)):
        try:
            c = state.service.record_consent(student_id, body.consent_version,
                                             body.purpose, body.evidence_ref,
                                             user["user_id"])
            return {"ok": True, "data": c}
        except AttendanceError as e:
            return errp(e)

    @router.post("/students/{student_id}/consent/revoke")
    def revoke_consent(student_id: str, user: dict = Depends(_teacher)):
        try:
            c = state.service.revoke_consent(student_id, user["user_id"])
            return {"ok": True, "data": c}
        except AttendanceError as e:
            return errp(e)

    @router.get("/students/{student_id}/templates")
    def list_templates(student_id: str, user: dict = Depends(_teacher)):
        return {"ok": True, "data": {"templates": state.service.list_templates(student_id)}}

    @router.post("/students/{student_id}/templates")
    def enroll_face(student_id: str, body: schemas.EnrollTemplateIn,
                    user: dict = Depends(_teacher)):
        raw = _b64decode(body.image)
        try:
            t = state.service.enroll_face(student_id, raw, user["user_id"])
            return {"ok": True, "data": t}
        except AttendanceError as e:
            return errp(e)

    # ── sessions ────────────────────────────────────────────────────────────
    @router.post("/sessions")
    def start_session(body: schemas.SessionCreate, user: dict = Depends(_teacher)):
        try:
            s = state.service.start_session(body.course_id, body.starts_at,
                                            user["user_id"])
            return {"ok": True, "data": s}
        except AttendanceError as e:
            return errp(e)

    @router.get("/sessions")
    def list_sessions(user: dict = Depends(_teacher)):
        return {"ok": True, "data": {"sessions": state.service.list_sessions()}}

    @router.post("/sessions/{session_id}/close")
    def close_session(session_id: str, user: dict = Depends(_teacher)):
        try:
            s = state.service.close_session(session_id, user["user_id"])
            return {"ok": True, "data": s}
        except AttendanceError as e:
            return errp(e)

    @router.get("/sessions/{session_id}")
    def session_detail(session_id: str, user: dict = Depends(_teacher)):
        try:
            d = state.service.session_detail(session_id)
            return {"ok": True, "data": d}
        except AttendanceError as e:
            return errp(e)

    @router.get("/sessions/{session_id}/summary")
    def session_summary(session_id: str, user: dict = Depends(_teacher)):
        try:
            d = state.service.attendance_summary(session_id)
            d["records"] = state.service.session_detail(session_id)["records"]
            return {"ok": True, "data": d}
        except AttendanceError as e:
            return errp(e)

    @router.post("/sessions/{session_id}/recognize")
    def recognize(session_id: str, body: schemas.RecognizeIn,
                  user: dict = Depends(_teacher)):
        if not state.rate.allow(user["user_id"]):
            return errp(AttendanceError(code="rate_limited", http=429,
                                        message="Too many recognition calls. 6/min."))
        raw = _b64decode(body.image)

        if body.request_id:
            prior = state.db.query_one(
                "SELECT * FROM attendance_events WHERE request_id = :r",
                {"r": body.request_id})
            if prior:
                return {"ok": True, "data": {
                    "event_id": prior["id"],
                    "session_id": prior["session_id"],
                    "result": schemas.RecognitionResult(
                        status=prior["recognition_status"],
                        student_id=prior["student_id"],
                        reason=prior["reason"], model_version=prior["model_version"]
                    ).model_dump(),
                    "status_outcome": prior["action"],
                    "idempotent_replay": True,
                }}
        try:
            res = state.service.recognize_event(session_id, raw, body.request_id,
                                                user["user_id"])
            return {"ok": True, "data": {
                "event_id": res["event_id"],
                "session_id": res["session_id"],
                "result": res["result"].model_dump(),
                "status_outcome": res["status_outcome"],
            }}
        except AttendanceError as e:
            return errp(e)

    @router.post("/sessions/{session_id}/manual")
    def manual_mark(session_id: str, body: schemas.MarkManualIn,
                    user: dict = Depends(_teacher)):
        try:
            sid = body.student_id
            if not sid and body.student_code:
                row = state.db.query_one(
                    "SELECT id FROM students WHERE student_code = :c AND active = 1",
                    {"c": body.student_code.strip().upper()})
                if not row:
                    return errp(AttendanceError(code="validation_error", http=422,
                                                message="Unknown student code."))
                sid = row["id"]
            m = state.service.manual_mark(session_id, sid, body.status,
                                          body.reason, user["user_id"])
            return {"ok": True, "data": m}
        except AttendanceError as e:
            return errp(e)
    @router.get("/sessions/{session_id}/events")
    def session_events(session_id: str, user: dict = Depends(_teacher)):
        rows = state.db.query(
            "SELECT * FROM attendance_events WHERE session_id = :s"
            " ORDER BY timestamp DESC LIMIT 100",
            {"s": session_id})
        return {"ok": True, "data": {"events": rows}}

    @router.get("/sessions/{session_id}/export.csv")
    def export_csv(session_id: str, user: dict = Depends(_teacher)):
        try:
            csv_text, fname = state.service.export_csv(session_id)
            headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
            return Response(content=csv_text, media_type="text/csv", headers=headers)
        except AttendanceError as e:
            return errp(e)

    return router