# Apartment Hunter

Read README.md and docs/superpowers/specs/2026-09-25-apartment-hunter-design.md before editing.

- Never solve, click, or hide from a human check (PerimeterX "Press & Hold"). Bring the tab to the front and wait for the user.
- Never send custom requests to StreetEasy or Zillow. Read only embedded page data and the page's own responses (passive capture).
- Keep page loads few: one per site per search by default, at least 20 seconds apart on one site. Do not lower the minimum pauses in `criteria.SAFETY_BOUNDS`.
- No login, no background searches, no stealth changes (user agent, fingerprint, cookie resets, proxies).
- Jev is text only. The vision model describes photos; Jev judges; code combines scores with the user's weights.
- Reject invalid model output. Never guess a value.
- Tests must not call paid APIs or listing sites. Live checks use local pages (`scripts/browser_check.py`).
- Keep credentials in `.env` (git-ignored) and on the server side.
- Do not commit or push unless the user asks.

Checks: uv run ruff check ., uv run pytest, node --check apartment_hunter/static/app.js.
