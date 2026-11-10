#!/usr/bin/env python3
"""One authorized X import. A durable repository tag prevents paid retries."""
import argparse
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from social_refresh import (APIError, NoRedirect, ROOT, UTC, datetime, ids_from_config,
                            request_json, stamp, valid_cache, metrics, source)

BATCH_ID = 'x-import-2026-11-10'
LATCH = 'refs/tags/' + BATCH_ID + '-attempted'
REPOSITORY = 'Danielsantalla/Danielsantalla.github.io'
PRICE = Decimal('0.005')
USER_PRICE = Decimal('0.010')
LIMIT = Decimal('1.395')
APPROVED_LIMIT = Decimal('1.40')
EXPECTED_IDS = frozenset(['1256781925890625543', '1213985659691655168', '1252030003052765185',
    '1216178256120029184', '1243709133867499521', '1211425334228336642',
    '1260695131755286528', '1254784538212876288', '1212766169381441537'])


class ImportBlocked(Exception):
    pass


def plan(ids):
    if len(ids) != 9 or frozenset(ids) != EXPECTED_IDS:
        raise ImportBlocked('Source map changed; no paid requests were made.')
    maximum_posts = len(ids) * 11
    maximum_users = len(ids) * 10
    if Decimal(maximum_posts) * PRICE + Decimal(maximum_users) * USER_PRICE > min(LIMIT, APPROVED_LIMIT):
        raise ImportBlocked('Estimated batch exceeds the approved limit.')
    return maximum_posts


def price_text():
    # Public documentation only. Never send credentials to this destination.
    try:
        with urllib.request.build_opener(NoRedirect()).open(
                'https://docs.x.com/x-api/getting-started/pricing.md', timeout=25) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ImportBlocked('Current X price could not be verified.')
        return raw.decode('utf-8')
    except (OSError, ValueError):
        raise ImportBlocked('Current X price could not be verified.') from None


def verify_price(text):
    text = text.replace('**', '').replace('\\$', '$')
    for label, expected in [('Posts', PRICE), ('User', USER_PRICE)]:
        matches = re.findall(r'^\s*\|\s*' + label + r':\s*Read\s*\|\s*\$(\d+(?:\.\d+)?)\s+per resource\s*\|', text, re.M)
        if len(matches) != 1 or Decimal(matches[0]) != expected:
            raise ImportBlocked('Current X post/profile price changed or could not be verified.')


def credit_balance(response):
    try:
        if response.get('errors'):
            raise ValueError()
        balance = Decimal(str(response['data']['total_balance']))
        if not balance.is_finite() or balance < 0:
            raise ValueError()
        return balance
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise ImportBlocked('X balance is unavailable.') from None


def verify_credit(response):
    balance = credit_balance(response)
    if balance < LIMIT:
        raise ImportBlocked('X balance is insufficient for the worst-case batch.')
    return balance  # Used only to calculate cost; never stored or printed.


def check_context(env):
    if (env.get('GITHUB_REPOSITORY') != REPOSITORY or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or env.get('GITHUB_REF') != 'refs/heads/main' or env.get('GITHUB_RUN_ATTEMPT') != '1'
            or env.get('X_ONCE_APPROVAL') != BATCH_ID or not env.get('X_TOKEN')
            or not env.get('GITHUB_TOKEN') or not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', ''))):
        raise ImportBlocked('One-time import requires the approved first manual main-branch attempt and credentials.')


def claim_once(env):
    # GitHub ref creation is atomic: an existing latch returns 422. It is written
    # BEFORE any paid request, so even a failed/uncertain run must not be retried.
    body = json.dumps({'ref': LATCH, 'sha': env['GITHUB_SHA']}).encode()
    req = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/git/refs',
        data=body, method='POST', headers={'Authorization': 'Bearer ' + env['GITHUB_TOKEN'],
        'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=25) as response:
            if response.status != 201:
                raise ImportBlocked('One-time marker was not confirmed; no paid requests were made.')
    except urllib.error.HTTPError as error:
        if error.code == 422:
            raise ImportBlocked('This one-time import has already been attempted. No paid retry is allowed.') from None
        raise ImportBlocked('One-time marker could not be confirmed; do not retry automatically.') from None
    except OSError:
        raise ImportBlocked('One-time marker has an uncertain outcome; do not retry automatically.') from None


def reply_params(id):
    return {'query': 'conversation_id:' + id + ' is:reply -is:retweet',
            'since_id': id, 'max_results': 10, 'sort_order': 'recency',
            'tweet.fields': 'author_id,created_at,entities,edit_history_tweet_ids,note_tweet,referenced_tweets',
            'expansions': 'author_id', 'user.fields': 'name,username,profile_image_url'}


class BudgetedFetch:
    def __init__(self, ids, fetch=request_json):
        self.ids, self.fetch = list(ids), fetch
        self.reserved = 0
        self.reserved_users = 0
        self.returned = 0
        self.returned_users = 0
        self.seen = set()
        self.stop = False
        self.last_http_status = None

    def __call__(self, url, params, headers):
        if self.stop:
            raise APIError()
        root = 'https://api.x.com/2/tweets'
        if url == root and params == {'ids': ','.join(self.ids), 'tweet.fields': 'public_metrics'}:
            key, capacity, users = 'roots', len(self.ids), 0
        elif (url == root + '/search/all' and params.get('since_id') in self.ids
                and params == reply_params(params['since_id'])):
            key, capacity, users = params['since_id'], 10, 10
        else:
            self.stop = True
            raise APIError()
        cost = Decimal(self.reserved + capacity) * PRICE + Decimal(self.reserved_users + users) * USER_PRICE
        if key in self.seen or cost > min(LIMIT, APPROVED_LIMIT):
            self.stop = True
            raise APIError()
        self.seen.add(key)
        self.reserved += capacity
        self.reserved_users += users
        try:
            response = self.fetch(url, params, headers)
            data = response.get('data', [])
            profiles = response.get('includes', {}).get('users', [])
            for records, maximum in [(data, capacity), (profiles, users)]:
                if not isinstance(records, list) or len(records) > maximum or any(not isinstance(item, dict) for item in records):
                    raise APIError()
            self.returned += len(data)
            self.returned_users += len(profiles)
            return response
        except (APIError, KeyError, TypeError, ValueError, AttributeError) as error:
            # A timeout might already be billed. Never retry or refund capacity.
            self.last_http_status = getattr(error, 'status', None)
            self.stop = True
            raise APIError() from None


def x_snapshot(ids, token, now, fetch, pause=time.sleep):
    headers = {'Authorization': 'Bearer ' + token}
    base = 'https://api.x.com/2/tweets'
    try:
        response = fetch(base, {'ids': ','.join(ids), 'tweet.fields': 'public_metrics'}, headers)
    except APIError:
        return {}
    result = {}
    search_started = False
    for item in response.get('data', []):
        id = item.get('id')
        if id not in ids or id in result:
            continue
        fields = ('like_count', 'reply_count', 'retweet_count', 'quote_count', 'impression_count')
        entry = {'mode': 'one_time', 'updated_at': stamp(now), 'source_url': source('x', id),
                 'metrics': metrics(item.get('public_metrics', {}), {k: k for k in fields}),
                 'comments_status': 'unavailable', 'comments': []}
        try:
            if search_started:
                pause(1.1)
            search_started = True
            replies = fetch(base + '/search/all', reply_params(id), headers)
            authors = {u.get('id'): u for u in replies.get('includes', {}).get('users', []) if isinstance(u.get('id'), str)}
            seen = set()
            for reply in replies.get('data', []):
                rid = reply.get('id', '')
                author_id = reply.get('author_id')
                author = authors.get(author_id, {})
                username, name, avatar = author.get('username'), author.get('name'), author.get('profile_image_url')
                rich = reply.get('note_tweet') if isinstance(reply.get('note_tweet'), dict) else reply
                text, published = rich.get('text'), reply.get('created_at')
                if (not isinstance(rid, str) or not re.fullmatch(r'\d{1,25}', rid) or rid in seen
                        or not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,15}', username)
                        or not isinstance(name, str) or not name.strip() or not isinstance(text, str)
                        or not isinstance(avatar, str) or not re.match(r'https://(?:pbs|abs)\.twimg\.com/', avatar)
                        or not isinstance(published, str)):
                    continue
                try:
                    date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    if date.tzinfo is None:
                        continue
                except ValueError:
                    continue
                seen.add(rid)
                comment = {'id': rid, 'author_id': author_id, 'author': name, 'username': username,
                           'author_url': 'https://x.com/' + username, 'author_image_url': avatar,
                           'text': text, 'published_at': published, 'source_url': source('x', rid)}
                entities = rich.get('entities')
                if isinstance(entities, dict):
                    comment['entities'] = {kind: [e for e in entities.get(kind, []) if isinstance(e, dict)][:100]
                        for kind in ('urls', 'mentions', 'hashtags', 'cashtags') if isinstance(entities.get(kind), list)}
                history = reply.get('edit_history_tweet_ids', [])
                if isinstance(history, list):
                    comment['edit_history_tweet_ids'] = [value for value in history if isinstance(value, str) and re.fullmatch(r'\d{1,25}', value)][:6]
                entry['comments'].append(comment)
            entry['comments_status'] = 'available'
        except (APIError, TypeError, ValueError, AttributeError):
            pass
        result[id] = entry
    return result


def execute(env, ids, now, fetch=request_json, read_price=price_text, claim=claim_once, pause=None):
    maximum = plan(ids)
    check_context(env)
    verify_price(read_price())
    headers = {'Authorization': 'Bearer ' + env['X_TOKEN']}
    try:
        before = verify_credit(fetch('https://api.x.com/2/usage/credits', headers=headers))
    except APIError:
        raise ImportBlocked('X balance could not be verified; no paid requests were made.') from None
    claim(env)
    guarded = BudgetedFetch(ids, fetch)
    kwargs = {'fetch': guarded}
    if pause is not None:
        kwargs['pause'] = pause
    entries = x_snapshot(ids, env['X_TOKEN'], now, **kwargs)
    summary = {'batch_id': BATCH_ID, 'attempted_at': stamp(now), 'maximum_posts': maximum,
        'maximum_profiles': 90, 'maximum_cost_usd': str(LIMIT), 'approved_limit_usd': str(APPROVED_LIMIT),
        'reserved_post_capacity': guarded.reserved, 'reserved_profile_capacity': guarded.reserved_users,
        'returned_posts': guarded.returned, 'returned_profiles': guarded.returned_users,
        'estimated_returned_cost_usd': str(Decimal(guarded.returned) * PRICE + Decimal(guarded.returned_users) * USER_PRICE),
        'stopped_on_error': guarded.stop, 'last_http_status': guarded.last_http_status}
    try:
        after = credit_balance(fetch('https://api.x.com/2/usage/credits', headers=headers))
        delta = before - after
        if Decimal(0) <= delta <= APPROVED_LIMIT:
            summary['observed_credit_change_usd'] = str(delta)
    except (APIError, ImportBlocked):
        pass  # Keep the imported data even if post-read billing is unavailable.
    return entries, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(UTC)
    ids = ids_from_config(json.loads((ROOT / 'data/social-sources.json').read_text()))
    # Read the already-built cache before claiming/spending. Do not lose a paid
    # result because of an invalid output path or absent existing artifact.
    payload = json.loads(args.output.read_text())
    platforms = valid_cache(payload, ids, now)
    try:
        entries, summary = execute(os.environ, ids['x'], now)
    except ImportBlocked as error:
        print(str(error), file=sys.stderr)
        return 1
    platforms['x'] = entries
    payload.update(platforms, generated_at=stamp(now), x_import=summary)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    lines = ['## One-time X import', '',
        '- Attempt marker created before paid reads. Automatic and manual reruns are blocked.',
        f"- Returned posts: {summary['returned_posts']}; maximum request capacity: 99 posts + 90 profiles / $1.395 USD.",
        f"- Estimated returned-resource cost: ${summary['estimated_returned_cost_usd']} USD, not a billing receipt.",
        f"- X tutorials: {len(entries)}/9; replies: {sum(len(e['comments']) for e in entries.values())}.",
        '- Author profiles included only for these replies. No pagination, retry, subscription, or recharge.',
        '- One-time snapshot: no automatic X refresh or arbitrary expiry. Removals/changes need operator maintenance.',
        '- Observed credit change: ' + summary.get('observed_credit_change_usd', 'unavailable') + ' USD; verify billing in X console.',
        '- Stopped on API error: ' + str(summary['stopped_on_error']) + '.']
    message = '\n'.join(lines) + '\n'
    print(message)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(message)
    return 0


if __name__ == '__main__':
    sys.exit(main())
