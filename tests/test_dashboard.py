import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import server


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_patch = patch.object(server, 'DATA', self.root)
        self.data_patch.start()
        server.init_data()
        server.RUN.update(state='idle', started=None, finished=None, exit_code=None)
        server.LOGS.clear()
        self.http = server.LocalServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        server.stop_run()
        self.http.shutdown()
        self.http.server_close()
        self.data_patch.stop()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        hdrs = {'Content-Type': 'application/json', 'X-Jobpipe': '1'} if body is not None else {}
        hdrs.update(headers or {})
        conn.request('POST' if body is not None else 'GET', path,
                     body=json.dumps(body) if body is not None else None, headers=hdrs)
        response = conn.getresponse()
        status, raw = response.status, response.read()
        conn.close()
        return status, json.loads(raw) if raw.startswith(b'{') else raw

    def test_board_preview_save_and_remove(self):
        url = 'https://jobs.lever.co/example-board'
        listings = [{'title': 'Software Engineer', 'location': 'Berlin'}]
        with patch('sources.lever', return_value=listings) as fetch:
            self.assertEqual(self.request('/api/boards/preview', {'url': url}),
                             (200, {'count': 1, 'jobs': listings}))
            self.assertNotIn('example-board', self.request('/api/boards')[1]['lever'])
            for _ in range(2):
                self.assertEqual(self.request('/api/boards/save', {'url': url})[0], 200)
            self.assertEqual(self.request('/api/boards')[1]['lever'].count('example-board'), 1)
            self.assertEqual(self.request('/api/boards/remove', {'url': url})[0], 200)
            self.assertNotIn('example-board', self.request('/api/boards')[1]['lever'])
            self.assertEqual(self.request('/api/boards/preview',
                                          {'url': 'https://jobs.lever.co.evil.test/example'})[0], 400)
            self.assertEqual(fetch.call_count, 3)

    def seed(self):
        with server.connect() as con:
            con.execute('INSERT INTO jobs(id,title,company,location,url,score,status,analysis,found_at) VALUES(?,?,?,?,?,?,?,?,?)',
                        ('one', '<script>test</script>', 'Example', 'Berlin', 'https://example.com', 85, 'shortlisted', '{"summary":"Fits","gaps":[]}', '2026-01-01'))

    def test_existing_data_filters_draft_and_applied_export(self):
        self.seed()
        folder = self.root / 'output' / 'one'
        folder.mkdir()
        (folder / 'application.md').write_text('## Cover letter\nVerified facts only')
        status, result = self.request('/api/jobs?status=shortlisted&q=Example')
        self.assertEqual(status, 200)
        self.assertEqual(result['total'], 1)
        self.assertEqual(self.request('/api/draft?id=one')[1]['text'], '## Cover letter\nVerified facts only')
        self.assertEqual(self.request('/api/applied', {'id': 'one'})[0], 200)
        with server.connect() as con:
            first = dict(con.execute('SELECT * FROM jobs').fetchone())
        self.request('/api/applied', {'id': 'one'})
        with server.connect() as con:
            second = dict(con.execute('SELECT * FROM jobs').fetchone())
        self.assertEqual(first['follow_up_at'], second['follow_up_at'])
        self.assertIn(b'applied', self.request('/api/export')[1])
        self.assertEqual(self.request('/api/stats')[1]['counts']['applied'], 1)

    def test_latex_cv_save_review_and_pdf(self):
        from cv_source import active_markdown

        source = r"""\documentclass{article}
\begin{document}
\textbf{Sample Candidate}
\section{Summary}
Builds web applications.
\section{Experience}
\resumeSubheading{Acme}{2020--2024}{Engineer}{Berlin}
\resumeItem{Built reliable web applications.}
\end{document}"""
        saved = self.request('/api/settings', {'cv': source, 'cv_format': 'tex'})
        self.assertEqual(saved[0], 200)
        settings = self.request('/api/settings')[1]
        self.assertEqual((settings['cv_format'], settings['cv']), ('tex', source))
        markdown = active_markdown(self.root)
        self.assertIn('### Engineer | Acme | Berlin | 2020--2024', markdown)
        self.assertIn('- Built reliable web applications.', markdown)
        with patch('cv_review.ask_ai', side_effect=[
            '{"score":80,"feedback":"Clear experience."}',
            '{"edits":[{"before":"Builds web applications.","after":"Develops web applications.","reason":"Clearer wording."}]}',
        ]):
            request = {'cv': source, 'format': 'tex'}
            self.assertEqual(self.request('/api/cv/review', dict(request, action='score'))[1]['score'], 80)
            self.assertEqual(len(self.request('/api/cv/review', dict(request, action='suggest'))[1]['edits']), 1)
        self.assertEqual(self.request('/api/settings')[1]['cv'], source)
        self.seed()
        folder = self.root / 'output' / 'one'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'application.md').write_text('## Tailored summary\nDevelops web applications.\n')
        status, pdf = self.request('/api/cv/pdf', {'id': 'one'})
        self.assertEqual(status, 200)
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertFalse(list(folder.glob('*.pdf')))
        self.assertEqual(self.request('/api/settings', {'cv': 'invalid', 'cv_format': 'tex'})[0], 400)
        self.assertEqual(self.request('/api/settings')[1]['cv'], source)

    def test_settings_and_cv_validation(self):
        self.assertEqual(self.request('/api/settings', {'config': {'min_score': 78}, 'cv': '# My real CV'})[0], 200)
        result = self.request('/api/settings')[1]
        self.assertEqual(result['config']['min_score'], 78)
        self.assertEqual(result['cv'], '# My real CV')
        for changes in ({'min_score': True}, {'min_score': 101}, {'codex_command': '/bin/sh'}, {'boards': {'greenhouse': ['../escape'], 'lever': []}}):
            self.assertEqual(self.request('/api/settings', {'config': changes})[0], 400)
        server.RUN['state'] = 'running'
        self.assertEqual(self.request('/api/settings', {'cv': 'change'})[0], 400)
        server.RUN['state'] = 'idle'

    def test_inbox_and_request_boundaries(self):
        body = dict(title='Python engineer', company='Example', url='https://example.com', description='Python full stack')
        self.assertEqual(self.request('/api/inbox', body)[0], 201)
        self.assertEqual(len(list((self.root / 'inbox').glob('*.txt'))), 1)
        self.assertEqual(self.request('/api/inbox', dict(body, title='Bad|title'))[0], 400)
        self.assertEqual(self.request('/api/inbox', dict(body, url='javascript:alert(1)'))[0], 400)
        self.assertEqual(self.request('/api/inbox', body, {'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.request('/api/inbox', body, {'X-Jobpipe': '0'})[0], 403)
        self.assertEqual(self.request('/api/settings', headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.request('/../../config.json')[0], 404)

    def test_real_pipeline_subprocess_with_fake_codex(self):
        import sys
        fake = self.root / 'fake-codex'
        fake.write_text('#!' + sys.executable + '''
import json,sys
from pathlib import Path
if 'login' in sys.argv: sys.exit(0)
sys.stdin.read()
value = {"score":85,"matches":["Python"],"gaps":[],"german_required":False,"visa_or_relocation_signal":"yes","seniority_fit":"ok","salary_eur_yearly_max":None,"summary":"Good match"}
text = json.dumps(value) if '--output-schema' in sys.argv else '## Cover letter\\nA verified draft.'
Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(text)
''')
        fake.chmod(0o755)
        cfg = json.loads((self.root / 'config.json').read_text())
        cfg.update(codex_command=str(fake), use_arbeitnow=False, boards={'greenhouse': [], 'lever': []}, include_keywords=['python'])
        (self.root / 'config.json').write_text(json.dumps(cfg))
        cfg.update(max_llm_jobs_per_run=1, min_relevance=4, location_keywords=['Berlin'])
        (self.root / 'config.json').write_text(json.dumps(cfg))
        self.request('/api/inbox', {'title': 'Engineer', 'description': 'We used Python at an old project.'})
        self.request('/api/inbox', {'title': 'Python engineer in London', 'description': 'Location: London\nPython required'})
        self.request('/api/inbox', {'title': 'Engineer in Berlin', 'description': 'Location: Berlin\nRequirements: Python'})
        self.request('/api/inbox', {'title': 'Python engineer in Berlin', 'description': 'Location: Berlin\nRequirements: Python. Visa support available.'})
        self.assertEqual(self.request('/api/run/start', {})[0], 202)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.request('/api/run')[1]['state'] not in ('running', 'stopping'): break
            time.sleep(.05)
        result = self.request('/api/run')[1]
        self.assertEqual(result['state'], 'completed', result)
        self.assertEqual(result['counts'], {'found': 4, 'passed': 2, 'sent': 1, 'shortlisted': 1})
        jobs = self.request('/api/jobs?status=shortlisted')[1]['jobs']
        self.assertEqual([job['title'] for job in jobs], ['Python engineer in Berlin'])
        self.assertTrue(list((self.root / 'output').glob('*/application.md')))


if __name__ == '__main__':
    unittest.main()
