"""Public HTTP comparison storage, authority and trial capability controls."""
import concurrent.futures
import copy
import secrets
import uuid


class EvalTests:
    def eval_write(self, op, client=None, key=None, status=200, **extra):
        return (client or self.bob).request('evals', {'contract_version':'commons.evals/1',
            'idempotency_key':key or str(uuid.uuid4()),'operation':op, **extra}, status)

    def test_evals_versions_attempts_shared_reads_and_retry(self):
        op={'op':'create_test','title':'Synthetic Lantern outreach research',
            'request':'What should outreach to Lantern emphasise? Use the supplied brief.',
            'configuration':{'model':'record actual client model','ordinary_tools':['files'],
                             'starting_files':{'brief.txt':'sha256:synthetic'}}}
        key=str(uuid.uuid4())
        self.assertEqual(self.eval_write(op,key=key,validate_only=True), {'validated_only':True})
        with concurrent.futures.ThreadPoolExecutor() as pool:
            saved=list(pool.map(lambda _:self.eval_write(op,key=key),range(2)))
        self.assertEqual(saved[0],saved[1]); test=saved[0]['id']
        self.eval_write({**op,'title':'changed'},key=key,status=409)
        self.eval_write(op,client=self.reader,status=403)
        self.eval_write(op,client=self.note_agent,status=403)
        token=self.bob.request('tokens',{'label':'eval coordinator','write_kinds':['eval']})['token']
        agent=type(self.agent)(self.bob.base,token)
        run=self.eval_write({'op':'create_run','test_id':test,'test_revision':1,
            'context_bundle':'Synthetic source note: Lantern prioritises developer onboarding.'},client=agent)['id']
        self.assertEqual(self.reader.request('eval-runs/'+run)['status'],'pending')
        self.eval_write({'op':'revise_test','test_id':test,'expected_revision':1,
            'title':op['title'],'request':'Produce briefing.md from brief.txt in a separate workspace.',
            'configuration':op['configuration']})
        self.eval_write({'op':'revise_test','test_id':test,'expected_revision':1,
            'title':op['title'],'request':'stale','configuration':{}},status=409)
        self.assertEqual(self.bob.request('eval-runs/'+run)['run']['snapshot']['request'],op['request'])
        self.assertEqual(len(self.reader.request('evals/'+test)['versions']),2)
        attempt={'status':'failed','output':'','error':'Client unavailable','evidence':'No session started',
                 'session_id':'synthetic-1','isolation':'unsupported','files':[],'links':[]}
        append={'op':'append_attempt','run_id':run,'expected_revision':1,'arm':'without','attempt':attempt}
        result=self.eval_write(append,client=agent,key='first-attempt')
        self.assertEqual(self.eval_write(append,client=agent,key='first-attempt'),result)
        self.eval_write(append,client=agent,status=409)
        self.assertEqual(self.reader.request('eval-runs/'+run)['status'],'partial')
        for revision,arm in [(2,'with'),(3,'without')]:
            completed={**attempt,'status':'completed','output':'Synthetic output '+arm,'error':'',
                'session_id':'separate-'+arm,'isolation':'unverified',
                'files':[{'name':'briefing.md','content':'# Exact UTF-8 α\n'}]}
            result=self.eval_write({**append,'expected_revision':revision,'arm':arm,'attempt':completed},client=agent)
        detail=self.bob.request('eval-runs/'+run)
        self.assertEqual(detail,self.reader.request('eval-runs/'+run))
        self.assertEqual(detail['status'],'completed'); self.assertEqual(len(detail['attempts']),3)
        self.assertEqual(detail['attempts'][0]['payload']['error'],'Client unavailable')
        bad=copy.deepcopy(completed); bad['links']=[{'label':'unsafe','url':'javascript:alert(1)'}]
        self.eval_write({**append,'expected_revision':4,'attempt':bad},status=422)
        self.assertEqual(self.reader.request('eval-runs/'+run),detail)
        self.assertNotIn(test,[o['id'] for o in self.reader.request('objects?q=Lantern')['objects']])

    def test_evals_trial_capability_cannot_read_results_or_mutate(self):
        self.assertIn('skill',self.reader.request('evals/guide'))
        test=self.eval_write({'op':'create_test','title':'Synthetic capability control','request':'Read brief', 'configuration':{}})['id']
        run=self.eval_write({'op':'create_run','test_id':test,'test_revision':1,'context_bundle':'Only approved synthetic knowledge.'})['id']
        token='cet_'+secrets.token_hex(32)
        grant={'op':'grant_context','run_id':run,'token':token}
        self.eval_write(grant,key='grant-'+run)
        self.eval_write(grant,key='grant-'+run)
        trial=type(self.agent)(self.bob.base,token)
        self.assertEqual(trial.request('eval-context')['context'],'Only approved synthetic knowledge.')
        for path in ['evals','evals/guide','evals/'+test,'eval-runs/'+run,'objects','chats','runs','orientation','retrieve?q=knowledge','history/'+test,'artifacts/'+test,'eval-files/'+test+'/0','me','contract']:
            trial.request(path,status=401)
        self.eval_write({'op':'create_test','title':'denied','request':'denied','configuration':{}},client=trial,status=401)
        self.bob.request('eval-context',status=401)
        self.eval_write({'op':'revoke_context','run_id':run})
        trial.request('eval-context',status=401)
        self.eval_write(grant,key='grant-'+run) # receipt replay must NOT resurrect a revoked grant
        trial.request('eval-context',status=401)

    def test_evals_independent_file_copies_and_failure_states(self):
        # Exercises file transport and input equivalence, not model execution.
        import hashlib
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory(prefix='commons-eval-files-') as root:
            initial='Lantern is a fictional developer tooling team.\n'
            paths={arm:Path(root)/arm for arm in ['without','with']}
            for path in paths.values():
                path.mkdir(); (path/'brief.txt').write_text(initial)
            hashes={arm:hashlib.sha256((path/'brief.txt').read_bytes()).hexdigest() for arm,path in paths.items()}
            self.assertEqual(hashes['without'],hashes['with'])
            test=self.eval_write({'op':'create_test','title':'Synthetic independent file task',
                'request':'Produce briefing.md from brief.txt; do not modify the brief or send anything.',
                'configuration':{'starting_files':{'brief.txt':hashes['without']},'execution':'deterministic fixture'}})['id']
            run=self.eval_write({'op':'create_run','test_id':test,'test_revision':1,'context_bundle':'Synthetic knowledge: onboarding matters.'})['id']
            for revision,arm in enumerate(['without','with'],1):
                content='# Synthetic briefing\n'+('Introduce the team.' if arm=='without' else 'Discuss onboarding.')+'\n'
                (paths[arm]/'briefing.md').write_text(content)
                if arm=='without': self.assertFalse((paths['with']/'briefing.md').exists())
                result=self.eval_write({'op':'append_attempt','run_id':run,'expected_revision':revision,'arm':arm,
                    'attempt':{'status':'completed','output':'Created briefing.md','error':'',
                    'evidence':'Separate temporary copies with matching initial SHA-256. Deterministic fixture, no agent executed.',
                    'session_id':'fixture-file-'+arm,'isolation':'unverified',
                    'files':[{'name':'briefing.md','content':(paths[arm]/'briefing.md').read_text()}]}})
                for client in [self.bob,self.reader]:
                    import urllib.request
                    response=client.opener.open(urllib.request.Request(client.base+'/api/eval-files/'+result['attempt_id']+'/0'))
                    self.assertEqual(response.read(),content.encode())
                    self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
                    self.assertEqual(response.headers['Content-Disposition'],'attachment')
            for arm,path in paths.items(): self.assertEqual(hashlib.sha256((path/'brief.txt').read_bytes()).hexdigest(),hashes[arm])
            self.assertEqual(self.bob.request('eval-runs/'+run)['status'],'completed')
            failed=self.eval_write({'op':'create_run','test_id':test,'test_revision':1,'context_bundle':''})['id']
            for revision,arm in enumerate(['without','with'],1):
                self.eval_write({'op':'append_attempt','run_id':failed,'expected_revision':revision,'arm':arm,
                    'attempt':{'status':'failed','output':'','error':'No isolated client available',
                    'evidence':'Not executed','session_id':'unstarted-'+arm,'isolation':'unsupported'}})
            self.assertEqual(self.reader.request('eval-runs/'+failed)['status'],'failed')
