from __future__ import annotations

from typing import Callable, Optional

# on_progress(message, step_id)
ProgressCallback = Callable[[str, str], None]


def report(cb: Optional[ProgressCallback], message: str, step: str = "") -> None:
    if cb is None:
        return
    try:
        cb(message, step)
    except Exception:
        pass
