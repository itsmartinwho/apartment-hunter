"""The fixtures are synthetic pages. Real captures carry third-party keys, visitor ids and the sites' content."""

import re

from scripts.build_sample_fixtures import build
from scripts.sanitize_fixtures import FIXTURES, PATTERNS, redact

# The generated pages, plus the MTA's open station list that scripts/build_data.py reads.
ALLOWED = {"streeteasy_search_flight.txt", "zillow_search_next_data.json", "mta_stations.csv"}
IDENTIFIERS = {
    "URL": re.compile(r"https?://|www\."),
    "e-mail address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone number": re.compile(r"(?<![\d.])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),
    "UUID": re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I),
}


def test_fixtures_are_only_the_synthetic_pages_and_open_data():
    # A raw capture dropped in here fails the test; scripts/build_sample_fixtures.py makes the pages.
    assert {path.name for path in FIXTURES.iterdir()} == ALLOWED


def test_pages_are_what_the_generator_writes():
    for name, text in build().items():
        assert (FIXTURES / name).read_text(encoding="utf-8") == text, f"Run scripts/build_sample_fixtures.py: {name}"


def test_pages_carry_no_urls_contacts_or_visitor_ids():
    findings = []
    for name in build():
        text = (FIXTURES / name).read_text(encoding="utf-8")
        findings += [f"{name}: {label}" for label, pattern in IDENTIFIERS.items() if pattern.search(text)]
    # Never include matching values in pytest output.
    assert not findings, ", ".join(findings)


def test_fixtures_do_not_contain_credentials():
    findings = []
    for path in FIXTURES.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            for label, pattern in PATTERNS.items():
                if pattern.search(data):
                    findings.append(f"{path.name}: {label}")
    # Never include matching values in pytest output.
    assert not findings, "Fixtures must not hold credential-shaped strings: " + ", ".join(findings)


def test_redaction_preserves_flight_record_lengths():
    example = b'apiKey="' + b"AI" + b"za" + b"x" * 35 + b'"'
    cleaned, count = redact(example)
    assert count == 1
    assert len(cleaned) == len(example)
    assert cleaned.startswith(b'apiKey="REDACTED')
    assert redact(cleaned) == (cleaned, 0)
