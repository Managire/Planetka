# Required Status Checks

Use this file when configuring release or branch-protection checks.

Recommended required checks:

- Python syntax/import checks for the add-on modules.
- Cloudflare Worker syntax/build checks.
- Bounded Blender smoke test for Create Earth and all quality levels.
- Resolve stability test covering manual resolve, resolve, cloud LOD updates, and long-open scene behaviour.
- Licence wording audit confirming Personal / Commercial naming and no obsolete feature-gate wording.

Stress and abuse tests should not be required branch-protection checks because they may intentionally load production services.
