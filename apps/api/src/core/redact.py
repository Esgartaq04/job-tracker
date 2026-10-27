"""Keep Claude API keys out of the logs.

A key reaches the process only for the length of a request, but SDK errors, HTTP client
debug lines and tracebacks have a way of echoing whatever they were given. This filter
is the backstop: anything shaped like a Claude key is replaced before a handler sees it.
"""

import logging
import re

KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_REDACTED = "sk-ant-…redacted"

# uvicorn and arq give their loggers their own handlers, so root alone doesn't cover them.
# arq's child loggers (`arq.worker` logs failed jobs, exception included) propagate to the
# handler on `arq`.
_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "arq")


def _scrub(text: str) -> str:
    return KEY_PATTERN.sub(_REDACTED, text)


class RedactKeys(logging.Filter):
    """Redacts the record as it will be rendered, not its parts: a key can hide in the
    `str()` of an exception or object passed as an arg, in a traceback, or in stack info."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            pass  # a malformed log call; leave it for the handler to report
        else:
            if KEY_PATTERN.search(message):
                # Freeze the rendered text so the args, and whatever their str() says, are
                # gone. Only done on a hit: uvicorn's access formatter unpacks the args
                # itself, so clean records have to keep them.
                record.msg = _scrub(message)
                record.args = ()
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None  # so formatters use exc_text, not a fresh raw traceback
        if record.exc_text:
            record.exc_text = _scrub(record.exc_text)
        if record.stack_info:
            record.stack_info = _scrub(record.stack_info)
        return True


def install() -> None:
    """Attach the filter to every handler once. Filters on a logger don't see records
    from its children, so it has to sit on the handlers."""
    for name in _LOGGERS:
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(f, RedactKeys) for f in handler.filters):
                handler.addFilter(RedactKeys())
