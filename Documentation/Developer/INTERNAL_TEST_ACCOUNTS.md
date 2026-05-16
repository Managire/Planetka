# Planetka Internal Test Accounts

This document is for internal testing only. It must not be shipped in the public addon package and must not be copied into user-facing docs.

## Source of Truth

Use this external file as the canonical source for internal test accounts and live API keys:

`/Users/tomasgriger/Library/Mobile Documents/com~apple~CloudDocs/Planetka APIs.rtf`

Do not duplicate live API keys into this repository.

## Approved Internal Accounts

Use purpose-specific accounts rather than account tiers. The current important accounts are:

- `free@planetka.io`: general authenticated beta workflow checks.
- `tom.griger@gmail.com`: purchase-testing account. This account is excluded from beta world-access grants so real purchase and pricing flows can be tested.

Do not create ad-hoc temporary test users unless explicitly required for a one-off scenario. If temporary users are created, remove them after the test.

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

## Handling Rules

- Treat the external RTF file as sensitive internal operational material.
- Do not paste live API keys into commits, issues, public docs, changelogs, or release artifacts.
- Do not include this credentials source in public `.zip` packages.
