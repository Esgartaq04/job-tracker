import logging
import sys

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


def test_a_key_inside_a_non_string_arg_is_redacted():
    # An SDK exception passed as an arg: str() of it is what ends up in the line.
    r = record("failed: %s", RuntimeError("boom sk-ant-api03-SECRETSECRET"))
    assert redact.RedactKeys().filter(r) is True
    assert "SECRETSECRET" not in r.getMessage()
    assert "boom" in r.getMessage()


def test_a_key_inside_a_dict_arg_value_is_redacted():
    r = record("payload=%(body)s", {"body": {"key": "sk-ant-api03-SECRETSECRET"}})
    redact.RedactKeys().filter(r)
    assert "SECRETSECRET" not in r.getMessage()


def test_numeric_formatting_still_works():
    r = record("n=%d", 3)
    redact.RedactKeys().filter(r)
    assert r.getMessage() == "n=3"


def test_a_literal_percent_sign_survives_a_second_pass():
    # Handlers each run the filter, so it sees an already-redacted, already-formatted record.
    r = record("100%% of %s", "sk-ant-api03-SECRETSECRET")
    f = redact.RedactKeys()
    f.filter(r)
    f.filter(r)
    assert r.getMessage() == "100% of sk-ant-…redacted"


def test_a_record_that_cannot_be_formatted_is_left_alone():
    r = record("needs two: %s %s", "only one")
    assert redact.RedactKeys().filter(r) is True
    assert r.msg == "needs two: %s %s" and r.args == ("only one",)


def test_a_key_in_a_traceback_is_redacted():
    try:
        raise RuntimeError("boom sk-ant-api03-TRACESECRET")
    except RuntimeError:
        exc_info = sys.exc_info()
    r = logging.LogRecord("t", logging.ERROR, __file__, 1, "call failed", (), exc_info)
    assert redact.RedactKeys().filter(r) is True
    output = logging.Formatter("%(message)s").format(r)
    assert "TRACESECRET" not in output
    assert "RuntimeError" in output and "call failed" in output


def test_a_key_in_already_rendered_exception_text_is_redacted():
    r = record("call failed")
    r.exc_text = "RuntimeError: boom sk-ant-api03-TRACESECRET"
    redact.RedactKeys().filter(r)
    assert "TRACESECRET" not in logging.Formatter("%(message)s").format(r)


def test_a_key_in_stack_info_is_redacted():
    r = record("where am I")
    r.stack_info = "File x.py, line 1, in f(token='sk-ant-api03-STACKSECRET')"
    redact.RedactKeys().filter(r)
    assert "STACKSECRET" not in logging.Formatter("%(message)s").format(r)


def test_a_clean_record_keeps_its_args():
    r = record("%s and %s", "a", "b")
    redact.RedactKeys().filter(r)
    assert r.args == ("a", "b")


def test_uvicorn_access_lines_still_format():
    """uvicorn's AccessFormatter unpacks the record's five args itself, so a clean record
    must come out of the filter with them intact."""
    from uvicorn.logging import AccessFormatter

    r = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/healthz", "1.1", 200),
        None,
    )
    redact.RedactKeys().filter(r)
    formatter = AccessFormatter("%(request_line)s -> %(status_code)s", use_colors=False)
    assert formatter.format(r) == "GET /healthz HTTP/1.1 -> 200 OK"
