"""Matcher providers — pluggable face recognizers for the attendance app.

The attendance app NEVER talks to a camera or a recognizer directly: it talks to
a :class:`RecognitionAdapter`, which delegates to a provider implementing the
small protocol below. Swap the provider to change the matcher.

    match(image_bytes: bytes) -> List[Tuple[str, float]]
        Decode the frame, detect faces, embed, and return ranked
        ``(student_code, similarity)`` pairs (best first). Never more than one
        face is accepted — raise :class:`NoFaceError` / :class:`MultiFaceError`
        to preserve those statuses. Faces not in the enrolled gallery raise
        :class:`UnknownFaceError`.

Providers raise the errors below instead of fabricating scores; the adapter
maps them to fail-closed ``RecognitionResult`` statuses.

Camera-tested path: :class:`InsightFaceProvider` (pure insightface, no CamBrain
dependency) — activate by running with `RECOGNITION_MODE=real` on a box where
``insightface`` is installed (see docs/ENV.md). Every other mode is available
right now with zero camera/matcher hardware.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .database import AttendanceDB


class ProviderError(Exception):
    """Base — matcher is down or misconfigured (maps to 'unavailable')."""


class NoFaceError(ProviderError):
    reason = "no face detected"


class MultiFaceError(ProviderError):
    reason = "multiple faces in frame"


class LowQualityError(ProviderError):
    reason = "failed to decode image"


class UnknownFaceError(ProviderError):
    reason = "no enrollment gallery loaded"


MATCH_THRESHOLD = 0.45      # below this = not this person
SOLID_BAR = 0.55            # above this always matches
AMBIGUITY_GAP = 0.02        # top-1 vs top-2 closer than this = ambiguous


class InsightFaceProvider:
    """Real recognition via insightface (buffalo_l), matching against the
    attendance app's OWN enrolled templates on disk.

    Lazy: constructs even when insightface is missing (``available`` stays
    False; every call then maps to 'unavailable' → fail-closed). Embedding
    gallery is rebuilt from ``face_templates`` on ``reload_gallery()`` (called
    at boot and after every enrollment). Embeddings live in memory only —
    the DB carries only template file paths (privacy invariant).
    """

    model_version = "insightface-buffalo_l-root-0.2"

    def __init__(self, db: Optional[AttendanceDB] = None) -> None:
        self.db = db
        self.ctx_id = -1  # CPU; set INSIGHT_CUDA=1 for GPU
        self._app = None
        self._gallery: dict[str, list] = {}  # student_code -> normalized embeds

    @property
    def available(self) -> bool:
        if not self._app:
            try:
                import os
                if os.environ.get("INSIGHT_CUDA") == "1":
                    self.ctx_id = 0
                import insightface
                from insightface.app import FaceAnalysis
                self._app = FaceAnalysis(name="buffalo_l",
                                         allowed_modules=["detection", "recognition"])
                self._app.prepare(ctx_id=self.ctx_id, det_size=(640, 640))
            except Exception:
                self._app = None
        return self._app is not None

    def reload_gallery(self) -> None:
        """(Re)embed every enrolled template file into the in-memory gallery."""
        self._gallery.clear()
        if not self.available or not self.db:
            return
        import numpy as np
        import cv2
        rows = self.db.query(
            "SELECT t.template_ref AS ref, s.student_code AS code"
            " FROM face_templates t JOIN students s ON s.id = t.student_id"
            " WHERE t.revoked_at IS NULL")
        for row in rows:
            try:
                frame = cv2.imread(row["ref"], cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                faces = self._app.get(frame)
                if not faces or len(faces) != 1:
                    continue
                emb = self._norm(np.array(faces[0].embedding, dtype=np.float32))
                self._gallery.setdefault(row["code"], []).append(emb)
            except Exception:
                continue  # a bad template file never blocks recognition

    def match(self, image_bytes: bytes) -> List[Tuple[str, float]]:
        if not self.available:
            raise ProviderError("insightface unavailable")
        import numpy as np
        import cv2
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise LowQualityError()
        faces = self._app.get(frame)
        if not faces:
            raise NoFaceError()
        if len(faces) > 1:
            raise MultiFaceError()
        probe = self._norm(np.array(faces[0].embedding, dtype=np.float32))
        if not self._gallery:
            raise UnknownFaceError()
        ranked = []
        for code, refs in self._gallery.items():
            best = max(float(np.dot(probe, r)) for r in refs)
            ranked.append((code, best))
        ranked.sort(key=lambda t: -t[1])
        return ranked[0:3]

    @staticmethod
    def _norm(v):
        n = float(v @ v) ** 0.5
        return v / n if n > 1e-9 else v


def default_provider(db: Optional[AttendanceDB] = None) -> InsightFaceProvider:
    return InsightFaceProvider(db)