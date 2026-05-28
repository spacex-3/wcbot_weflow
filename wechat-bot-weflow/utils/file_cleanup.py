import os
import time
from typing import Iterable


def cleanup_old_files(
    directory: str,
    retention_days: int = 7,
    allowed_extensions: Iterable[str] | None = None,
    now: float | None = None,
) -> dict[str, int]:
    if not directory or not os.path.isdir(directory):
        return {"removed": 0, "failed": 0}

    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        days = 7
    if days <= 0:
        return {"removed": 0, "failed": 0}

    normalized_extensions = None
    if allowed_extensions is not None:
        normalized_extensions = {ext.lower() for ext in allowed_extensions}

    cutoff = (time.time() if now is None else now) - days * 24 * 60 * 60
    removed = 0
    failed = 0

    for root, _, files in os.walk(directory):
        for filename in files:
            path = os.path.join(root, filename)
            extension = os.path.splitext(filename)[1].lower()
            if normalized_extensions is not None and extension not in normalized_extensions:
                continue
            try:
                if os.path.getmtime(path) >= cutoff:
                    continue
                os.remove(path)
                removed += 1
            except OSError:
                failed += 1

    return {"removed": removed, "failed": failed}
