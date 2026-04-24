# Stable Release: Preview + Full Quality Credits

Date: 2026-03-29  
Status: Stable

## Model

- One functional addon tier for all users (personal + commercial use).
- Preview quality: free.
- Full Quality: consumes credits for newly downloaded data.
- Starter credits: `25 GB` per new account.
- Top-ups: Stripe checkout grants additional credits by mapped package size.
- Credits do not expire.

## Product/UI

- Quality selector moved to **Status Check**:
  - `Preview`
  - `Full Quality`
- Quarter quality removed.
- Status shows:
  - current available credits
  - estimated `Cost in Full resolution` while in Preview mode
- Animation prepare dialog shows:
  - visible Preview warning (potential flicker/tile transitions)
  - estimated `Cost of animation in Full Quality`
- Account panel actions:
  - `Connect API Key`
  - `Request API Key`
  - `Top Up Credits`

## Worker/API

- Public `/auth/api-key/request` is always base access.
- Stripe webhook (`checkout.session.completed`) grants credits, not plan elevation.
- Tile charging is controlled by request header:
  - `X-Planetka-Quality-Mode: preview` => no charge
  - `X-Planetka-Quality-Mode: full` => charge by served bytes
- `allowance_exhausted` (`402`) is returned only for Full Quality when credits are depleted.

## Validation

- Python compile checks: pass.
- Worker syntax check: pass.
- Release gate: pass.
