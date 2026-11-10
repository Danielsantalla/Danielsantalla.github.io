#!/usr/bin/env python3
"""Fetch only allowlisted public social data. Stdlib, no API data in git."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import http.client
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UTC = timezone.utc
MAX_AGE = timedelta(days=14)
CACHE_URL = 'https://danielsantalla.com/data/social.json'
ROOT = Path(__file__).resolve().parents[1]


class APIError(Exception):
    def __init__(self, reason='unavailable', status=None):
        # Deliberately never retain response bodies, URLs or credential values.
        self.reason = reason
        self.status = status
        super().__init__(reason)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward API credentials to a redirected destination.
        return None


def request_json(url, params=None, headers=None):
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=25) as response:
            data = json.loads(response.read(2_000_001))
            if not isinstance(data, dict):
                raise APIError()
            return data
    except urllib.error.HTTPError as error:
        reason = 'unavailable'
        try:
            body = json.loads(error.read(65536))
            if any(e.get('reason') == 'commentsDisabled' for e in body.get('error', {}).get('errors', [])):
                reason = 'disabled'
        except (ValueError, AttributeError, TypeError, OSError, http.client.HTTPException):
            pass
        raise APIError(reason, error.code) from None
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        raise APIError() from None


def stamp(now):
    return now.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def ids_from_config(config):
    ids = {'youtube': [], 'x': []}
    for row in config['tutorials']:
        for platform, pattern in [('youtube', r'[\w-]{11}'), ('x', r'\d{1,25}')]:
            value = row.get(platform + '_id')
            if value is not None:
                if not isinstance(value, str) or not re.fullmatch(pattern, value):
                    raise ValueError('Invalid source ID')
                if value not in ids[platform]:
                    ids[platform].append(value)
    if len(ids['youtube']) > 50 or len(ids['x']) > 100:
        raise ValueError('Source batch too large')
    return ids


def count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.isdecimal()):
        number = int(value)
        if 0 <= number <= 9007199254740991:
            return number
    return None


def metrics(values, mapping):
    return {out: count(values[key]) for key, out in mapping.items()
            if key in values and count(values[key]) is not None}


def source(platform, id):
    return ('https://www.youtube.com/watch?v=' if platform == 'youtube' else 'https://x.com/i/status/') + id


def youtube(ids, key, now, fetch=request_json, report=None):
    if report is not None:
        report["youtube"] = "missing credential" if not key else "API request failed or invalid data"
    if not key or not ids:
        return {}
    headers = {'x-goog-api-key': key}
    base = 'https://www.googleapis.com/youtube/v3/'
    try:
        response = fetch(base + 'videos', {'part': 'statistics', 'id': ','.join(ids)}, headers)
    except APIError:
        return {}
    if report is not None:
        report['youtube'] = 'API response received'
    result = {}
    for item in response.get('items', []):
        id = item.get('id')
        if id not in ids:
            continue
        entry = {'updated_at': stamp(now), 'source_url': source('youtube', id),
                 'metrics': metrics(item.get('statistics', {}), {'viewCount': 'view_count', 'likeCount': 'like_count', 'commentCount': 'comment_count'}),
                 'comments_status': 'unavailable', 'comments': []}
        try:
            response = fetch(base + 'commentThreads', {'part': 'snippet', 'videoId': id,
                             'maxResults': 20, 'order': 'time', 'textFormat': 'plainText'}, headers)
            for thread in response.get('items', [])[:20]:
                comment = thread['snippet']['topLevelComment']
                snippet = comment['snippet']
                cid = comment['id']
                if not isinstance(cid, str):
                    continue
                record = {'id': cid, 'author': snippet.get('authorDisplayName', ''),
                          'text': snippet.get('textDisplay', ''), 'published_at': snippet.get('publishedAt', ''),
                          'source_url': source('youtube', id) + '&lc=' + urllib.parse.quote(cid, safe='')}
                for field, value in [('author_channel_url', snippet.get('authorChannelUrl')),
                                     ('author_image_url', snippet.get('authorProfileImageUrl'))]:
                    if isinstance(value, str) and value.startswith('https://'):
                        record[field] = value
                entry['comments'].append(record)
            entry['comments_status'] = 'available'
        except APIError as error:
            entry['comments_status'] = error.reason
        except (KeyError, TypeError, AttributeError):
            entry['comments'] = []
        result[id] = entry
    return result


def x_posts(ids, token, enabled, now, fetch=request_json, report=None, pause=time.sleep):
    if report is not None:
        report["x"] = "disabled (X_ENABLED is not true)" if not enabled else ("missing credential" if not token else "API request failed or invalid data")
    if not enabled or not token or not ids:
        return {}
    headers = {'Authorization': 'Bearer ' + token}
    base = 'https://api.x.com/2/tweets'
    try:
        response = fetch(base, {'ids': ','.join(ids), 'tweet.fields': 'public_metrics'}, headers)
    except APIError:
        return {}
    if report is not None:
        report['x'] = 'API response received'
    result = {}
    search_started = False
    for item in response.get('data', []):
        id = item.get('id')
        if id not in ids or id in result:
            continue
        fields = ('like_count', 'reply_count', 'retweet_count', 'quote_count', 'impression_count')
        entry = {'updated_at': stamp(now), 'source_url': source('x', id),
                 'metrics': metrics(item.get('public_metrics', {}), {k: k for k in fields}),
                 'comments_status': 'unavailable', 'comments': []}
        try:
            # Full-archive search permits at most one request per second.
            # Wait after the prior response too, including failed responses.
            if search_started:
                pause(1.1)
            search_started = True
            replies = fetch(base + '/search/all', {'query': 'conversation_id:' + id + ' is:reply -is:retweet',
                            'since_id': id, 'max_results': 10, 'sort_order': 'recency'}, headers)
            for reply in replies.get('data', [])[:10]:
                rid = reply.get('id', '')
                if isinstance(rid, str) and re.fullmatch(r'\d{1,25}', rid):
                    entry['comments'].append({'id': rid, 'source_url': source('x', rid)})
            entry['comments_status'] = 'available'
        except APIError:
            pass
        result[id] = entry
    return result


def valid_cache(cache, ids, now):
    """Drop expired/future/unallowlisted entries without extending their lifetime."""
    result = {'youtube': {}, 'x': {}}
    if not isinstance(cache, dict) or cache.get('schema_version') != 1:
        return result
    for platform in result:
        entries = cache.get(platform, {})
        if not isinstance(entries, dict):
            continue
        for id in ids[platform]:
            entry = entries.get(id)
            try:
                updated = datetime.fromisoformat(entry['updated_at'].replace('Z', '+00:00'))
                age = now - updated
                one_time = platform == 'x' and entry.get('mode') == 'one_time'
                if age < timedelta(0) or (not one_time and age >= MAX_AGE):
                    continue
                # Cache is our public deployment, never an API fallback on refresh.
                if entry.get('source_url') != source(platform, id) or not isinstance(entry.get('metrics'), dict):
                    continue
                result[platform][id] = entry
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
    return result


def remove_x_entries(entries, removals):
    """Apply operator-requested removal without contacting or charging X."""
    if not isinstance(removals, dict):
        raise ValueError('Invalid X removal list')
    lists = [removals.get(key, []) for key in ('post_ids', 'author_ids')]
    for values in lists:
        if not isinstance(values, list) or any(not isinstance(v, str) or not re.fullmatch(r'\d{1,25}', v) for v in values):
            raise ValueError('Invalid X removal ID')
    post_ids, author_ids = map(set, lists)
    result = {}
    for id, entry in entries.items():
        if id in post_ids:
            continue
        clean = dict(entry)
        clean['comments'] = [c for c in entry.get('comments', [])
            if isinstance(c, dict) and c.get('id') not in post_ids and c.get('author_id') not in author_ids]
        result[id] = clean
    return result


def correct_x_impressions(entries, corrections):
    """Do not equate unavailable legacy API impressions with zero reach.

    Owner-supplied Analytics evidence is kept separate from API provenance.
    Corrections never create posts or renew an imported snapshot's timestamp.
    """
    posts = corrections.get('posts', {}) if isinstance(corrections, dict) and corrections.get('schema_version') == 1 else {}
    if not isinstance(posts, dict):
        posts = {}
    result = {}
    for id, entry in entries.items():
        clean = dict(entry)
        clean['metrics'] = dict(entry.get('metrics', {}))
        # The imported 2020 posts all returned zero, including one with 76,284
        # impressions in the owner's Analytics. Zero is unverified, not reach.
        if clean['metrics'].get('impression_count') == 0:
            clean['metrics'].pop('impression_count')
            clean['impressions_status'] = 'unavailable'
        correction = posts.get(id)
        if isinstance(correction, dict):
            value = count(correction.get('impression_count'))
            verified = correction.get('verified_on', '')
            try:
                valid_date = isinstance(verified, str) and datetime.strptime(verified, '%Y-%m-%d').strftime('%Y-%m-%d') == verified
            except ValueError:
                valid_date = False
            if (value is not None and valid_date
                    and correction.get('source_kind') == 'owner_analytics_screenshot'
                    and correction.get('source_url') == source('x', id)):
                clean['metrics']['impression_count'] = value
                clean['impressions_status'] = 'owner_verified'
                clean['impressions_source'] = {key: correction[key] for key in ('source_kind', 'verified_on', 'source_url')}
        result[id] = clean
    return result


def fail_closed(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except (APIError, KeyError, TypeError, ValueError, AttributeError):
        # Malformed upstream data must not prevent deploying the purged cache.
        report = kwargs.get('report')
        if report is not None:
            report['youtube' if operation is youtube else 'x'] = 'API request failed or invalid data'
        return {}


def write_summary(report, platforms, ids):
    lines = ['## Social-data deployment', '']
    for platform in ['youtube', 'x']:
        entries = platforms[platform]
        missing_metrics = sum(not entry.get('metrics') for entry in entries.values())
        unavailable = sum(entry.get('comments_status') == 'unavailable' for entry in entries.values())
        disabled = sum(entry.get('comments_status') == 'disabled' for entry in entries.values())
        lines.append(f"- {platform}: {report[platform]}; entries {len(entries)}/{len(ids[platform])}; "
                     f"entries without metrics {missing_metrics}; comments unavailable {unavailable}; comments disabled {disabled}.")
    lines += ['', 'An empty platform or successful deployment does not mean live API integration is active. Missing values are not zero.']
    summary = '\n'.join(lines) + '\n'
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(UTC)
    ids = ids_from_config(json.loads((ROOT / 'data/social-sources.json').read_text()))
    try:
        cache = request_json(CACHE_URL)
    except APIError:
        cache = {}
    platforms = valid_cache(cache, ids, now)
    report = {platform: 'cache-only (no social API requests)' for platform in platforms}
    if args.refresh:
        # X is never fetched or renewed by source pushes or scheduled refreshes.
        platforms['youtube'] = fail_closed(youtube, ids['youtube'], os.getenv('YOUTUBE_API_KEY', ''), now, report=report)
    removals_path = ROOT / 'data/x-removals.json'
    try:
        removals = json.loads(removals_path.read_text())
        platforms['x'] = remove_x_entries(platforms['x'], removals)
    except (OSError, ValueError, TypeError):
        platforms['x'] = {}  # Malformed removal instructions must fail closed.
    try:
        corrections = json.loads((ROOT / 'data/x-metric-corrections.json').read_text())
    except (OSError, ValueError, TypeError):
        corrections = {}
    platforms['x'] = correct_x_impressions(platforms['x'], corrections)
    payload = {'schema_version': 1, 'generated_at': stamp(now), 'refresh_interval_days': 7,
               'max_age_days': 14, **platforms}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    write_summary(report, platforms, ids)


if __name__ == '__main__':
    main()
