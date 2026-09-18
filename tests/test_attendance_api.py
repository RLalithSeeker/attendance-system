"""Attendance API tests.

Env-truth notes (see docs/attendance/REPO_AUDIT.md):
- Real recognition (insightface) is NOT importable in CI / system python, so the
  full auto-mark pipeline is exercised through the demo adapter (deterministic
  hash-based match, SIMULATED). Fail-closed behaviour is asserted with a
  'disabled' adapter: recognition is refused instead of guessing.
- These tests build the standalone attendance app directly. They deliberately
  do NOT import main.py (needs the heavy engine stack).

Run: python -m pytest tests/test_attendance_api.py -q
"""

from __future__ import annotations

import base64
import glob
import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from attendance.app import create_app, seed_demo
from attendance.auth import TeacherAuth
from attendance.database import AttendanceDB
from attendance.recognition_adapter import RecognitionAdapter
from attendance.service import AttendanceService

PREFIX = "/api/attendance/v1"


def _empty_demo_app(db_path: str, mode: str = "demo"):
    db = AttendanceDB(sqlite_path=db_path)
    db.migrate()
    seed_demo(db)
    auth = TeacherAuth(db)
    adapter = RecognitionAdapter(db, mode=mode)
    service = AttendanceService(db, auth, adapter)
    app = create_app({"db": db, "auth": auth, "adapter": adapter, "service": service})
    return app, db


@pytest.fixture(scope="module")
def demo_ctx():
    td = tempfile.mkdtemp(prefix="att_demo_")
    app, db = _empty_demo_app(os.path.join(td, "att.db"))
    c = TestClient(app)
    r = c.post(f"{PREFIX}/auth/login",
               json={"email": "teacher@demo.local", "password": "demo1234"})
    assert r.status_code == 200
    token = r.json()["data"]["token"]
    h = {"Authorization": f"Bearer {token}"}
    return c, h, db


@pytest.fixture(scope="module")
def disabled_ctx():
    td = tempfile.mkdtemp(prefix="att_dis_")
    app, db = _empty_demo_app(os.path.join(td, "att.db"), mode="disabled")
    c = TestClient(app)
    r = c.post(f"{PREFIX}/auth/login",
               json={"email": "teacher@demo.local", "password": "demo1234"})
    token = r.json()["data"]["token"]
    h = {"Authorization": f"Bearer {token}"}
    return c, h, db


@pytest.fixture(scope="module")
def rate_ctx():
    td = tempfile.mkdtemp(prefix="att_rate_")
    app, db = _empty_demo_app(os.path.join(td, "att.db"))
    c = TestClient(app)
    r = c.post(f"{PREFIX}/auth/login",
               json={"email": "teacher@demo.local", "password": "demo1234"})
    token = r.json()["data"]["token"]
    h = {"Authorization": f"Bearer {token}"}
    return c, h, db


def _jpg_bytes(seed: int = 5) -> str:
    try:
        import numpy as np
        import cv2
        img = np.full((128, 128, 3), seed * 20, dtype="uint8")
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        return base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return base64.b64encode(b"jpegbinary" * seed).decode()


# ── auth ─────────────────────────────────────────────────────────────────────
def _open_session(c, h, course_id: str) -> str:
    """Close any open session for the course, then start a fresh one."""
    for s in c.get(f"{PREFIX}/sessions", headers=h).json()["data"]["sessions"]:
        if s["course_id"] == course_id and s["status"] == "active":
            c.post(f"{PREFIX}/sessions/{s['id']}/close", headers=h)
    r = c.post(f"{PREFIX}/sessions", json={"course_id": course_id}, headers=h)
    assert r.status_code == 200, f"session create failed: {r.text}"
    return r.json()["data"]["id"]


def test_login_bad_password(demo_ctx):
    c, _, _ = demo_ctx
    r = c.post(f"{PREFIX}/auth/login",
               json={"email": "teacher@demo.local", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_me_requires_token(demo_ctx):
    c, _, _ = demo_ctx
    r = c.get(f"{PREFIX}/me")
    assert r.status_code == 401


def test_me_with_token(demo_ctx):
    c, h, _ = demo_ctx
    r = c.get(f"{PREFIX}/me", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["email"] == "teacher@demo.local"


def test_bad_token_rejected(demo_ctx):
    c, _, _ = demo_ctx
    r = c.get(f"{PREFIX}/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


# ── students / courses / enrollment ──────────────────────────────────────────
def test_students_seeded(demo_ctx):
    c, h, _ = demo_ctx
    r = c.get(f"{PREFIX}/students", headers=h)
    body = r.json()["data"]["students"]
    codes = sorted(s["student_code"] for s in body)
    assert codes == ["S1001", "S1002", "S1003"]


def test_duplicate_student_409(demo_ctx):
    c, h, _ = demo_ctx
    r = c.post(f"{PREFIX}/students",
               json={"student_code": "S1001", "full_name": "Clone"}, headers=h)
    assert r.status_code == 409


def test_course_enroll_by_code(demo_ctx):
    c, h, db = demo_ctx
    r = c.post(f"{PREFIX}/courses",
               json={"code": "CS305", "name": "Algorithms III"}, headers=h)
    assert r.status_code == 200
    cid = r.json()["data"]["id"]

    r = c.post(f"{PREFIX}/courses/{cid}/enroll",
               json={"student_codes": ["s1002"]}, headers=h)  # lowercase to prove uppercasing
    assert r.status_code == 200
    assert r.json()["data"]["added"] == 1

    r = c.get(f"{PREFIX}/courses/{cid}", headers=h)
    detail = r.json()["data"]
    assert [s["student_code"] for s in detail["students"]] == ["S1002"]

    courses = c.get(f"{PREFIX}/courses", headers=h).json()["data"]["courses"]
    mine = next(x for x in courses if x["id"] == cid)
    assert mine["enrolled_count"] == 1


def test_enroll_requires_identifier(demo_ctx):
    c, h, db = demo_ctx
    r = c.post(f"{PREFIX}/courses", json={"code": "CS210", "name": "Theory"}, headers=h)
    cid = r.json()["data"]["id"]
    r = c.post(f"{PREFIX}/courses/{cid}/enroll", json={}, headers=h)
    assert r.status_code == 422


def test_unknown_enroll_code_422(demo_ctx):
    c, h, db = demo_ctx
    r = c.post(f"{PREFIX}/courses", json={"code": "CS211", "name": "Linear"}, headers=h)
    cid = r.json()["data"]["id"]
    r = c.post(f"{PREFIX}/courses/{cid}/enroll",
               json={"student_codes": ["NOPE999"]}, headers=h)
    assert r.status_code == 422


# ── consent + templates ──────────────────────────────────────────────────────
def test_consent_version_min_length(demo_ctx):
    c, h, db = demo_ctx
    students = c.get(f"{PREFIX}/students", headers=h).json()["data"]["students"]
    sid = students[2]["id"]
    r = c.post(f"{PREFIX}/students/{sid}/consent",
               json={"consent_version": "1"}, headers=h)  # too short
    assert r.status_code == 422


def test_consent_and_template_flow(demo_ctx):
    c, h, db = demo_ctx
    students = c.get(f"{PREFIX}/students", headers=h).json()["data"]["students"]
    sid = students[1]["id"]
    r = c.post(f"{PREFIX}/students/{sid}/consent",
               json={"consent_version": "v1"}, headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["active"] is True

    r = c.post(f"{PREFIX}/students/{sid}/templates", headers=h,
               json={"image": _jpg_bytes(1)})
    assert r.status_code == 200
    assert r.json()["data"]["model_version"] == "demo-model"

    r = c.get(f"{PREFIX}/students/{sid}/templates", headers=h)
    assert r.status_code == 200
    assert len(r.json()["data"]["templates"]) == 1


def test_template_requires_consent(demo_ctx):
    c, h, db = demo_ctx
    students = c.get(f"{PREFIX}/students", headers=h).json()["data"]["students"]
    sid = students[0]["id"]  # no consent recorded yet for S1001
    r = c.post(f"{PREFIX}/students/{sid}/templates", headers=h,
               json={"image": _jpg_bytes(2)})
    assert r.status_code == 403
def test_full_session_demo_flow(demo_ctx):
    c, h, db = demo_ctx
    courses = c.get(f"{PREFIX}/courses", headers=h).json()["data"]["courses"]
    seed_course = next(x for x in courses if x["code"] == "CS201")

    sid = _open_session(c, h, seed_course["id"])

    sessions = c.get(f"{PREFIX}/sessions", headers=h).json()["data"]["sessions"]
    row = next(x for x in sessions if x["id"] == sid)
    assert row["course_code"] == "CS201"
    assert row["student_count"] == 3

    r = c.post(f"{PREFIX}/sessions/{sid}/recognize", headers=h,
               json={"session_id": sid, "image": _jpg_bytes(3),
                     "request_id": "req-1"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["result"]["status"] == "matched"
    assert data["result"]["model_version"] == "demo-model"
    assert data["status_outcome"] in ("present", "late")

    # idempotent replay via request_id
    r2 = c.post(f"{PREFIX}/sessions/{sid}/recognize", headers=h,
                json={"session_id": sid, "image": _jpg_bytes(3),
                      "request_id": "req-1"})
    assert r2.json()["data"]["event_id"] == data["event_id"]
    assert r2.json()["data"].get("idempotent_replay") is True

    summ = c.get(f"{PREFIX}/sessions/{sid}/summary", headers=h).json()["data"]
    assert summ["status"] == "active"
    assert summ["present"] + summ["late"] == 1
    assert summ["unaccounted"] == 3 - summ["present"] - summ["late"]
    assert isinstance(summ["records"], list) and len(summ["records"]) == 1

    r = c.post(f"{PREFIX}/sessions/{sid}/close", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "closed"


def test_manual_mark_by_code(demo_ctx):
    c, h, db = demo_ctx
    courses = c.get(f"{PREFIX}/courses", headers=h).json()["data"]["courses"]
    seed_course = next(x for x in courses if x["code"] == "CS201")
    sid = _open_session(c, h, seed_course["id"])

    r = c.post(f"{PREFIX}/sessions/{sid}/manual", headers=h,
               json={"student_code": "S1003", "status": "excused",
                     "reason": "field trip"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "excused"

    summ = c.get(f"{PREFIX}/sessions/{sid}/summary", headers=h).json()["data"]
    assert summ["excused"] == 1
    assert summ["records"][0]["student_code"] == "S1003"

    # unknown code -> 422, no record written
    r2 = c.post(f"{PREFIX}/sessions/{sid}/manual", headers=h,
                json={"student_code": "NOPE", "status": "present"})
    assert r2.status_code == 422


def test_export_csv_injection_escaped(demo_ctx):
    c, h, db = demo_ctx
    courses = c.get(f"{PREFIX}/courses", headers=h).json()["data"]["courses"]
    seed_course = next(x for x in courses if x["code"] == "CS201")

    # ensure attacker student exists (idempotent across repeated runs)
    code = "S1009"
    existing = [s for s in c.get(f"{PREFIX}/students", headers=h).json()["data"]["students"]
                if s["student_code"] == code]
    if existing:
        stid = existing[0]["id"]
    else:
        st = c.post(f"{PREFIX}/students",
                    json={"student_code": code, "full_name": "=SUM(A1:A9)"}, headers=h)
        assert st.status_code == 200
        stid = st.json()["data"]["id"]
    c.post(f"{PREFIX}/courses/{seed_course['id']}/enroll",
           json={"student_ids": [stid]}, headers=h)
    sid = _open_session(c, h, seed_course["id"])

    r = c.get(f"{PREFIX}/sessions/{sid}/export.csv", headers=h)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    # hostile name must be apostrophe-prefixed (never a live-formula cell)
    assert "'=SUM(A1:A9)" in r.text
    assert "\n=SUM(A1:A9)" not in r.text
    assert ",=SUM(A1:A9)," not in r.text


def test_session_not_found(demo_ctx):
    c, h, db = demo_ctx
    r = c.get(f"{PREFIX}/sessions/nope", headers=h)
    assert r.status_code == 404


# ── fail-closed: recognition disabled ────────────────────────────────────────
def test_recognize_fail_closed_when_disabled(disabled_ctx):
    c, h, db = disabled_ctx
    courses = c.get(f"{PREFIX}/courses", headers=h).json()["data"]["courses"]
    seed_course = next(x for x in courses if x["code"] == "CS201")
    sid = _open_session(c, h, seed_course["id"])

    r = c.post(f"{PREFIX}/sessions/{sid}/recognize", headers=h,
               json={"session_id": sid, "image": _jpg_bytes(9)})
    assert r.status_code == 503
    assert r.json()["ok"] is False
    assert r.json()["error"]["code"] == "matcher_unavailable"

    # nothing recorded while disabled
    summ = c.get(f"{PREFIX}/sessions/{sid}/summary", headers=h).json()["data"]
    assert summ["present"] + summ["late"] == 0
    assert summ["unaccounted"] == 3

    # manual still permitted (the designed fallback)
    r = c.post(f"{PREFIX}/sessions/{sid}/manual", headers=h,
               json={"student_code": "S1001", "status": "present"})
    assert r.status_code == 200
    # closing works too
    assert c.post(f"{PREFIX}/sessions/{sid}/close", headers=h).status_code == 200


# ── rate limiting ────────────────────────────────────────────────────────────
def test_recognize_rate_limited(rate_ctx):
    c, h, db = rate_ctx
    courses = c.get(f"{PREFIX}/courses", headers=h).json()["data"]["courses"]
    seed_course = next(x for x in courses if x["code"] == "CS201")
    sid = _open_session(c, h, seed_course["id"])

    codes = [200, 200, 200, 200, 200, 200, 429]
    for i, want in enumerate(codes):
        r = c.post(f"{PREFIX}/sessions/{sid}/recognize", headers=h,
                   json={"session_id": sid, "image": _jpg_bytes(i)})
        assert r.status_code == want, f"call {i}: wanted {want}, got {r.status_code}"
        if want == 429:
            assert r.json()["error"]["code"] == "rate_limited"