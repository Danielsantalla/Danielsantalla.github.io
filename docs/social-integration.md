# Public social integration

Production uses GitHub Pages with API credentials only in Actions secrets. No tokens or imported API content belong in Git. Public snapshots are generated in the deployment artifact. `data/social-sources.json` maps nine tutorials to X posts and seven YouTube videos.

## YouTube

The normal Pages workflow refreshes YouTube weekly on Monday and performs cache-only deployments on other days. Source pushes and default manual deployments do not fetch either API. YouTube data expires after 14 days, below the API policy's 30 day refresh/delete limit. The interface displays public counts/comments directly, with initials instead of Google-hosted avatars and links to privacy and YouTube terms. No consent-state storage or social login is used.

## X: one authorized import

The owner authorized one import of comments and required author information, with a maximum of **USD 1.40** from existing credits. No recharge, subscription or recurring X refresh is authorized or implemented.

Run **Import X once and publish** manually on main with confirmation `x-import-2026-11-10`. Do not dispatch again if the outcome is uncertain. Before any paid request the script verifies the official prices, sufficient account credit and the exact nine source IDs, then creates the durable Git tag `x-import-2026-11-10-attempted`. Atomic tag creation blocks concurrent or repeated imports; workflow reruns are also blocked. Never delete/reset the marker to retry automatically.

The budget reserves nine original posts and at most ten replies plus ten expanded author profiles per conversation. Maximum:99 posts × $0.005 +90 profiles × $0.010 = **$1.395 USD**. This fits the owner's $1.40 limit. A changed price or source map fails closed before spending. Requests are rate-spaced, with no pagination, retries, separate user lookups, unrelated expansions or other write operations. The first failed/uncertain paid request stops the remaining paid requests; reserved cost is never refunded in the guard. Provider deduplication is not assumed.

Author expansions include only the profile ID, name, username and image required for attribution. Replies include text, publication date and display entities. Incomplete authors are omitted rather than invented. Imported data is rendered in the site's own layout, with linked avatar/name/username, unmodified text, linked date, source link and X branding. There are no embedded posts or X widget scripts. Profile images contact X's image servers, as disclosed in the privacy page.

The Actions summary records returned resources, estimated cost, optional observed credit difference and failures. It never prints account balances or secrets. Actual billing should be checked in the X console; a credit difference can include other concurrent activity or lag. An existing artifact can be deployed without repeating the API import if publication fails.

## Snapshot retention and removal

X is a dated one-time snapshot, not live data. It has **no arbitrary 14 day expiry** and is not renewed by scheduled YouTube refreshes. Source deployments reuse the original timestamp. No new comments are added automatically. API snapshots are not committed to public Git history; upload artifacts are retained for one day.

No fixed 14 day retention exemption exists in X's policy. The operator must make reasonable efforts to reflect edits, deletions, protected/suspended accounts and other removals promptly, and handle requests from X or an owner within 24 hours as required by the applicable terms. Historical metrics remain explicitly dated and must not be presented as current. This import does not promise zero-maintenance compliance or permanent availability.

To remove a known changed/deleted post, add its numeric ID to `post_ids` in `data/x-removals.json` and publish. A root ID removes its whole X entry; a reply ID removes that reply. `author_ids` removes cached replies by that author. Normal deployments apply these instructions without contacting X. Remove old deployed artifacts when required. If a new revision cannot be obtained within the authorized budget, remove the stale content rather than silently refetch it. Verify the published JSON after a removal.

X Batch Compliance can check existing IDs for changes without searching for new comments. It appears in this project's access/rate-limit list, but its fee was not confirmed by the console or public rate card, so **no compliance job, subscription or schedule is activated**. Additional monitoring or paid reads require an explicit decision. GitHub deployment delays and external caches can delay removal; the operator must follow up rather than treating a successful source commit as proof of removal.

## Validation and operation

Run `python -m unittest discover -s tests -v`, `node --check tweet-metrics.js`, `node tests/test_social_ui.cjs`, and `python scripts/build_site.py <empty-output-directory>`. Tests make no credentialed API calls. The standard refresher's `--refresh` flag affects YouTube only and never reads X, even when an X token is accidentally present.

The public build uses an explicit allowlist and excludes scripts, tests, docs, workflow files, Git metadata, secrets and legacy caches. Missing counts are omitted, not represented as zero. API errors and redirects never expose or forward credentials.

Sources checked November 10,2026:
- https://docs.x.com/x-api/getting-started/pricing
- https://docs.x.com/x-api/usage/get-usage-credits
- https://docs.x.com/developer-terms/display-requirements
- https://docs.x.com/developer-terms/policy
- https://docs.x.com/developer-terms/agreement
- https://docs.x.com/x-api/compliance/batch-compliance/integrate
