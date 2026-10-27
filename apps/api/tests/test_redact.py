import logging

from src.core import redact


def record(msg, *args):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_a_key_in_the_message_is_redacted():
    r = record("calling with sk-ant-api03-AbC_123-xyz now")
    assert redact.RedactKeys().filter(r) is True
    assert "AbC_123" not in r.getMessage() and "sk-ant-…redacted" in r.getMessage()


def test_a_key_in_the_args_is_redacted():
    r = record("key=%s", "sk-ant-api03-SECRETSECRET")
    redact.RedactKeys().filter(r)
    assert "SECRETSECRET" not in r.getMessage()


def test_install_puts_the_filter_on_root_handlers():
    redact.install()
    assert any(
        isinstance(f, redact.RedactKeys) for h in logging.getLogger().handlers for f in h.filters
    )


def test_install_is_idempotent():
    redact.install()
    redact.install()
    for h in logging.getLogger().handlers:
        assert sum(isinstance(f, redact.RedactKeys) for f in h.filters) <= 1
