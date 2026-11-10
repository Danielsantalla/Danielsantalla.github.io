import importlib.util
import hashlib
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import io
import urllib.error
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
s = load('social_refresh')
b = load('build_site')
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)

class SocialTests(unittest.TestCase):
    def test_tutorials_load_current_social_script_version(self):
        version = hashlib.sha256((ROOT / 'tweet-metrics.js').read_bytes()).hexdigest()[:12]
        paths = list((ROOT / 'tutorials').rglob('index.html'))
        self.assertEqual(len(paths), 10)
        for path in paths:
            self.assertIn(f'<script src="/tweet-metrics.js?v={version}" defer></script>', path.read_text(),
                          f'{path.relative_to(ROOT)} must use the current script hash to avoid stale cached UI')

    def test_mapping(self):
        ids = s.ids_from_config(json.loads((ROOT / 'data/social-sources.json').read_text()))
        self.assertEqual(len(ids['youtube']), 7)
        self.assertEqual(len(ids['x']), 9)
        for row in json.loads((ROOT / 'data/social-sources.json').read_text())['tutorials']:
            html = (ROOT / row['path'].strip('/') / 'index.html').read_text()
            self.assertIn(row['x_id'], html)
            if 'youtube_id' in row:
                self.assertIn(row['youtube_id'], html)

    def test_youtube_batch_and_comments(self):
        calls = []
        def fetch(url, params, headers):
            calls.append((url, params, headers))
            self.assertNotIn('key', params)
            if url.endswith('/videos'):
                return {'items': [{'id': 'a', 'statistics': {'viewCount': '123', 'likeCount': '0'}}]}
            return {'items': [{'snippet': {'topLevelComment': {'id': 'c', 'snippet': {
                'authorDisplayName': 'Name', 'textDisplay': '<b>plain text</b>',
                'publishedAt': '2026-11-09T00:00:00Z', 'authorChannelUrl': 'https://www.youtube.com/channel/u',
                'authorProfileImageUrl': 'https://yt3.ggpht.com/a'}}}}]}
        result = s.youtube(['a', 'b'], 'private', NOW, fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]['id'], 'a,b')
        self.assertEqual(calls[1][1]['maxResults'], 20)
        self.assertEqual(calls[1][1]['textFormat'], 'plainText')
        self.assertNotIn('b', result)  # Successful missing/deleted item purged.
        self.assertEqual(result['a']['metrics'], {'view_count': 123, 'like_count': 0})
        self.assertNotIn('comment_count', result['a']['metrics'])
        self.assertEqual(result['a']['comments'][0]['text'], '<b>plain text</b>')
        self.assertEqual(result['a']['comments_status'], 'available')

    def test_youtube_disabled_distinct_from_errors(self):
        for reason in ['disabled', 'unavailable']:
            def fetch(url, params, headers):
                if url.endswith('/videos'):
                    return {'items': [{'id': 'a'}]}
                raise s.APIError(reason)
            entry = s.youtube(['a'], 'key', NOW, fetch)['a']
            self.assertEqual(entry['comments_status'], reason)
            self.assertEqual(entry['comments'], [])

    def test_outage_and_missing_credentials_fail_closed(self):
        def fail(*args):
            raise s.APIError()
        self.assertEqual(s.youtube(['a'], 'key', NOW, fail), {})
        self.assertEqual(s.x_posts(['1'], 'token', True, NOW, fail), {})
        def forbidden(*args):
            self.fail('Network must not be called')
        self.assertEqual(s.youtube(['a'], '', NOW, forbidden), {})
        self.assertEqual(s.x_posts(['1'], 'token', False, NOW, forbidden), {})
        self.assertEqual(s.x_posts(['1'], '', True, NOW, forbidden), {})

    def test_x_batch_ids_only_and_no_pagination(self):
        calls = []
        def fetch(url, params, headers):
            calls.append((url, params))
            if url.endswith('/search/all'):
                return {'data': [{'id': '3', 'text': 'DO NOT STORE', 'author_id': 'secret'}], 'meta': {'next_token': 'ignored'}}
            return {'data': [{'id': '1', 'public_metrics': {'like_count': 1, 'impression_count': 22}}]}
        result = s.x_posts(['1', '2'], 'private', True, NOW, fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]['ids'], '1,2')
        self.assertEqual(calls[1][1]['max_results'], 10)
        self.assertEqual(calls[1][1]['since_id'], '1')
        self.assertEqual(result['1']['comments'], [{'id': '3', 'source_url': 'https://x.com/i/status/3'}])
        self.assertNotIn('2', result)
        self.assertNotIn('DO NOT STORE', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))

    def test_x_search_rate_limit_and_duplicate_roots(self):
        calls, waits = [], []
        def fetch(url, params, headers):
            calls.append((url, params))
            if url.endswith('/search/all'):
                if params['since_id'] == '1':
                    raise s.APIError()
                return {'data': []}
            return {'data': [{'id': '1'}, {'id': '1'}, {'id': '2'}]}
        result = s.x_posts(['1', '2'], 'private', True, NOW, fetch, pause=waits.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(waits, [1.1])
        self.assertEqual(result['1']['comments_status'], 'unavailable')
        self.assertEqual(result['2']['comments_status'], 'available')

    def test_workflow_cannot_activate_paid_x(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        self.assertIn("X_ENABLED: 'false'", workflow)
        self.assertNotIn('secrets.X_TOKEN', workflow)
        self.assertNotIn('vars.X_ENABLED', workflow)

    def test_cache_expiry_future_allowlist_and_no_renewal(self):
        for age, expected in [(13, True), (14, False), (15, False), (-1, False)]:
            updated = s.stamp(NOW - timedelta(days=age))
            entry = {'updated_at': updated, 'source_url': s.source('x', '1'), 'metrics': {}}
            cache = {'schema_version': 1, 'x': {'1': entry, '2': entry}}
            result = s.valid_cache(cache, {'x': ['1'], 'youtube': []}, NOW)
            self.assertEqual('1' in result['x'], expected)
            self.assertNotIn('2', result['x'])
            if expected:
                self.assertEqual(result['x']['1']['updated_at'], updated)
        self.assertEqual(s.valid_cache(None, {'x': [], 'youtube': []}, NOW), {'x': {}, 'youtube': {}})

    def test_only_real_nonnegative_counts(self):
        for bad in [True, False, -1, 'bad', 2.3, None, 2**60]:
            self.assertIsNone(s.count(bad))
        self.assertEqual(s.count('0'), 0)

    def test_legacy_x_zero_impressions_are_unknown(self):
        entry = {'mode': 'one_time', 'updated_at': s.stamp(NOW),
                 'metrics': {'impression_count': 0, 'like_count': 0, 'reply_count': 6},
                 'comments': [{'id': 'reply'}]}
        result = s.correct_x_impressions({'1': entry}, {})['1']
        self.assertNotIn('impression_count', result['metrics'])
        self.assertEqual(result['impressions_status'], 'unavailable')
        self.assertEqual(result['metrics']['like_count'], 0)
        self.assertEqual(result['comments'], entry['comments'])
        self.assertEqual(result['updated_at'], entry['updated_at'])
        self.assertEqual(entry['metrics']['impression_count'], 0, 'Input snapshot must remain unchanged')

    def test_owner_screenshot_impressions_keep_provenance_and_snapshot_date(self):
        id = '1256781925890625543'
        corrections = {'schema_version': 1, 'posts': {id: {'impression_count': 76284,
            'source_kind': 'owner_analytics_screenshot', 'verified_on': '2026-11-10', 'source_url': s.source('x', id)}}}
        entry = {'mode': 'one_time', 'updated_at': '2026-11-09T12:00:00Z',
                 'metrics': {'impression_count': 0, 'like_count': 674}, 'comments': []}
        result = s.correct_x_impressions({id: entry}, corrections)[id]
        self.assertEqual(result['metrics']['impression_count'], 76284)
        self.assertEqual(result['impressions_status'], 'owner_verified')
        self.assertEqual(result['impressions_source'], {
            'source_kind': 'owner_analytics_screenshot', 'verified_on': '2026-11-10', 'source_url': s.source('x', id)})
        self.assertEqual(result['updated_at'], entry['updated_at'])
        self.assertEqual(result['metrics']['like_count'], 674)
        self.assertEqual(s.correct_x_impressions({}, corrections), {}, 'Corrections must not restore removed posts')
        self.assertEqual(s.correct_x_impressions({id: result}, corrections)[id], result, 'Repeated deployments must be stable')

    def test_rounded_owner_screenshot_keeps_precision_without_inventing_exact_count(self):
        id = '1211425334228336642'
        corrections = json.loads((ROOT / 'data/x-metric-corrections.json').read_text())
        corrections['posts'][id]['source_kind'] = 'owner_analytics_screenshot'
        entry = {'mode': 'one_time', 'updated_at': '2026-11-09T12:00:00Z',
                 'metrics': {'impression_count': 0, 'like_count': 4080, 'reply_count': 35},
                 'comments': [{'id': 'reply'}]}
        result = s.correct_x_impressions({id: entry}, corrections)[id]
        self.assertEqual(result['metrics']['impression_count'], 394700)
        self.assertEqual(result['impressions_source'], {
            'source_kind': 'owner_analytics_screenshot', 'verified_on': '2026-11-10',
            'source_url': s.source('x', id), 'precision': 'rounded',
            'rounding_increment': 100, 'source_display': '394,7 mil'})
        self.assertEqual(result['comments'], entry['comments'])
        self.assertEqual(result['updated_at'], entry['updated_at'])
        self.assertEqual(result['metrics']['like_count'], 4080)
        self.assertEqual(result['metrics']['reply_count'], 35)
        self.assertNotIn('video_view_count', result['metrics'])
        self.assertEqual(s.correct_x_impressions({id: result}, corrections)[id], result)
        self.assertEqual(s.correct_x_impressions({}, corrections), {})
        for change in [{'precision': 'invented'}, {'rounding_increment': True},
                       {'rounding_increment': 0}, {'rounding_increment': 99},
                       {'impression_count': 394701}, {'source_display': None},
                       {'source_display': 'bad\nsource'}, {'source_display': ''}]:
            with self.subTest(change=change):
                invalid = {'schema_version': 1, 'posts': {id: {**corrections['posts'][id], **change}}}
                rejected = s.correct_x_impressions({id: entry}, invalid)[id]
                self.assertNotIn('impression_count', rejected['metrics'])
                self.assertNotIn('impressions_source', rejected)

    def test_all_nine_verified_analytics_observations_match_sources(self):
        corrections = json.loads((ROOT / 'data/x-metric-corrections.json').read_text())['posts']
        expected = {
            '1256781925890625543': (76286, None), '1213985659691655168': (137000, 1000),
            '1252030003052765185': (60032, None), '1216178256120029184': (199400, 100),
            '1243709133867499521': (254700, 100), '1211425334228336642': (394700, 100),
            '1260695131755286528': (39581, None), '1254784538212876288': (57230, None),
            '1212766169381441537': (226400, 100)}
        self.assertEqual(set(corrections), set(expected))
        for id, (value, increment) in expected.items():
            self.assertEqual(corrections[id]['impression_count'], value)
            self.assertEqual(corrections[id]['source_kind'], 'owner_analytics_page')
            self.assertEqual(corrections[id]['source_url'], s.source('x', id))
            self.assertEqual(corrections[id].get('rounding_increment'), increment)
            self.assertEqual(corrections[id].get('precision'), 'rounded' if increment else None)

    def test_direct_owner_analytics_page_has_distinct_provenance(self):
        id = '1211425334228336642'
        correction = {'impression_count': 394700, 'source_kind': 'owner_analytics_page',
                      'verified_on': '2026-11-10', 'source_url': s.source('x', id)}
        result = s.correct_x_impressions({id: {'metrics': {}}}, {'schema_version': 1, 'posts': {id: correction}})[id]
        self.assertEqual(result['metrics']['impression_count'], 394700)
        self.assertEqual(result['impressions_source']['source_kind'], 'owner_analytics_page')

    def test_rounded_correction_deploy_uses_cache_without_paid_requests(self):
        id = '1211425334228336642'
        entry = {'mode': 'one_time', 'updated_at': '2026-11-09T12:00:00Z',
                 'source_url': s.source('x', id), 'metrics': {'like_count': 4080},
                 'comments': [{'id': '123', 'author_id': '456'}]}
        cache = {'schema_version': 1, 'x': {id: entry}, 'youtube': {}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'social.json'
            with patch.object(s, 'request_json', return_value=cache) as request, \
                    patch.object(s, 'youtube') as youtube, patch.object(s, 'x_posts') as x_posts, \
                    patch('sys.argv', ['social_refresh.py', '--output', str(output)]), patch('sys.stdout', io.StringIO()):
                s.main()
            request.assert_called_once_with(s.CACHE_URL)
            youtube.assert_not_called()
            x_posts.assert_not_called()
            result = json.loads(output.read_text())['x'][id]
            self.assertEqual(result['metrics']['impression_count'], 394700)
            self.assertEqual(result['impressions_source']['precision'], 'rounded')
            self.assertEqual(result['impressions_source']['source_display'], '394,7 mil')
            self.assertEqual(result['updated_at'], entry['updated_at'])
            self.assertEqual(result['comments'], entry['comments'])

    def test_invalid_corrections_fail_closed_and_do_not_change_positive_api_counts(self):
        entry = {'metrics': {'impression_count': 55}}
        correct = {'impression_count': 99, 'source_kind': 'owner_analytics_screenshot',
                   'verified_on': '2026-11-10', 'source_url': s.source('x', '1')}
        for change in [{'impression_count': -1}, {'impression_count': True}, {'impression_count': 2.5},
                       {'source_kind': 'invented'}, {'source_url': s.source('x', '2')},
                       {'verified_on': '2026-02-30'}, {'verified_on': []}]:
            result = s.correct_x_impressions({'1': entry}, {'schema_version': 1, 'posts': {'1': {**correct, **change}}})
            self.assertEqual(result['1'], entry)
        for corrections in [None, [], {}, {'schema_version': 1, 'posts': []}]:
            self.assertEqual(s.correct_x_impressions({'1': entry}, corrections)['1'], entry)

    def test_cache_only_deployment_applies_correction_without_api_reads(self):
        id = '1256781925890625543'
        entry = {'mode': 'one_time', 'updated_at': '2026-11-09T12:00:00Z',
                 'source_url': s.source('x', id), 'metrics': {'impression_count': 0, 'like_count': 674},
                 'comments': [{'id': '123', 'author_id': '456'}]}
        cache = {'schema_version': 1, 'x': {id: entry}, 'youtube': {}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'social.json'
            with patch.object(s, 'request_json', return_value=cache) as request, \
                    patch.object(s, 'youtube') as youtube, patch.object(s, 'x_posts') as x_posts, \
                    patch('sys.argv', ['social_refresh.py', '--output', str(output)]), patch('sys.stdout', io.StringIO()):
                s.main()
            request.assert_called_once_with(s.CACHE_URL)
            youtube.assert_not_called()
            x_posts.assert_not_called()
            result = json.loads(output.read_text())['x'][id]
            self.assertEqual(result['metrics']['impression_count'], 76286)
            self.assertEqual(result['updated_at'], entry['updated_at'])
            self.assertEqual(result['comments'], entry['comments'])

    def test_malformed_api_data_is_purged(self):
        def malformed(*args):
            raise TypeError('upstream details')
        self.assertEqual(s.fail_closed(malformed), {})

    def test_error_messages_are_scrubbed(self):
        error = urllib.error.HTTPError('https://example.test/private', 403, 'TOKEN_SECRET', {},
                                      io.BytesIO(b'{"error":{"errors":[{"reason":"commentsDisabled"}],"message":"TOKEN_SECRET"}}'))
        opener = Mock()
        opener.open.side_effect = error
        with patch.object(s.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(s.APIError) as raised:
                s.request_json('https://example.test', headers={'x-goog-api-key': 'TOKEN_SECRET'})
        self.assertEqual(str(raised.exception), 'disabled')
        self.assertNotIn('TOKEN_SECRET', str(raised.exception))
        self.assertIsNone(s.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test'))

    def test_platform_status_without_credentials_or_on_failure(self):
        report = {}
        self.assertEqual(s.youtube(['a'], '', NOW, report=report), {})
        self.assertEqual(report['youtube'], 'missing credential')
        self.assertEqual(s.x_posts(['1'], 'private', False, NOW, report=report), {})
        self.assertIn('disabled', report['x'])
        s.x_posts(['1'], '', True, NOW, report=report)
        self.assertEqual(report['x'], 'missing credential')
        def fail(*args):
            raise s.APIError()
        s.youtube(['a'], 'private', NOW, fetch=fail, report=report)
        self.assertIn('failed', report['youtube'])
        self.assertNotIn('private', json.dumps(report))

    def test_only_weekly_schedule_refreshes_apis(self):
        workflow = (ROOT / '.github/workflows/pages.yml').read_text()
        schedules = re.findall(r"cron:\s*'([^']+)'", workflow)
        self.assertEqual(len(schedules), 2)
        scheduled_days = {}
        for schedule in schedules:
            fields = schedule.split()
            self.assertEqual(fields[:4], ['23', '6', '*', '*'])
            self.assertEqual(len(fields), 5)
            days = set()
            for item in fields[4].split(','):
                bounds = [int(value) for value in item.split('-')]
                self.assertIn(len(bounds), [1, 2])
                start, end = bounds[0], bounds[-1]
                self.assertTrue(0 <= start <= end <= 6, 'GitHub weekdays must be 0–6')
                days.update(range(start, end + 1))
            scheduled_days[schedule] = days
        refresh = re.findall(r"if: github.event.schedule == '([^']+)'", workflow)
        cache_only = re.findall(r"if: github.event.schedule != '([^']+)'", workflow)
        self.assertEqual(len(refresh), 1)
        self.assertEqual(cache_only, refresh)
        self.assertEqual(scheduled_days[refresh[0]], {1}, 'Only Monday refreshes APIs')
        remaining = set().union(*(days for cron, days in scheduled_days.items() if cron != refresh[0]))
        self.assertEqual(remaining, {0, 2, 3, 4, 5, 6})
        self.assertFalse(remaining & scheduled_days[refresh[0]])
        self.assertIn('default: false', workflow)

    def test_youtube_privacy_and_terms_notice(self):
        page = (ROOT / 'privacy/index.html').read_text()
        self.assertIn('agree to be bound by the', page)
        self.assertIn('https://www.youtube.com/t/terms', page)
        self.assertIn('agree to this privacy policy', page)
        self.assertIn('Public statistics and comments appear automatically', page)
        self.assertNotIn('Agree and show YouTube', page)
        self.assertIn('rather than Google-hosted profile images', page)
        self.assertIn('https://policies.google.com/privacy', page)

    def test_truncated_success_response_is_scrubbed(self):
        response = Mock()
        response.read.side_effect = s.http.client.IncompleteRead(b'TOKEN_SECRET', 100)
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = context
        with patch.object(s.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(s.APIError) as raised:
                s.request_json('https://example.test')
        self.assertEqual(str(raised.exception), 'unavailable')

    def test_truncated_error_response_is_scrubbed(self):
        body = Mock()
        body.read.side_effect = s.http.client.IncompleteRead(b'TOKEN_SECRET', 100)
        error = urllib.error.HTTPError('https://example.test', 403, 'TOKEN_SECRET', {}, body)
        opener = Mock()
        opener.open.side_effect = error
        with patch.object(s.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(s.APIError) as raised:
                s.request_json('https://example.test')
        self.assertEqual(str(raised.exception), 'unavailable')

    def test_build_rejects_nonempty_output_without_deleting(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            private = output / 'secret.env'
            private.write_text('PRIVATE')
            with self.assertRaisesRegex(ValueError, 'must be empty'):
                b.build(output)
            self.assertEqual(private.read_text(), 'PRIVATE')
            self.assertFalse((output / 'index.html').exists())

    def test_artifact_excludes_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            b.build(output)
            self.assertTrue((output / 'index.html').is_file())
            self.assertTrue((output / 'data/social-sources.json').is_file())
            for private in ['.git', '.github', 'scripts', 'tests', 'docs', 'README.md', 'data/tweet-metrics.json', 'data/x-metric-corrections.json']:
                self.assertFalse((output / private).exists(), private)

if __name__ == '__main__':
    unittest.main()
