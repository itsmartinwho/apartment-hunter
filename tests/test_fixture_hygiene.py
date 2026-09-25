"""Captured public pages can contain third-party keys. Never publish those in fixtures."""

from scripts.sanitize_fixtures import FIXTURES, PATTERNS, redact


def test_fixtures_do_not_contain_credentials():
    findings = []
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for label, pattern in PATTERNS.items():
                if pattern.search(data):
                    findings.append(f"{path.name}: {label}")
    # Never include matching values in pytest output.
    assert not findings, "Run scripts/sanitize_fixtures.py before committing: " + ", ".join(findings)


def test_redaction_preserves_flight_record_lengths():
    example = b'apiKey="' + b"AI" + b"za" + b"x" * 35 + b'"'
    cleaned, count = redact(example)
    assert count == 1
    assert len(cleaned) == len(example)
    assert cleaned.startswith(b'apiKey="REDACTED')
    assert redact(cleaned) == (cleaned, 0)
