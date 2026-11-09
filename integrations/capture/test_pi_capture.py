import unittest
from pi_capture import envelope

class PiCaptureTests(unittest.TestCase):
    def fixture(self):
        return {'domain':'business','session':'session','turn':'turn','started_at':'2026-11-05T00:00:00Z',
                'completed_at':'2026-11-05T00:00:01Z','position':1000,
                'items':[{'body':'Visible text','kind':'message','role':'human','at':'2026-11-05T00:00:00Z'}],
                'events':[{'event':'agent_settled'}]}
    def test_excluded_turns_do_not_require_or_process_content(self):
        for domain in ('personal','mixed','unclassified',None):
            self.assertIsNone(envelope({'domain':domain},{}))
    def test_stable_retry_and_explicit_non_native_trace(self):
        config={'namespace':'synthetic','speaker_ids':{}}
        a=envelope(self.fixture(),config);b=envelope(self.fixture(),config)
        self.assertEqual(a,b)
        self.assertEqual(a['runs'][0]['kind'],'pi-events')
        self.assertFalse(a['runs'][0]['review']['native_spans'])
        self.assertEqual(a['source']['provider'],'pi')
        self.assertFalse(a['history'])
    def test_stable_user_human_context_and_model_changes(self):
        p=self.fixture();p['models']=[{'id':'first','provider':'synthetic'},{'id':'second','provider':'synthetic'}]
        p['items'].append({'body':'Response','kind':'message','role':'agent','at':p['completed_at'],'model':{'id':'second','provider':'synthetic'}})
        result=envelope(p,{'namespace':'synthetic','speaker_ids':{'agent':'stable-agent-user'},'on_behalf_of':'human-user'})
        self.assertEqual(result['on_behalf_of'],'human-user')
        self.assertEqual(result['items'][-1]['speaker_id'],'stable-agent-user')
        self.assertEqual(result['items'][-1]['model']['id'],'second')
        self.assertEqual(result['runs'][0]['actor_id'],'stable-agent-user')
        self.assertEqual(result['runs'][0]['input']['models'],p['models'])

    def test_secret_redacted_before_outbox(self):
        p=self.fixture();p['items'][0]['body']='secret-synthetic-value'
        result=envelope(p,{'namespace':'synthetic'},('secret-synthetic-value',))
        self.assertNotIn('secret-synthetic-value',result['items'][0]['body'])

if __name__=='__main__': unittest.main()
