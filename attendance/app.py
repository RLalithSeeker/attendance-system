"""Attendance app assembly.

``create_app()`` builds a standalone FastAPI app from the SAME router that the
``main.py`` entrypoint mounts — it exists so the attendance API is testable and
demo-runnable with zero camera / matcher hardware. Recognition is a swappable
matcher-provider (see ``matcher_providers.py``); every mode except ``real``
runs with no camera and no insightface installed.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .auth import TeacherAuth
from .database import AttendanceDB
from .errors import AttendanceError
from . import matcher_providers as providers
from .recognition_adapter import adapter_for
from .routers import build_router
from .service import AttendanceService


def build_runtime(db: Optional[AttendanceDB] = None,
                  provider: Optional[providers.InsightFaceProvider] = None) -> dict:
    """Assemble db/auth/adapter/service for a given (or default) database."""
    db = db or AttendanceDB()
    db.migrate()
    auth = TeacherAuth(db)
    adapter = adapter_for(db, provider=provider)
    adapter.reload_gallery()
    service = AttendanceService(db, auth, adapter)
    return {"db": db, "auth": auth, "adapter": adapter, "service": service}


def create_app(runtime: Optional[dict] = None) -> FastAPI:
    rt = runtime or build_runtime()
    app = FastAPI(title="Attendance", version="0.1.0")
    router = build_router(rt["db"], rt["auth"], rt["adapter"], rt["service"])
    app.include_router(router)

    @app.exception_handler(AttendanceError)
    async def _on_err(request: Request, exc: AttendanceError):
        return JSONResponse(status_code=exc.http, content={
            "ok": False,
            "error": {"code": exc.code, "message": exc.message,
                      "request_id": exc.request_id or ""},
        })

    @app.get("/attendance/health")
    def health():
        return {"status": "ok", "service": "attendance",
                "mode": rt["adapter"].effective_mode()}

    return app


def seed_demo(db: AttendanceDB, with_biometric: bool = False) -> None:
    """One-time demo data (teachers/course/students) — NO biometrics by default."""
    from .auth import password_hash
    from .database import iso_utc
    import uuid

    if db.query_one("SELECT 1 FROM students LIMIT 1"):
        return  # already seeded

    with db.transaction() as conn:
        t_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role, active, created_at)"
            " VALUES (:id, :email, :pw, 'teacher', 1, :ts)",
            {"id": t_id, "email": "teacher@demo.local",
             "pw": password_hash("demo1234"), "ts": iso_utc()})
        for code, name in (("S1001", "Aarav Mehta"), ("S1002", "Diya Nair"),
                           ("S1003", "Rohan Verma")):
            conn.execute(
                "INSERT INTO students (id, student_code, full_name, active, created_at)"
                " VALUES (:id, :code, :name, 1, :ts)",
                {"id": str(uuid.uuid4()), "code": code, "name": name,
                 "ts": iso_utc()})
        c_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO courses (id, code, name, teacher_id, timezone, created_at)"
            " VALUES (:id, 'CS201', 'Data Structures', :tid, 'Asia/Kolkata', :ts)",
            {"id": c_id, "tid": t_id, "ts": iso_utc()})
        students = conn.execute("SELECT id FROM students").fetchall()
        course = conn.execute("SELECT id FROM courses").fetchone()
        for st in students:
            conn.execute(
                "INSERT INTO course_enrollments (id, course_id, student_id, active, created_at)"
                " VALUES (:id, :c, :s, 1, :ts)",
                {"id": str(uuid.uuid4()), "c": course[0], "s": st[0],
                 "ts": iso_utc()})
        if with_biometric:
            for st in students:
                conn.execute(
                    "INSERT INTO biometric_consents"
                    " (id, student_id, consent_version, purpose, consented_at, collected_by_id)"
                    " VALUES (:id, :s, '1', 'face-recognition-attendance', :ts, :by)",
                    {"id": str(uuid.uuid4()), "s": st[0], "ts": iso_utc(),
                     "by": t_id})

    print("[attendance.seed] demo teacher teacher@demo.local / demo1234;"
          " course CS201; students S1001..S1003")