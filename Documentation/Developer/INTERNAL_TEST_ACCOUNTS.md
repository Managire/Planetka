# Planetka Internal Test Accounts

This document is for internal testing only. It must not be shipped in the public addon package and must not be copied into user-facing docs.

## Source of Truth

Use this external file as the canonical source for internal test accounts and live API keys:

`/Users/tomasgriger/Library/Mobile Documents/com~apple~CloudDocs/Planetka APIs.rtf`

Do not duplicate live API keys into this repository.

## Approved Internal Accounts

Only use these three internal accounts for addon, backend, stress, and entitlement tests:

- `free@planetka.io`
- `personal@planetka.io`
- `commercial@planetka.io`

Do not create ad-hoc temporary test users unless explicitly required for a one-off scenario. If temporary users are ever created, they should be removed after the test.

## Intended Use

- `free@planetka.io`
  Use for tier gating, disabled-quality checks, and free-tier UX validation.
- `personal@planetka.io`
  Use for historical personal-tier gating and upgrade-path validation.
- `commercial@planetka.io`
  Use for full-quality still renders, final animation renders, stress tests, and backend soak tests.

## Loading Keys For Existing Tools

Some internal scripts expect derived local files such as:

- `/tmp/planetka_api_key.txt`
- `/tmp/planetka_test_accounts_keys.json`

Generate those derived files from the RTF source rather than storing credentials in the repo.

Example conversion to plain text:

```bash
textutil -convert txt -stdout \
  "/Users/tomasgriger/Library/Mobile Documents/com~apple~CloudDocs/Planetka APIs.rtf"
```

Example derived JSON for tier E2E scripts:

```json
{
  "free@planetka.io": {"plan": "free", "api_key": "pka_..."},
  "personal@planetka.io": {"plan": "personal", "api_key": "pka_..."},
  "commercial@planetka.io": {"plan": "commercial", "api_key": "pka_..."}
}
```

## Handling Rules

- Treat the external RTF file as sensitive internal operational material.
- Do not paste live API keys into commits, issues, public docs, changelogs, or release artifacts.
- Do not include this credentials source in public `.zip` packages.
- When running unattended tests, prefer the account that matches the scenario instead of reusing Commercial for everything.
