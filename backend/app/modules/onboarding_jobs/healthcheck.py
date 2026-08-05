from __future__ import annotations

import argparse
import os
from pathlib import Path
import time


DEFAULT_HEARTBEAT_PATH = Path(
    os.getenv(
        "ONBOARDING_WORKER_HEARTBEAT_PATH",
        "/tmp/blackpenguin-onboarding-worker.heartbeat",
    )
)


def write_heartbeat(path: Path = DEFAULT_HEARTBEAT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(str(time.time()), encoding="utf-8")
    temporary.replace(path)


def is_heartbeat_fresh(
    path: Path = DEFAULT_HEARTBEAT_PATH,
    *,
    max_age_seconds: float = 180.0,
    now: float | None = None,
) -> bool:
    try:
        modified_at = path.stat().st_mtime
    except OSError:
        return False
    reference = time.time() if now is None else now
    age = reference - modified_at
    return 0 <= age <= max_age_seconds


def main() -> None:
    parser = argparse.ArgumentParser(description="Check onboarding worker heartbeat freshness.")
    parser.add_argument("--max-age-seconds", type=float, default=180.0)
    args = parser.parse_args()
    raise SystemExit(
        0 if is_heartbeat_fresh(max_age_seconds=args.max_age_seconds) else 1
    )


if __name__ == "__main__":
    main()
