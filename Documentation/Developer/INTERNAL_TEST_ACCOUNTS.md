# Internal Test Access

Use purpose-specific test identities for admin, abuse-control, and data-streaming checks. The add-on does not use runtime account classs for feature access.

Recommended identities:

- `tom.griger@gmail.com`: owner/admin workflow checks.
- `qa@planetka.io`: non-owner workflow checks.

Tests should focus on anonymous session creation, token refresh, admin block/unblock, analytics labelling, and data-streaming reliability.
