# Public social integration

The website publishes a same-origin `/data/social.json` artifact. No credentials or downloaded API data belong in Git. The only committed data file for the integration is `data/social-sources.json`, an explicit map of nine existing tutorial posts and seven linked YouTube videos. Missing counts are omitted, never represented as zero. Sources remain independent.

## Activation status

This change is prepared for a draft pull request only. Production deployment and paid X reads are not activated. Do not merge or change the Pages source until credential, billing, and live-data checks are complete. An initial credit top-up does not automatically enable recurring API reads.

## Setup and operation

1. In repository Settings → Pages, choose **GitHub Actions** as the build source. The workflow deploys the custom-domain site with `CNAME` preserved.
2. Store `YOUTUBE_API_KEY` and `X_TOKEN` in repository Actions secrets, not variables, files, browser JavaScript or workflow inputs. Restrict the Google key to YouTube Data API v3 in its Google Cloud project. A static GitHub-hosted runner IP restriction is unsuitable.
3. X reads stay disabled unless repository Actions variable `X_ENABLED` is exactly `true` (case-insensitive). Leave unset or false until the owner approves the applicable paid X API budget and enables access. A token alone does not enable spending. X API full-archive search entitlement is required for these older posts.
4. Run **Publish site and refresh social data** manually with **Refresh APIs** checked after approved credential setup. Default manual runs and source pushes only reuse the current public cache and perform no YouTube/X API reads.
5. Weekly API refresh runs Monday at 06:23 UTC. Tuesday through Sunday at the same time, cache-only deployments remove expired data without API reads. GitHub scheduled runs may be delayed and public-repository schedules can become disabled after 60 days without repository activity. Check Actions if updates stop. Scheduling is not a guaranteed SLA.

A refresh performs one YouTube `videos.list` batch and at most seven `commentThreads.list` requests, with the latest 20 top-level comments per video, plain text, without reply expansion or pagination. It performs one X `/2/tweets` batch and at most nine `/2/tweets/search/all` calls with `conversation_id:ID is:reply -is:retweet`, ten results each and no pagination. X results are a latest sample of the conversation, not a complete list or necessarily direct replies only. X costs and access limits depend on the account and must be checked in the developer console before activation. There are no automatic retries, reply pagination, user expansions, full-thread backfills or unbounded reads. At an X read price of $0.005 per returned post, the maximum requested weekly sample is 9 root posts plus 90 replies: 99 × $0.005 = $0.495 per weekly refresh, approximately $2.15 per month (52/12 weeks). This is a capped read-count estimate, not an authorization or a guarantee of the provider’s current price; verify pricing, taxes and account terms before activation. Each explicitly requested manual API refresh may add the same maximum charge. Source pushes and daily expiry-only deployments do not add X reads.

## Freshness, removals and retention

Each entry has its own `updated_at`. Cache-only source deployments retain that timestamp, accept only allowlisted IDs and drop entries at 14 days, future timestamps or invalid dates. A refresh replaces each platform wholesale: API failure, missing credentials or disabled X produces an empty platform map, never a stale fallback. Successfully missing/deleted/private videos and posts are removed. Failed comments queries keep fetched metrics but remove all previous comments. `comments_status` distinguishes `available`, YouTube `disabled`, and `unavailable`. Successful empty comments are `available` with an empty list.

YouTube stores public comment display name, optional channel/avatar URLs, full plain text, publication time and source link. X stores only reply IDs and source links, not text, authors or profile data. Official opt-in X embeds fetch current display content themselves. Counts and YouTube comments are snapshots, not live or exhaustive.

Data is generated only inside the Pages upload artifact, retained for one day, never committed to public Git history or Actions caches. Fresh fetches replace old snapshots weekly; daily cache-only deployments remove entries at 14 days without renewing their timestamps. Fourteen-day application expiry is shorter than the YouTube API policy's 30-day refresh/delete limit. The client must reject expired entries too. Static hosting cannot guarantee physical removal of an already-deployed file if scheduled deployment is disabled or GitHub is unavailable: an operator must restore a successful refresh or deploy empty data before 30 days, and remove old deployed content if the site is discontinued. GitHub Pages infrastructure and visitor caches may retain prior responses outside this app's control.

## JSON contract

`schema_version: 1`, `generated_at` (build time), `refresh_interval_days: 7`, `max_age_days: 14`, `youtube` keyed by video ID, and `x` keyed by post ID. Both entry types contain `updated_at`, `source_url`, `metrics`, `comments_status`, `comments`.

YouTube metrics: optional `view_count`, `like_count`, `comment_count`. Comments: `id`, `author`, optional `author_channel_url`, optional `author_image_url`, `text`, `published_at`, `source_url`.

X metrics: optional `like_count`, `reply_count`, `retweet_count`, `quote_count`, `impression_count`. Comments: only `id` and `source_url`. All metrics are nonnegative safe integers obtained from the API. No schema fixture is published as real data.

## Safety and testing

Python uses the standard library, a 25-second request timeout and bounded response reads. Google credentials use the `x-goog-api-key` header, X uses an Authorization header. API exceptions are scrubbed: no URLs, response bodies, tokens or raw exception strings are logged. API failures produce absent data rather than untrusted error content. No credentialed API call is made by tests.

Run `python -m unittest discover -s tests -v` and `node tests/test_social_ui.cjs`. Actions job summaries distinguish missing credentials, disabled X, API failures, returned entries and comments availability without printing secrets. Build with `python scripts/build_site.py _site`. Run `python scripts/social_refresh.py --output _site/data/social.json` for a cache-only build or add `--refresh` with secrets supplied only through the environment for approved API reads. The website artifact uses an explicit public directory/file allowlist and excludes repository metadata, workflow/scripts/tests/docs and legacy metrics caches.
