"""Standalone Attendance Server.

Run: python main.py  (or: uvicorn main:app --reload)
Env: RECOGNITION_MODE  (auto|demo|live|disabled), default auto.

This is the SEPARATE project — no CamBrain / insightface / torch required for
demo or disabled modes. Real matching is activated by installing insightface and
setting RECOGNITION_MODE=real (see docs/ENV.md).
"""

import os
import sys

# Allow `python main.py` from the repo root.
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from attendance.app import build_runtime, seed_demo

# ── provider (lazy) ──────────────────────────────────────────────────────────
# In real mode, build_runtime() instantiates an InsightFaceProvider internally
# when insightface is importable; the provider stays inactive (available=False)
# otherwise, so every mode works without camera/matcher hardware.
_rt = build_runtime()
seed_demo(_rt["db"])  # idempotent: gives teacher@demo.local / demo1234 on first boot
_app = FastAPI(title="Attendance", version="0.1.0")

# mount the API router
from attendance.routers import build_router
from attendance.errors import AttendanceError

_app.include_router(build_router(
    _rt["db"], _rt["auth"], _rt["adapter"], _rt["service"],
))


@_app.exception_handler(AttendanceError)
async def _attendance_error_handler(request, exc):
    return JSONResponse(status_code=exc.http, content={
        "ok": False,
        "error": {"code": exc.code, "message": exc.message,
                  "request_id": exc.request_id or ""}})


@_app.get("/attendance/health")
def attendance_health():
    return {"status": "ok", "service": "attendance",
            "mode": _rt["adapter"].effective_mode()}


@_app.get("/", response_class=HTMLResponse)
def attendance_ui():
    tpl = os.path.join(os.path.dirname(__file__), "templates", "attendance.html")
    with open(tpl, encoding="utf-8") as f:
        return f.read()


print(f"[attendance] mode={_rt['adapter'].effective_mode()}")

app = _app  # uvicorn main:app entry


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(_app, host="0.0.0.0", port=8000, reload=True)
