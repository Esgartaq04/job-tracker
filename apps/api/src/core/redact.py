"""Keep Claude API keys out of the logs.

A key reaches the process only for the length of a request, but SDK errors, HTTP client
debug lines and tracebacks have a way of echoing whatever they were given. This filter
is the backstop: anything shaped like a Claude key is replaced before a handler sees it.
"""

import logging
import re

KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_REDACTED = "sk-ant-…redacted"

# uvicorn gives its loggers their own handlers, so root alone doesn't cover them.
_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


def _scrub(value):
    return KEY_PATTERN.sub(_REDACTED, value) if isinstance(value, str) else value


class RedactKeys(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _scrub(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_scrub(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _scrub(arg) for key, arg in record.args.items()}
        return True


def install() -> None:
    """Attach the filter to every handler once. Filters on a logger don't see records
    from its children, so it has to sit on the handlers."""
    for name in _LOGGERS:
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactKeys) for f in handler.filters):
                handler.addFilter(RedactKeys())
