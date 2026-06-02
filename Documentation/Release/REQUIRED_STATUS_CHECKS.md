# Required Status Checks

Use this file when configuring release or branch-protection checks.

Recommended required checks:

- Python syntax/import checks for the add-on modules.
- Cloudflare Worker syntax/build checks.
- Bounded Blender smoke test for Create Earth and all quality levels.
- Resolve stability test covering manual resolve, cloud LOD updates, and long-open scene behaviour.
- Public-review wording audit confirming no obsolete feature-gate, purchase-flow, or automatic data-refresh terminology remains in runtime code.

Stress and abuse tests should not be required branch-protection checks because they may intentionally load production services.
