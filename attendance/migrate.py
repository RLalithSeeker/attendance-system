"""Attendance DB CLI.

Usage (from repo root):
    python -m attendance.migrate            # create/migrate schema
    python -m attendance.migrate --seed     # + demo teacher/course/students
    python -m attendance.migrate --seed-biometric
"""

from __future__ import annotations

import sys

from .app import build_runtime, seed_demo


def main() -> int:
    rt = build_runtime()
    version = rt["db"].migrate()
    print(f"[attendance] schema ready, version={version} "
          f"({'PG' if rt['db'].is_pg else 'sqlite'}) path={rt['db'].path_or_dsn()}")
    if "--seed" in sys.argv or "--seed-biometric" in sys.argv:
        seed_demo(rt["db"], with_biometric="--seed-biometric" in sys.argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())