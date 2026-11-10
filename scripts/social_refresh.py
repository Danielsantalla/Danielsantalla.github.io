#!/usr/bin/env python3
"""Fetch only allowlisted public social data. Stdlib, no API data in git."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import http.client
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

UTC = timezone.utc
MAX_AGE = timedelta(days=14)
CACHE_URL = 'https://danielsantalla.com/data/social.json'
ROOT = Path(__file__).resolve().parents[1]


class APIError(Exception):
    def __init__(self, reason='unavailable'):
        # Deliberately never retain response bodies, URLs or credential values.
        self.reason = reason
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
        raise APIError(reason) from None
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


def x_posts(ids, token, enabled, now, fetch=request_json, report=None):
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
    for item in response.get('data', []):
        id = item.get('id')
        if id not in ids:
            continue
        fields = ('like_count', 'reply_count', 'retweet_count', 'quote_count', 'impression_count')
        entry = {'updated_at': stamp(now), 'source_url': source('x', id),
                 'metrics': metrics(item.get('public_metrics', {}), {k: k for k in fields}),
                 'comments_status': 'unavailable', 'comments': []}
        try:
            replies = fetch(base + '/search/all', {'query': 'conversation_id:' + id + ' is:reply -is:retweet',
                            'max_results': 10, 'sort_order': 'recency'}, headers)
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
                if not timedelta(0) <= now - updated < MAX_AGE:
                    continue
                # Cache is our public deployment, never an API fallback on refresh.
                if entry.get('source_url') != source(platform, id) or not isinstance(entry.get('metrics'), dict):
                    continue
                result[platform][id] = entry
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
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
    report = {}
    if args.refresh:
        platforms = {'youtube': fail_closed(youtube, ids['youtube'], os.getenv('YOUTUBE_API_KEY', ''), now, report=report),
                     'x': fail_closed(x_posts, ids['x'], os.getenv('X_TOKEN', ''), os.getenv('X_ENABLED', '').lower() == 'true', now, report=report)}
    else:
        try:
            cache = request_json(CACHE_URL)
        except APIError:
            cache = {}
        platforms = valid_cache(cache, ids, now)
        report = {platform: 'cache-only (no social API requests)' for platform in platforms}
    payload = {'schema_version': 1, 'generated_at': stamp(now), 'refresh_interval_days': 7,
               'max_age_days': 14, **platforms}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    write_summary(report, platforms, ids)


if __name__ == '__main__':
    main()
