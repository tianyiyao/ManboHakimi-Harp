"""Best-effort console output for Windows code pages and windowed builds."""
from __future__ import annotations

import sys


def safe_print(message: object) -> None:
    """Never let a diagnostic message interrupt a user action."""
    stream = sys.stdout
    if stream is None:
        return
    text = str(message)
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        escaped = text.encode(encoding, errors="backslashreplace").decode(encoding)
        try:
            print(escaped, file=stream)
        except (OSError, UnicodeError, ValueError):
            pass
    except (OSError, ValueError):
        pass
