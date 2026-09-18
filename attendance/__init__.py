"""Standalone face-recognition class attendance app.

Facial-recognition class attendance with a swappable matcher provider. No camera
is required for demo / disabled operation; `real` mode needs insightface (see
docs/ENV.md) and fails closed when unavailable. See docs/ for the audit + plan.
"""

__all__ = [
    "app", "auth", "database", "errors", "matcher_providers", "migrate",
    "recognition_adapter", "routers", "schemas", "service",
]