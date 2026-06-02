# Cloud API Environment Variables

The current add-on uses anonymous install sessions and short-lived tile session tokens. It does not prompt for API keys, email addresses, or cloud activation inside Blender.

Operational user status values:

- `active` - Planetka Cloud access is allowed.
- `blocked` - Planetka Cloud access is denied by admin action or abuse protection.

Feature availability is not decided by account class in runtime code.
