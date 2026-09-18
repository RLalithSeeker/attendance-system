"""Recognition adapter — the only place attendance talks to a matcher.

Modes (env RECOGNITION_MODE):
- real     Use the configured matcher provider (InsightFace by default). If no
           provider is available (e.g. insightface not installed) the adapter
           reports ``unavailable`` — fail-closed, never guessed.
- demo     DETERMINISTIC, PRODUCT-DEMO-ONLY. Matches by image hash, not identity.
           The UI shows a fixed "DEMO / SIMULATED RECOGNITION" banner and the
           result is flagged. Never enabled without an explicit env setting.
- disabled Recognition off. Manual marking still works.
- auto     (default) real if a provider is available, else disabled.

The provider agreement is in ``matcher_providers.py``. The adapter owns the
matching thresholds and the mapping to RecognitionResult statuses; the provider
owns frame decode, face detection, embedding and gallery scoring.
"""

from __future__ import annotations

import hashlib
import os
from typing import List, Optional, Tuple

import numpy as np

from . import matcher_providers as providers
from .database import AttendanceDB
from .schemas import RecognitionResult

# Back-compat constant: fallback when no real provider is present.
MODEL_VERSION = "insightface-buffalo_l-root-0.1"


class RecognitionAdapter:
    def __init__(self, db: AttendanceDB, mode: str = "auto",
                 provider: Optional[providers.InsightFaceProvider] = None):
        self.mode = mode
        self.db = db
        self._provider = provider if provider is not None else providers.default_provider(db)

    # ── availability ─────────────────────────────────────────────────────────
    @property
    def provider(self):
        return self._provider

    def available(self) -> bool:
        if self.mode in ("disabled", "demo"):
            return False  # demo is available for ITS path; see effective_mode()
        return bool(self._provider is not None and self._provider.available)

    def effective_mode(self) -> str:
        if self.mode == "auto":
            return "real" if self.available() else "disabled"
        if self.mode == "real" and not self.available():
            return "disabled"
        return self.mode

    @property
    def model_version(self) -> str:
        if self._provider is not None and self._provider.available:
            return getattr(self._provider, "model_version", MODEL_VERSION)
        return "demo-model" if self.mode == "demo" else MODEL_VERSION

    def reload_gallery(self) -> None:
        """Rebuild the provider's enrollment gallery (boot + after enroll)."""
        if self._provider is not None and hasattr(self._provider, "reload_gallery"):
            self._provider.reload_gallery()

    # ── the one entry point ──────────────────────────────────────────────────
    def recognize(self, image_bytes: bytes) -> RecognitionResult:
        mode = self.effective_mode()
        if mode == "disabled":
            return RecognitionResult(status="unavailable",
                                     reason="matcher unavailable")
        if mode == "demo":
            return self._recognize_demo(image_bytes)
        return self._recognize_real(image_bytes)

    def _recognize_real(self, image_bytes: bytes) -> RecognitionResult:
        try:
            ranked = self._provider.match(image_bytes)
        except providers.NoFaceError as e:
            return RecognitionResult(status="no_face", reason=e.reason)
        except providers.MultiFaceError as e:
            return RecognitionResult(status="multi_face", reason=e.reason)
        except providers.LowQualityError as e:
            return RecognitionResult(status="low_quality", reason=e.reason)
        except providers.UnknownFaceError as e:
            return RecognitionResult(status="unknown", reason=e.reason)
        except Exception as e:
            return RecognitionResult(status="unavailable",
                                     reason=f"matcher error: {type(e).__name__}")

        if not ranked:
            return RecognitionResult(status="unknown", reason="no enrollment")

        best_code, best_sim = ranked[0]
        second_sim = ranked[1][1] if len(ranked) > 1 else -1.0
        gap = best_sim - second_sim if second_sim >= 0 else 1.0

        if best_sim >= providers.SOLID_BAR:
            pass
        elif best_sim < providers.MATCH_THRESHOLD or gap < providers.AMBIGUITY_GAP:
            if best_sim < providers.MATCH_THRESHOLD:
                return RecognitionResult(status="unknown", score=best_sim,
                                         model_version=self.model_version,
                                         reason="below threshold")
            return RecognitionResult(status="ambiguous", score=best_sim,
                                     model_version=self.model_version,
                                     reason="top scores too close")

        # Resolve the matched code to an ACTUAL enrolled, active student.
        student = self._student_for_code(best_code)
        if student is None:
            return RecognitionResult(status="unknown", score=best_sim,
                                     model_version=self.model_version,
                                     reason="name not in attendance roster")
        return RecognitionResult(status="matched", student_id=student["id"],
                                 score=best_sim, model_version=self.model_version,
                                 reason=getattr(self._provider, "model_version",
                                                MODEL_VERSION))

    def _student_for_code(self, code: str) -> Optional[dict]:
        row = self.db.query_one(
            "SELECT id, student_code FROM students"
            " WHERE UPPER(student_code) = :code AND active = 1",
            {"code": str(code).upper()},
        )
        return row

    # demo path ────────────────────────────────────────────────────────────────
    def _recognize_demo(self, image_bytes: bytes) -> RecognitionResult:
        digest = hashlib.sha256(image_bytes).hexdigest()[:12]
        idx = int(digest, 16) % 1000
        demo = self.db.query_one(
            "SELECT id FROM students WHERE active = 1 "
            "ORDER BY student_code LIMIT 1 OFFSET :o",
            {"o": idx % max(1, self._count_students())},
        )
        if demo is None:
            return RecognitionResult(status="no_face", reason="demo: no students enrolled")
        return RecognitionResult(status="matched",
                                 student_id=demo["id"],
                                 score=round(0.9 + (idx % 10) / 100.0, 2),
                                 model_version="demo-model",
                                 reason="DEMO / SIMULATED RECOGNITION — NOT identity")

    def _count_students(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS c FROM students WHERE active = 1")
        return int(row["c"]) if row else 0


def adapter_for(db: AttendanceDB, mode: Optional[str] = None,
                provider: Optional[providers.InsightFaceProvider] = None) -> RecognitionAdapter:
    mode = mode or os.environ.get("RECOGNITION_MODE", "auto")
    return RecognitionAdapter(db, mode=mode, provider=provider)