"""Remove credential-shaped strings from captured fixtures without logging them.

Run before committing new captures: uv run python scripts/sanitize_fixtures.py
Replacements preserve byte lengths because Next.js Flight can contain length-prefixed text records.
"""

import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
PATTERNS = {
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "OpenRouter API key": re.compile(rb"sk-or-v1-[0-9a-fA-F]{32,}"),
    "GitHub token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def redact(data):
    count = 0
    for pattern in PATTERNS.values():
        data, found = pattern.subn(lambda match: b"REDACTED".ljust(len(match[0]), b"_"), data)
        count += found
    return data, count


def main():
    for path in sorted(FIXTURES.rglob("*")):
        if path.is_file():
            original = path.read_bytes()
            clean, count = redact(original)
            if count:
                path.write_bytes(clean)
                print(f"{path.relative_to(FIXTURES.parent.parent)}: redacted {count} credential-shaped values")


if __name__ == "__main__":
    main()
