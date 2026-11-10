import importlib.util
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import x_once as x
import social_refresh as s

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
IDS = s.ids_from_config(json.loads((ROOT / 'data/social-sources.json').read_text()))['x']
PRICE_TEXT = '| Resource | Unit cost |\n| Posts: Read | $0.005 per resource |\n| User: Read | $0.010 per resource |'
ENV = {'GITHUB_REPOSITORY': x.REPOSITORY, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
    'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'X_ONCE_APPROVAL': x.BATCH_ID,
    'GITHUB_TOKEN': 'GITHUB_SECRET', 'X_TOKEN': 'X_SECRET', 'GITHUB_SHA': '1'*40}

class OneTimeTests(unittest.TestCase):
    def test_plan_exact_99_posts_90_profiles_under_1400_mills(self):
        self.assertEqual(x.plan(IDS), 99)
        self.assertEqual(x.PRICE * x.plan(IDS) + x.USER_PRICE * 90, x.LIMIT)
        self.assertLessEqual(x.LIMIT, x.APPROVED_LIMIT)
        for bad in [IDS[:-1], IDS + ['99'], IDS[:-1] + ['99'], IDS[:-1] + [IDS[0]]]:
            with self.assertRaises(x.ImportBlocked): x.plan(bad)

    def test_no_schedule_retry_branch_or_unapproved_context(self):
        for field, value in [('GITHUB_EVENT_NAME','schedule'), ('GITHUB_EVENT_NAME','push'),
                ('GITHUB_RUN_ATTEMPT','2'),('GITHUB_REF','refs/heads/other'),
                ('GITHUB_REPOSITORY','other/repo'),('X_ONCE_APPROVAL',''),('X_TOKEN',''),('GITHUB_TOKEN','')]:
            fetch = Mock()
            with self.assertRaises(x.ImportBlocked):
                x.execute({**ENV, field:value}, IDS, NOW, fetch=fetch)
            fetch.assert_not_called()

    def test_price_and_credit_fail_closed(self):
        for text in ['', PRICE_TEXT.replace('0.005', '0.006'), PRICE_TEXT + '\n' + PRICE_TEXT]:
            with self.assertRaises(x.ImportBlocked): x.verify_price(text)
        x.verify_price(PRICE_TEXT)
        x.verify_price('| **Posts: Read** | \\$0.005 per resource |\n| **User: Read** | \\$0.010 per resource |')
        for amount in ['0.494', 'NaN', 'Infinity', None, False, '-2']:
            with self.assertRaises(x.ImportBlocked): x.verify_credit({'data': {'total_balance': amount}})
        x.verify_credit({'data': {'total_balance': '1.395'}})
        with self.assertRaises(x.ImportBlocked): x.verify_credit({'data': {'total_balance': 10}, 'errors': [{}]})
        claim=Mock()
        with self.assertRaises(x.ImportBlocked):
            x.execute(ENV, IDS, NOW, fetch=lambda *a,**k: {}, read_price=lambda:PRICE_TEXT, claim=claim)
        claim.assert_not_called()

    def test_claim_precedes_paid_reads_with_bounded_author_expansions(self):
        events=[]
        def fetch(url, params=None, headers=None):
            if url.endswith('/usage/credits'):
                events.append('balance'); return {'data': {'total_balance': 10}}
            self.assertIn('claimed', events)
            events.append(url)
            self.assertEqual(headers, {'Authorization':'Bearer X_SECRET'})
            if url.endswith('/search/all'):
                self.assertEqual(params['max_results'],10)
                return {'data': [{'id':str(i+1), 'text':'Real reply text','author_id':str(i+101), 'created_at':'2026-11-01T12:00:00Z'} for i in range(10)], 'includes': {'users':[{'id':str(i+101),'name':'Real Name','username':'person'+str(i),'profile_image_url':'https://pbs.twimg.com/profile_images/test.jpg'} for i in range(10)]}, 'meta':{'next_token':'NO_PAGINATION'}}
            return {'data': [{'id':id,'public_metrics':{'like_count':1}} for id in IDS]}
        entries, summary=x.execute(ENV,IDS,NOW,fetch=fetch,read_price=lambda:PRICE_TEXT,
            claim=lambda env:events.append('claimed'), pause=lambda t:None)
        self.assertEqual(events[:2], ['balance','claimed'])
        self.assertEqual(len(events),13) # two balance checks, latch, ten paid requests
        self.assertEqual(len(entries),9)
        self.assertEqual(summary['reserved_post_capacity'],99)
        self.assertEqual(summary['returned_posts'],99)
        self.assertEqual(summary['returned_profiles'],90)
        self.assertEqual(summary['reserved_profile_capacity'],90)
        self.assertEqual(summary['estimated_returned_cost_usd'],'1.395')
        self.assertEqual(len(entries[IDS[0]]['comments']),10)
        self.assertEqual(entries[IDS[0]]['comments'][0]['author'],'Real Name')
        self.assertEqual(entries[IDS[0]]['mode'],'one_time')
        self.assertFalse(summary['stopped_on_error'])
        for private in ['X_SECRET','GITHUB_SECRET','NO_PAGINATION','total_balance']:
            self.assertNotIn(private,json.dumps([entries,summary]))

    def test_duplicate_claim_stops_before_paid_call(self):
        fetch=Mock(return_value={'data':{'total_balance':10}})
        def fail_claim(env): raise x.ImportBlocked('already attempted')
        with self.assertRaises(x.ImportBlocked):
            x.execute(ENV,IDS,NOW,fetch=fetch,read_price=lambda:PRICE_TEXT,claim=fail_claim)
        self.assertEqual(fetch.call_count,1)
        self.assertTrue(fetch.call_args.args[0].endswith('/usage/credits'))

    def test_uncertain_paid_request_is_not_retried_and_stops_batch(self):
        paid=[]
        def fetch(url, params=None, headers=None):
            if url.endswith('/usage/credits'): return {'data':{'total_balance':10}}
            paid.append(url)
            if url.endswith('/search/all'): raise s.APIError()
            return {'data':[{'id':id} for id in IDS]}
        entries,summary=x.execute(ENV,IDS,NOW,fetch=fetch,read_price=lambda:PRICE_TEXT,claim=lambda env:None,pause=lambda t:None)
        self.assertEqual(len(paid),2)
        self.assertTrue(summary['stopped_on_error'])
        self.assertEqual(summary['reserved_post_capacity'],19)
        self.assertEqual(len(entries),9)
        self.assertTrue(all(e['comments_status']=='unavailable' for e in entries.values()))

    def test_guard_rejects_duplicate_extra_fields_pagination_and_users(self):
        params={'ids':','.join(IDS),'tweet.fields':'public_metrics'}
        fetch=Mock(return_value={'data':[]})
        guarded=x.BudgetedFetch(IDS,fetch)
        guarded('https://api.x.com/2/tweets',params,{})
        with self.assertRaises(s.APIError): guarded('https://api.x.com/2/tweets',params,{})
        self.assertEqual(fetch.call_count,1)
        for url, bad in [('https://api.x.com/2/users',{}),('https://api.x.com/2/tweets',{**params,'expansions':'author_id'}),
                ('https://api.x.com/2/tweets/search/all',{'since_id':IDS[0], 'max_results':100})]:
            fetch=Mock();guarded=x.BudgetedFetch(IDS,fetch)
            with self.assertRaises(s.APIError): guarded(url,bad,{})
            fetch.assert_not_called()

    def test_claim_422_and_uncertain_outcome_are_scrubbed(self):
        for error in [urllib.error.HTTPError('https://secret',422,'X_SECRET',{},None), OSError('X_SECRET')]:
            opener=Mock();opener.open.side_effect=error
            with patch.object(x.urllib.request,'build_opener',return_value=opener):
                with self.assertRaises(x.ImportBlocked) as caught: x.claim_once(ENV)
            self.assertNotIn('X_SECRET',str(caught.exception))
            self.assertEqual(opener.open.call_count,1)

    def test_one_time_workflow_has_no_schedule_or_push_trigger(self):
        workflow=(ROOT/'.github/workflows/x-import-once.yml').read_text()
        self.assertIn('workflow_dispatch:',workflow)
        self.assertNotIn('schedule:',workflow)
        self.assertNotIn('push:',workflow)
        self.assertIn('github.run_attempt == 1',workflow)
        self.assertIn('group: pages',workflow)
        self.assertIn('secrets.X_TOKEN',workflow)
        regular=(ROOT/'.github/workflows/pages.yml').read_text()
        self.assertNotIn('secrets.X_TOKEN',regular)
        self.assertNotIn('x_once.py',regular)

    def test_youtube_refresh_preserves_original_x_expiry(self):
        entry={'mode':'one_time','updated_at':s.stamp(NOW),'source_url':s.source('x',IDS[0]),'metrics':{},'comments':[]}
        cache={'schema_version':1,'x':{IDS[0]:entry},'youtube':{}}
        with tempfile.TemporaryDirectory() as directory, patch.object(s,'request_json',return_value=cache), \
             patch.object(s,'youtube',return_value={}) as youtube, patch.object(s,'x_posts') as x_posts, \
             patch.object(s,'datetime') as clock, patch.object(sys,'argv',['social_refresh.py','--refresh','--output',directory+'/social.json']):
            clock.now.return_value=NOW
            clock.fromisoformat=datetime.fromisoformat
            s.main()
            result=json.loads(Path(directory+'/social.json').read_text())
        x_posts.assert_not_called()
        youtube.assert_called_once()
        self.assertEqual(result['x'][IDS[0]]['updated_at'],entry['updated_at'])

    def test_one_time_has_no_arbitrary_expiry_and_removals_are_applied(self):
        entry={'mode':'one_time','updated_at':'2020-01-01T00:00:00Z','source_url':s.source('x',IDS[0]),'metrics':{},
            'comments':[{'id':'111','author_id':'222'},{'id':'333','author_id':'444'}]}
        cache={'schema_version':1,'x':{IDS[0]:entry},'youtube':{}}
        self.assertIn(IDS[0],s.valid_cache(cache,{'x':IDS,'youtube':[]},NOW)['x'])
        self.assertEqual(s.remove_x_entries({IDS[0]:entry},{'post_ids':['111']} )[IDS[0]]['comments'],[{'id':'333','author_id':'444'}])
        self.assertEqual(s.remove_x_entries({IDS[0]:entry},{'author_ids':['444']} )[IDS[0]]['comments'],[{'id':'111','author_id':'222'}])
        self.assertEqual(s.remove_x_entries({IDS[0]:entry},{'post_ids':[IDS[0]]}),{})
        with self.assertRaises(ValueError): s.remove_x_entries({IDS[0]:entry},{'post_ids':['invalid']})

    def test_profiles_over_reserved_capacity_stop_future_paid_calls(self):
        fetch=Mock(return_value={'data':[], 'includes':{'users':[{'id':str(i)} for i in range(11)]}})
        guarded=x.BudgetedFetch(IDS,fetch)
        with self.assertRaises(s.APIError): guarded('https://api.x.com/2/tweets/search/all',x.reply_params(IDS[0]),{})
        with self.assertRaises(s.APIError): guarded('https://api.x.com/2/tweets/search/all',x.reply_params(IDS[1]),{})
        self.assertEqual(fetch.call_count,1)

    def test_missing_required_profile_omits_comment_without_inventing_author(self):
        def fetch(url,params,headers):
            if url.endswith('/search/all'):
                return {'data':[{'id':'111','text':'Body','created_at':'2020-01-01T00:00:00Z','author_id':'222'}]}
            return {'data':[{'id':IDS[0]}]}
        entries=x.x_snapshot(IDS,'secret',NOW,fetch,pause=lambda t:None)
        self.assertEqual(entries[IDS[0]]['comments'],[])

if __name__=='__main__': unittest.main()
