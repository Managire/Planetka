# Planetka Hardening Backlog

## Priority Items

1. Replace silent exception-swallowing (`except ...: pass`) in critical runtime paths with structured warnings/errors.
- Scope: especially animation/segmenting and render-prep paths where silent failures can hide incorrect output.
- Goal: no silent failure in core production workflows.
