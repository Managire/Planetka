# Planetka Changelog Discipline

`CHANGELOG.md` is append-only release history for external users.

## Format

- Keep a single top-level `## [vX.Y.Z] - YYYY-MM-DD` section per release.
- Newest release at top.
- Use buckets:
  - `Added`
  - `Changed`
  - `Fixed`
  - `Known Issues` (optional)

## Rules

1. Every manifest version bump must have a matching changelog section.
2. Every section must contain user-impactful notes (not internal-only refactors unless they affect users).
3. Avoid vague entries such as "misc improvements".
4. If rollback risk exists, document it explicitly in that release section.
5. Do not rewrite past release notes after publish; add follow-up entries instead.

## Minimum Release Entry Quality

Each release entry should answer:

1. What changed for users?
2. What stability risk was addressed?
3. What compatibility limits exist?
4. Any required manual action after update?
