"""Logging setup. Never log tokens, Authorization headers or DB URLs."""
from __future__ import annotations

import logging
import re

_SECRET = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+|(password|secret|token)=\S+", re.I)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET.sub(lambda m: (m.group(1) or m.group(2) + "=") + "[REDACTED]", str(record.msg))
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for h in root.handlers:
        h.addFilter(RedactFilter())
