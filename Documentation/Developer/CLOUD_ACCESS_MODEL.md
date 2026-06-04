# Cloud Access Model

Planetka uses one technical cloud-access model. Installs are either `active` or `blocked` for service reliability and abuse protection.

Planetka product wording is Free and Pro. The current public add-on does not use runtime feature gates between Free and Pro: Preview, Balanced, Full Quality, clouds, export, panoramic camera support, and animation tools use the same cloud access path unless Planetka explicitly defines a Pro-only package or service.

Backend access controls exist for abuse prevention, service reliability, and blocking compromised or abusive installs. They are not quality-level gates in the current public add-on.

## Installation Editions

Free and Pro are installation editions, not user account tiers.

Each distributable package contains `Resources/planetka_edition.json`. The addon sends that package edition during anonymous session creation and refresh. Backend access and tile-session tokens carry:

- `install_edition`: `free` or `pro`
- `install_edition_label`: `Free` or `Pro`

This allows backend catalogue and data routes to offer different asset sets to Free and Pro installations without requiring email accounts or user login. For example, Pro can expose the full cloud catalogue while Free can expose a curated subset.

If `PLANETKA_EDITION_SIGNING_SECRET` is configured in the backend, Pro markers must include a valid hex HMAC-SHA256 signature. The signed message is:

`planetka-edition:v1:pro`

Without a valid signature, a requested Pro edition is treated as Free. Free markers do not need a signature.
