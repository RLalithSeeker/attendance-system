"""Pydantic request/response models for the attendance API.

All keep the envelope shape of the API contract:
  success: {"ok": true, "data": {...}}
  error:   {"ok": false, "error": {"code", "message", "request_id"}}
Recognition results obey contracts/recognition-result.md exactly (a matched
student_id is INSIDE RecognitionResult — a matched face alone is never enough
to mark present).
"""

from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ── auth ───────────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=256)


class StudentIn(BaseModel):
    student_code: str = Field(min_length=2, max_length=40)
    full_name: str = Field(min_length=2, max_length=160)

    @field_validator("student_code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v):
            raise ValueError("student_code must be alphanumeric (._- allowed)")
        return v.upper()

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("full_name too short")
        return v


class StudentOut(BaseModel):
    id: str
    student_code: str
    full_name: str
    active: bool


class CourseIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    teacher_id: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    late_after_minutes: Optional[int] = Field(default=None, ge=0, le=240)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v):
            raise ValueError("code must be alphanumeric (._- allowed)")
        return v.upper()


class CourseOut(BaseModel):
    id: str
    code: str
    name: str
    teacher_id: str
    timezone: str
    late_after_minutes: Optional[int]
    teacher_email: Optional[str] = None


class EnrollIn(BaseModel):
    student_ids: Optional[List[str]] = Field(default=None, max_length=200)
    student_codes: Optional[List[str]] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _either(self):
        if not self.student_ids and not self.student_codes:
            raise ValueError("provide student_ids or student_codes")
        return self


# ── consent / templates ────────────────────────────────────────────────────
class ConsentIn(BaseModel):
    consent_version: str = Field(min_length=2, max_length=40)
    purpose: str = "face-recognition-attendance"
    evidence_ref: Optional[str] = None


class ConsentOut(BaseModel):
    student_id: str
    consent_version: str
    consented_at: str
    revoked_at: Optional[str]
    active: bool


class EnrollTemplateIn(BaseModel):
    image: str  # base64 data URI or raw jpeg bytes base64

    @field_validator("image")
    @classmethod
    def _image_tag(cls, v: str) -> str:
        body = v.split(",", 1)[-1]
        return body


class TemplateOut(BaseModel):
    id: str
    student_id: str
    model_version: str
    enrolled_at: str
    revoked_at: Optional[str]


# ── sessions & attendance ─────────────────────────────────────────────────────
class SessionCreate(BaseModel):
    course_id: str
    starts_at: Optional[str] = None  # ISO UTC; None => now


class SessionOut(BaseModel):
    id: str
    course_id: str
    course_code: str
    starts_at: str
    ends_at: Optional[str]
    status: str
    present: int = 0
    total: int = 0


class MarkManualIn(BaseModel):
    student_id: Optional[str] = None
    student_code: Optional[str] = None
    status: Literal["present", "late", "absent", "excused"] = "present"
    reason: Optional[str] = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _either(self):
        if not self.student_id and not self.student_code:
            raise ValueError("provide student_id or student_code")
        return self


class AttendanceEventOut(BaseModel):
    id: str
    session_id: str
    student_id: Optional[str]
    recognition_status: str
    action: str
    timestamp: str
    reason: Optional[str]


# ── recognition contract (contracts/recognition-result.md) ───────────────────
class RecognitionResult(BaseModel):
    status: Literal[
        "matched",
        "unknown",
        "ambiguous",
        "no_face",
        "multi_face",
        "unavailable",
        "low_quality",
    ]
    student_id: Optional[str] = None
    score: Optional[float] = None
    score_kind: Literal["cosine_sim", "euclidean", "none"] = "cosine_sim"
    model_version: Optional[str] = None
    reason: Optional[str] = None


class RecognizeIn(BaseModel):
    image: str  # base64 data URI or raw base64
    session_id: str
    request_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("image")
    @classmethod
    def _tag(cls, v: str) -> str:
        return v.split(",", 1)[-1]


class RecognizeOut(BaseModel):
    event_id: str
    session_id: str
    result: RecognitionResult
    status_outcome: Literal["present", "late", "ambiguous", "unknown", "already_recorded", "no_action", "excused", "unavailable"]


class AttendanceSummaryOut(BaseModel):
    session_id: str
    course_id: str
    status: str
    total_enrolled: int
    present: int
    late: int
    absent: int
    excused: int
    unaccounted: int


class AttendanceRecordOut(BaseModel):
    student_code: str
    full_name: str
    status: str
    method: str
    first_seen_at: Optional[str]
    marked_by: Optional[str]