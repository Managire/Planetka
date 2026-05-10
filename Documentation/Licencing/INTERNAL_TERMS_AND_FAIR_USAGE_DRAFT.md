# Planetka Internal Terms and Fair Usage Draft

Status: Internal draft for legal review only
Last updated: 2026-05-06
Owner: Planetka
Public status: Do not publish before legal review

This document is a working internal draft for Planetka's future Terms of Service,
Full Quality data licence terms, Preview fair usage policy, and related UI
wording. It is written for review with a lawyer and is not legal advice.

This draft is original Planetka wording. It follows common map-service policy
patterns, but it should not copy wording from Mapbox or any other provider.

## 1. Business Model Assumptions

This draft assumes the newer Planetka model:

- There are no Free, Personal, Commercial, Pro, Unlimited, or Unrestricted account plans.
- Each account may hold Full Quality tile entitlements purchased through direct payment.
- Preview Quality is free for normal interactive use inside Planetka.
- Full Quality data is paid/licenced by tile.
- A user pays only for newly licenced Full Quality tiles.
- Once a Full Quality tile is licenced by a user, that user may download it again without paying again.
- Reusing the same licenced tile in another Planetka scene does not create a new charge.
- Paid Full Quality usage is separate from free Preview usage.
- Preview usage may be monitored and limited to prevent source-data scraping.
- Paid/licenced Full Quality downloads are not subject to Preview fair-usage limits, but remain subject to fraud, security, and anti-circumvention rules.

## 2. Core Terms Summary

Planetka provides a Blender add-on and hosted Earth texture delivery service.
The add-on code may be governed by a separate open-source licence. Account
access, hosted services, Preview streaming, paid Full Quality data access,
payments, telemetry, and abuse prevention are governed by Planetka service
terms.

Users may use Planetka to create still images, animations, 3D scenes, and other
creative outputs, subject to these terms and the underlying third-party data
attribution requirements.

## 3. Definitions

Suggested definitions for lawyer review:

- **Planetka** means the Planetka add-on, Planetka account system, Planetka cloud services, Planetka-hosted data delivery, and related websites or APIs.
- **Preview Quality** means free lower-resolution or reduced-detail data made available for interactive exploration, layout, testing, and preview rendering inside Planetka.
- **Full Quality** means paid higher-detail Earth texture data made available after the relevant tile licence has been purchased or otherwise granted.
- **Licenced Tile** means a Full Quality tile that has been unlocked for a specific user account through direct payment, free grant, admin grant, or other Planetka-approved entitlement.
- **Source Data** means texture files, tile files, masks, metadata, elevation data, and other data files delivered by Planetka services.
- **Rendered Output** means images, videos, animations, screenshots, and similar creative outputs rendered by the user from a Planetka scene.
- **Dataset Reconstruction** means using Planetka to build, mirror, scrape, harvest, or systematically collect Planetka source data outside normal creative use.
- **Automated Access** means scripted, bot-driven, bulk, repeated, or non-interactive requests outside normal use of the Planetka add-on.

## 4. Intended Use

Planetka is intended for normal creative workflows, including:

- interactive location search and scene setup in Blender;
- resolving Preview Quality data while designing a scene;
- licencing and downloading Full Quality tiles needed for still renders and animations;
- rendering still images and animation sequences;
- storing licenced Full Quality tiles locally for reuse by the same licenced user;
- creating commercial or non-commercial rendered outputs, subject to the applicable licence and attribution requirements.

Planetka is not intended to be used as a general-purpose map API, GIS data
extraction service, bulk imagery downloader, scraping tool, or dataset delivery
backend.

## 5. Preview Quality Terms

Preview Quality is provided free of charge for normal interactive use inside the
Planetka add-on.

Users may use Preview Quality to explore locations, build scenes, test camera
angles, create quick previews, and decide whether to licence Full Quality data.

Preview Quality does not grant rights to extract, mirror, redistribute, resell,
train from, archive at scale, or reconstruct the underlying Planetka data.

Preview cache files are temporary operational cache only. They exist to make the
add-on responsive and reduce repeated downloads during normal work. They must not
be treated as a licenced source dataset.

## 6. Full Quality Tile Licence Terms

When a user licences a Full Quality tile, Planetka grants that user a right to
access and re-download that tile through Planetka according to the applicable
licence.

Recommended default licence position for lawyer review:

- The user may store licenced Full Quality tiles locally.
- The user may reuse licenced Full Quality tiles in Planetka scenes without paying again.
- The user may use licenced Full Quality tiles in their own creative 3D/rendering workflows, including still images, animations, VFX shots, environment art, and client deliverables.
- The user may archive licenced Full Quality tiles for their own future use.
- The user may not resell, redistribute, publish, mirror, sublicense, or provide raw Full Quality tile files as a standalone dataset, texture pack, API, downloadable asset library, or competing service.
- The user may not share raw Full Quality tile files with third parties except where necessary for a specific production workflow under the user's responsibility, and only if those third parties do not retain or reuse the raw files outside that project.
- The user may not use licenced Full Quality data to reconstruct a Planetka-like dataset or competing Earth texture delivery service.

Point for lawyer review: decide how broad the user's rights should be for raw
Full Quality texture files outside Blender. The business model suggests allowing
reasonable production use outside Blender, but not allowing redistribution of raw
source tiles or creation of a competing source-data product.

## 7. Rendered Outputs

Users retain rights in their own rendered outputs, subject to third-party source
attribution and any restrictions required by the underlying data licences.

Planetka should not claim ownership of user-created rendered stills, animations,
composites, or client deliverables solely because Planetka was used.

Users are responsible for including required third-party source attribution when
publishing rendered outputs, where attribution is required.

Recommended Planetka credit wording:

- Planetka credit is encouraged, for example: "Created with Planetka for Blender".
- Planetka credit may be optional unless a specific licence or promotion requires it.
- Third-party data attribution may be mandatory and should be documented separately.

## 8. Prohibited Use

Users must not:

- scrape, mirror, harvest, or systematically download Planetka Source Data;
- perform bulk or automated requests intended to collect map content or texture files;
- use Preview Quality to build a local or remote source-data archive;
- use Planetka as a generic API or backend data service outside the add-on's intended workflow;
- bypass, disable, circumvent, or interfere with authentication, API keys, tile-session tokens, licence checks, pricing checks, fair-usage checks, request limits, monitoring, caching controls, or entitlement controls;
- share account credentials or API keys outside the normal single-user account model;
- use multiple accounts, scripts, proxies, VPN rotation, token rotation, or other techniques to avoid Preview usage monitoring;
- redistribute raw Preview files, raw Full Quality tile files, masks, metadata, or other Planetka Source Data as a dataset or asset pack;
- reverse engineer, scrape, or automate the add-on or service to extract Source Data;
- stress, probe, overload, interfere with, or degrade Planetka services;
- use Planetka data for AI/ML training, dataset creation, benchmarking, validation, model evaluation, or similar workflows unless Planetka grants a separate written licence for that use;
- remove, obscure, or misrepresent required source-data attribution.

## 9. Fair Usage Policy for Preview Quality

Preview Quality is free, but it is not unlimited for scraping or bulk download.
Planetka may monitor Preview usage to protect the service and underlying data.

Planetka may look at operational signals such as:

- Preview tile request volume;
- Preview bytes served;
- number of unique Preview tiles requested;
- repeated access to high-value Preview levels;
- unusual request timing;
- scripted or bot-like request patterns;
- account age;
- payment history;
- IP-derived abuse indicators;
- failed authentication or entitlement checks;
- attempts to use Preview outside normal add-on workflows.

Suggested internal enforcement threshold direction:

- The system may alert Planetka when Preview usage exceeds internal review thresholds.
- Initial rollout should use alerts only until real usage patterns are understood.
- Later, Planetka may automatically pause Preview streaming for accounts that exceed fair-use thresholds or show scraping-like behavior.

Suggested public wording:

> Preview Quality is intended for normal interactive use inside Planetka. If Preview usage appears automated, excessive, abusive, or inconsistent with normal creative use, Planetka may temporarily pause Preview streaming for review.

## 10. Preview Hold

Planetka may place an account on Preview Hold if the account appears to exceed
fair usage limits or shows signs of scraping, automation, abuse, or attempted
dataset reconstruction.

Preview Hold should:

- block Preview tile-session creation;
- block Preview tile delivery immediately, even for previously issued tile-session tokens;
- keep account login available where appropriate;
- keep paid/licenced Full Quality access available where appropriate;
- show the user a gentle UI notice;
- be reviewable and releasable by Planetka through Analytics/admin tools.

Suggested UI wording:

> Preview streaming is paused for review.
>
> Full Quality licenced data remains available.
>
> If you believe this is unexpected, contact Planetka support.

## 11. Hard Account Block

A hard account block is separate from Preview Hold.

Preview Hold is for protecting free Preview streaming and reviewing unusual
usage. A hard account block is for serious cases such as fraud, payment abuse,
chargebacks, credential theft, account sharing abuse, security attacks,
circumvention, service interference, or deliberate data scraping.

A hard block may restrict login, API access, tile delivery, payments, downloads,
or other services.

Suggested wording:

> Planetka may suspend, restrict, or disable access immediately where needed to protect the service, prevent abuse, respond to fraud or security concerns, or prevent unauthorized extraction of Planetka Source Data.

## 12. No Advance Notice for Protective Action

Planetka may take immediate protective action without advance notice where delay
could risk service stability, security, payment integrity, or unauthorized data
extraction.

Suggested wording:

> Where Planetka reasonably believes that immediate action is necessary to protect the service, users, payment integrity, or Source Data, Planetka may restrict, pause, suspend, or disable access without advance notice.

## 13. Caching and Local Storage

Preview caching:

- allowed only as operational cache used by the add-on;
- not a licence to extract or retain a source dataset;
- may be cleared, invalidated, limited, or changed by Planetka at any time;
- may not be redistributed or used outside the intended Preview workflow.

Full Quality local storage:

- allowed for tiles licenced by the user's account;
- may be used as a local source to avoid repeated downloads;
- may be re-downloaded by the user where Planetka offers download tools;
- should remain subject to the raw-data redistribution restrictions in Section 6.

If Planetka updates a tile, the user may be allowed to re-download the updated
version without paying again for the same licenced tile.

## 14. Payments and Tile Licencing

Suggested terms:

- Users licence Full Quality tiles through direct checkout payment.
- A user may pay the exact current scene price or the current data-pack price through a checkout flow where available.
- Planetka calculates the tile price based on Planetka's pricing system and backend records.
- The client UI may display estimates or pre-check calculations, but backend records determine the final licence transaction.
- Once a tile is licenced, repeat use of that exact entitlement does not create a new charge.
- If a user later licences a higher-detail version of a previously licenced lower-detail tile, Planetka may charge only the price difference where that rule is supported.
- Some tiles may be free under Planetka's pricing rules.
- Planetka may correct pricing, entitlement, or accounting errors where necessary.

Point for lawyer/accounting review: define refund policy for exact-scene
payments, data-pack payments, failed downloads, accidental purchases, and chargebacks.

## 15. Monitoring and Telemetry

Planetka may collect and process operational telemetry needed to operate,
secure, price, bill, monitor, and improve the service.

Telemetry may include:

- account ID and email;
- API key/session identifiers;
- tile keys requested;
- quality mode, such as Preview or Full Quality;
- bytes served;
- request status codes;
- request timestamps;
- coarse IP-derived abuse signals;
- entitlement checks;
- checkout, payment, and tile-licence events;
- checkout and payment status events;
- add-on version and compatibility details;
- error and performance diagnostics.

Suggested wording:

> Planetka uses telemetry to operate the service, calculate paid Full Quality access, protect Preview data, investigate errors, prevent abuse, and maintain service reliability.

This should be cross-checked with the Privacy Policy and GDPR obligations.

## 16. AI and Machine Learning Restriction

Recommended default position:

Planetka Source Data, Preview data, Full Quality tile files, masks, metadata,
and rendered outputs where Planetka Source Data is a material input may not be
used to train, fine-tune, validate, benchmark, evaluate, or create datasets for
AI, machine learning, computer vision, generative, or similar systems without a
separate written licence from Planetka.

Point for lawyer review: rendered outputs restriction may be too broad or hard
to enforce. Decide whether to restrict only raw/source data or also rendered
outputs derived from Planetka data.

## 17. Service Availability and Changes

Planetka may change technical limits, Preview thresholds, pricing rules,
entitlement logic, data sources, cache behavior, and service architecture over
time.

Planetka should reserve the right to:

- update Preview and Full Quality delivery systems;
- replace or update source textures;
- change fair-usage thresholds;
- change pricing for future tile licences;
- correct errors in payments, pricing, or tile entitlements;
- discontinue beta or test features;
- require add-on updates for continued cloud-service access.

## 18. Suggested UI Wording

Account panel Preview Hold notice:

> Preview streaming is paused for review.
> Full Quality licenced data remains available.

Data Control paid button:

> Full Quality Textures (€X.XX)

Animation confirmation:

> New tiles to be downloaded/licenced: N
> Price: €X.XX
> By continuing, these Full Quality tiles will be licenced to your account and downloaded before rendering starts.

Fair-usage warning email/admin alert:

> Preview usage review threshold reached.
> Account: {email}
> Preview data served: {gb} GB
> Unique Preview tiles: {count}
> No automatic block was applied.

Manual Preview Hold admin action label:

> Pause Preview Streaming

Manual Preview Hold release label:

> Release Preview Hold

## 19. Lawyer Review Questions

Ask the lawyer specifically:

1. What exact rights should users receive for raw Full Quality tile files?
2. Can users use licenced Full Quality tiles outside Blender in other 3D/VFX tools?
3. Can users share raw files with contractors working on the same project?
4. Should raw tile redistribution be completely prohibited?
5. Should AI/ML restrictions apply to rendered outputs, raw data only, or both?
6. How should refunds work for exact-scene payments and data-pack payments?
7. Is immediate Preview Hold without notice acceptable under applicable consumer and platform laws?
8. What telemetry wording is required for GDPR/privacy compliance?
9. Should Preview cache restrictions be in Terms, Fair Usage Policy, EULA, or all three?
10. Should public Terms distinguish account suspension from temporary Preview streaming review?
11. Are there mandatory consumer-law disclosures for digital data access and direct checkout payments?
12. Should licenced tile access survive account closure, refund, chargeback, or Terms breach?

## 20. Public Document Split Recommendation

Recommended public documents after legal review:

- Terms of Service: account, service, payment, enforcement, source-data rules.
- Fair Usage Policy: Preview-specific usage limits, monitoring, Preview Hold.
- Full Quality Data Licence: what licenced tiles allow and prohibit.
- Privacy Policy: telemetry, account data, payment metadata, analytics.
- Attribution Guide: required source attribution for rendered outputs.

Do not publish this internal draft directly. Convert it into clean public-facing
documents after legal review.
