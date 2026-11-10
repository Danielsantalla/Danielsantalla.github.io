import importlib.util
import json
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
        self.assertEqual(result['1']['comments'], [{'id': '3', 'source_url': 'https://x.com/i/status/3'}])
        self.assertNotIn('2', result)
        self.assertNotIn('DO NOT STORE', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))

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
        self.assertIn("cron: '23 6 * * 2-7'", workflow)
        self.assertIn("if: github.event.schedule == '23 6 * * 1' ||", workflow)
        self.assertIn("if: github.event.schedule != '23 6 * * 1' &&", workflow)
        self.assertIn('default: false', workflow)

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
            for private in ['.git', '.github', 'scripts', 'tests', 'docs', 'README.md', 'data/tweet-metrics.json']:
                self.assertFalse((output / private).exists(), private)

if __name__ == '__main__':
    unittest.main()
