"""A windowed-app crash must leave a redacted, local breadcrumb (crashlog)."""

from __future__ import annotations

from ghostcursor.workspace import crashlog


def test_write_crash_is_local_redacted_and_keeps_the_error(tmp_path, monkeypatch):
    monkeypatch.setattr(crashlog, "_log_dir", lambda: tmp_path)
    try:
        raise ValueError("boom key sk-ABCDEFGHIJKLMNOP1234 mail a@b.com")
    except ValueError as exc:
        path = crashlog.write_crash(exc)

    assert path.exists() and path.parent == tmp_path
    body = path.read_text(encoding="utf-8")
    assert "ValueError" in body and "boom" in body  # the error is legible
    assert "sk-ABCDEFGHIJKLMNOP1234" not in body  # secret masked before writing
    assert "a@b.com" not in body


def test_report_never_raises_even_if_the_log_cannot_be_written(monkeypatch):
    # a crash handler must never crash: an unwritable log dir returns None, not
    # a second exception.
    def _boom():
        raise OSError("read-only")

    monkeypatch.setattr(
        crashlog, "write_crash", lambda exc: (_ for _ in ()).throw(OSError())
    )
    assert crashlog.report(ValueError("x")) is None
