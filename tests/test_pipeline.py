import json
import sqlite3
import subprocess
import tempfile
import unittest
import types
from pathlib import Path
from unittest.mock import patch

import ai_provider as ai
import jobpipe as jp
import search_rank


class CountryAndLanguageTests(unittest.TestCase):
    def test_country_selection_aliases_and_existing_locations(self):
        config = dict(jp.CFG, target_countries=['nl'], location_keywords=[],
                      include_keywords=[], exclude_keywords=[], role_keywords=[])
        for location in ('Amsterdam', 'Nederland', 'Utrecht, NL', 'The Hague', 'Den Haag'):
            job = dict(title='Engineer', description='Build services', location=location)
            self.assertIsNone(search_rank.evaluate(job, config)[0], location)
        self.assertIsNotNone(search_rank.evaluate(dict(title='Engineer', description='', location='Berlin'), config)[0])
        config['location_keywords'] = ['Berlin']
        self.assertTrue(search_rank.location_matches('Berlin', config))
        config.update(target_countries=[], location_keywords=['Munich'])
        self.assertFalse(search_rank.location_matches('Amsterdam', config))
        self.assertTrue(search_rank.location_matches('Munich', config))
        self.assertFalse(search_rank.location_matches('Île de France', dict(config, target_countries=['de'], location_keywords=[])))

    def test_language_requirements_negation_and_unknown_policy(self):
        config = dict(english_only=True, language_unknown_policy='review')
        for text in ('Fluent Dutch required.', 'Dutch (C1) required.', 'German: C1 required.', 'Dutch is mandatory.', 'Vloeiend Nederlands vereist.', 'Fluent German and English required.'):
            self.assertIsNotNone(search_rank.language_reason(dict(title='Engineer', description=text), config), text)
        for text in ('Fluent English required.', 'English is our working language. Dutch is not required.', 'Fluent Dutch is a plus. Fluent English required.', 'Fluent Dutch is not required. Fluent English required.', 'You do not need to be fluent Dutch. Fluent English required.', 'German-speaking customers. Working language is English.'):
            self.assertIsNone(search_rank.language_reason(dict(title='Engineer', description=text), config), text)
        job = dict(title='Engineer', description='Build services in an international team.')
        self.assertIsNone(search_rank.language_reason(job, config))
        self.assertEqual(search_rank.eligibility(job, config)['status'], 'needs checking')
        self.assertEqual(search_rank.language_reason(job, dict(config, language_unknown_policy='exclude')), 'English working language unconfirmed')
        self.assertEqual(search_rank.language_assessment(dict(title='Engineer', description='Fluent English is optional.'))['english'], 'unknown')
        self.assertIsNone(search_rank.language_reason(dict(title='Engineer', description='Fließend Englisch erforderlich.'), {'exclude_german_required': True}))

    def test_language_screen_happens_before_ai_and_review_is_independent(self):
        config = dict(jp.CFG, english_only=True, language_unknown_policy='review',
                      unknown_policy='exclude', required_keywords=[], sponsorship_required=False,
                      target_countries=['nl'], location_keywords=[], include_keywords=[], role_keywords=[], exclude_keywords=[])
        job = dict(title='Engineer', location='Amsterdam', description='Fluent Dutch required.')
        with patch.dict(jp.CFG, config), patch.object(jp, 'ask') as ai:
            self.assertEqual(jp.prefilter(job)[0], 'Dutch required')
            job['description'] = 'Build services in a collaborative team.'
            self.assertIsNone(jp.prefilter(job)[0])
            ai.assert_not_called()


class PreciseScreeningTests(unittest.TestCase):
    def config(self, **changes):
        return dict(dict(jp.CFG, role_keywords=['software developer', 'frontend engineer'],
                         include_keywords=['React', 'TypeScript', 'full-stack', 'fullstack'],
                         exclude_keywords=['ausbildung', 'internship', 'unpaid', 'security clearance'],
                         location_keywords=['Berlin'], target_countries=[], required_keywords=[],
                         sponsorship_required=False, english_only=False, exclude_german_required=False,
                         exclude_dutch_required=False, unknown_policy='review', current_country='',
                         authorized_countries=[], relocation_required=False, min_relevance=4), **changes)

    def test_equivalent_titles_without_unrelated_or_seniority_expansion(self):
        config = self.config()
        for title in ('Senior TypeScript Developer', 'Senior Software Engineer', 'Front End Engineer',
                      'Frontend Developer', 'Frontend Ontwikkelaar', 'Full-Stack Engineer', 'Senior Product Engineer (TypeScript, Full-Stack)'):
            self.assertIsNone(search_rank.screen(dict(title=title, description='Requirements: React and TypeScript.', location='Berlin'), config)[0], title)
        for title in ('Civil Engineer', 'Recruiter', 'Engineering Manager', 'Sales Engineer'):
            self.assertEqual(search_rank.screen(dict(title=title, description='Our company uses React.', location='Berlin'), config)[0], 'title outside preferred roles')
        self.assertTrue(search_rank.role_matches('Engineer, Front-End', self.config(role_keywords=['frontend developer'])))
        self.assertTrue(search_rank.role_matches('Frontend-Entwickler', self.config(role_keywords=['frontend developer'])))
        self.assertFalse(search_rank.role_matches('Backend Engineer', self.config(role_keywords=['frontend developer'])))
        self.assertFalse(search_rank.role_matches('Junior TypeScript Developer', self.config(role_keywords=['senior software developer'])))
        self.assertEqual(len(search_rank.skill_matches('Full stack', ['full-stack', 'fullstack', 'full stack'])), 1)
        self.assertFalse(search_rank.skill_matches('Join our next generation team', ['next']))

    def test_job_type_exclusion_does_not_reject_education_or_leave(self):
        config = self.config()
        job = dict(title='Software Engineer', description='Abgeschlossene Ausbildung oder Studium. React required. Unpaid leave available.', location='Berlin')
        self.assertIsNone(search_rank.screen(job, config)[0])
        for title in ('Ausbildung Softwareentwicklung', 'Software Engineering Internship', 'Unpaid Frontend Developer'):
            self.assertIn('excluded job type', search_rank.excluded_reason(dict(job, title=title), config))
        self.assertIn('excluded job type', search_rank.excluded_reason(dict(job, employment_type='INTERN'), config))
        self.assertIsNone(search_rank.excluded_reason(dict(job, description='No security clearance required.'), config))
        self.assertIn('security clearance', search_rank.excluded_reason(dict(job, description='Must obtain security clearance.'), config))

    def test_residency_and_declared_authorization_are_separate(self):
        job = dict(title='Engineer', description='Applicants must already be based in the Netherlands. Existing right to work in the Netherlands is required.')
        self.assertEqual(search_rank.eligibility(job, self.config())['status'], 'needs checking')
        self.assertEqual(search_rank.eligibility(job, self.config(current_country='Germany'))['status'], 'excluded')
        self.assertEqual(search_rank.eligibility(job, self.config(current_country='Netherlands'))['status'], 'needs checking')
        self.assertEqual(search_rank.eligibility(job, self.config(current_country='NL', authorized_countries=['Netherlands']))['status'], 'eligible')
        self.assertEqual(search_rank.eligibility(dict(job, description='Our company is already based in the Netherlands.'), self.config())['status'], 'eligible')
        self.assertEqual(search_rank.eligibility(dict(job, description='We offer visa sponsorship. Relocation support is provided.'), self.config(sponsorship_required=True, relocation_required=True))['status'], 'eligible')
        self.assertEqual(search_rank.eligibility(dict(job, description='No relocation support is offered.'), self.config(relocation_required=True))['status'], 'excluded')

    def test_high_score_cannot_shortlist_unknown_or_conflicting_residency(self):
        job = dict(id='residency', title='Frontend engineer', company='Example', url='https://example.com', location='Amsterdam', description='Applicants must already be based in the Netherlands. React required.')
        with patch.dict(jp.CFG, self.config()), patch.object(jp, 'ask', return_value=json.dumps(analysis())), patch.object(jp, 'ask_ai', return_value='{"evidence": []}'), patch.object(jp, 'tailor') as draft:
            self.assertEqual(jp.process('CV facts', job)[2], 'needs_review')
            draft.assert_not_called()
        with patch.dict(jp.CFG, self.config(current_country='Germany')), patch.object(jp, 'ask') as ai:
            self.assertIn('eligibility conflict', jp.prefilter(job)[0])
            ai.assert_not_called()

    def test_reconsider_recovers_only_local_rejections_and_keeps_dedup(self):
        import dedup
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,title,company,location,url,score,status,analysis,found_at)')
        con.execute('CREATE TABLE feedback(job_id TEXT PRIMARY KEY,decision)')
        candidates = []
        for identity, title, status, analysis_value in (
            ('recover', 'TypeScript Developer', 'skipped', {'skip': 'title outside preferred roles'}),
            ('reject', 'Sales Manager', 'skipped', {'skip': 'title outside preferred roles'}),
            ('applied', 'TypeScript Developer', 'applied', {'score': 85}),
            ('ai-scored', 'TypeScript Developer', 'skipped', {'score': 0, 'scored_at': 'earlier', 'skip': 'salary'}),
            ('dismissed', 'TypeScript Developer', 'skipped', {'skip': 'title outside preferred roles'})):
            job = dict(id=identity,title=title,company='Example',location='Berlin',url='https://example.com/'+identity,description='Requirements: React and TypeScript. ' * 10)
            candidates.append(job)
            con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',(identity,title,'Example','Berlin',job['url'],0,status,json.dumps(analysis_value),'original-date'))
        con.execute("INSERT INTO feedback VALUES('dismissed','dismissed')")
        dedup.collect(con, candidates)
        protected = con.execute("SELECT * FROM jobs WHERE id IN ('applied','ai-scored','dismissed') ORDER BY id").fetchall()
        result = search_rank.reconsider(con, self.config())
        self.assertEqual((result['checked'],result['requeued'],result['still_rejected']), (2,1,1))
        self.assertEqual(con.execute("SELECT * FROM jobs WHERE id IN ('applied','ai-scored','dismissed') ORDER BY id").fetchall(), protected)
        self.assertEqual(search_rank.reconsider(con, self.config())['checked'], 0)
        recovered, _ = dedup.collect(con, [json.loads(con.execute("SELECT payload FROM candidates WHERE id='recover'").fetchone()[0])])
        self.assertEqual([j['id'] for j in recovered], ['recover'])
        con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',('recover','TypeScript Developer','Example','Berlin','https://example.com/recover',85,'shortlisted','{"score":85}','new-date'))
        self.assertEqual(dedup.collect(con, recovered)[0], [])
        con.close()


def analysis(**changes):
    value = dict(score=85, matches=['Python'], gaps=[], german_required=False,
                 visa_or_relocation_signal='yes', seniority_fit='ok',
                 salary_eur_yearly_max=None, summary='Suitable role')
    value.update(changes)
    return value


class ProviderTests(unittest.TestCase):
    def test_codex_schema_stdin_and_result(self):
        def fake(command, **kwargs):
            self.assertEqual(command[-1], '-')
            self.assertIn('private CV', kwargs['input'])
            self.assertNotIn('private CV', command)
            self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
            schema = Path(command[command.index('--output-schema') + 1])
            self.assertEqual(json.loads(schema.read_text()), ai.SCORE_SCHEMA)
            Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(analysis()))
            return subprocess.CompletedProcess(command, 0)
        with patch('ai_provider.subprocess.run', side_effect=fake):
            value = ai.ask_ai({}, 'score', 'private CV', schema=ai.SCORE_SCHEMA)
        self.assertEqual(ai.validate_score(json.loads(value))['score'], 85)

    def test_provider_errors(self):
        for failure, expected in [(FileNotFoundError(), 'not found'),
                                  (subprocess.TimeoutExpired('codex', 1), 'timed out')]:
            with self.subTest(expected=expected), patch('ai_provider.subprocess.run', side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, expected):
                    ai.ask_ai({}, 'system', 'user')
        with patch('ai_provider.subprocess.run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, 'exited'):
                ai.ask_ai({}, 'system', 'user')

    def test_anthropic_adapter(self):
        response = types.SimpleNamespace(content=[types.SimpleNamespace(type='text', text='draft')])
        from unittest.mock import MagicMock
        client = MagicMock()
        client.__enter__.return_value.messages.create.return_value = response
        factory = MagicMock(return_value=client)
        with patch.dict('sys.modules', {'anthropic': types.SimpleNamespace(Anthropic=factory)}):
            self.assertEqual(ai.ask_ai({'ai_provider': 'anthropic', 'anthropic_model': 'test-model'},
                                       'system', 'user'), 'draft')
        self.assertEqual(client.__enter__.return_value.messages.create.call_args.kwargs['model'], 'test-model')

    def test_invalid_scores(self):
        for change in [dict(score=True), dict(score=101), dict(german_required='false'),
                       dict(gaps='missing'), dict(salary_eur_yearly_max=float('nan')),
                       dict(seniority_fit='perfect')]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                ai.validate_score(analysis(**change))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        evidence_patch = patch.object(jp, 'ask_ai', return_value=json.dumps({'evidence': []}))
        evidence_patch.start()
        self.addCleanup(evidence_patch.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = dict(id='in-test', title='Python engineer', company='Example',
                        location='Berlin', url='https://example.com', description='Python visa support')

    def tearDown(self):
        self.tmp.cleanup()

    def test_evidence_rejects_fabricated_quotes(self):
        response = {"evidence": [
            {"requirement": "Python", "posting_evidence": "Python", "cv_evidence": "Python", "assessment": "match"},
            {"requirement": "Invented", "posting_evidence": "not in posting", "cv_evidence": "Python", "assessment": "match"},
            {"requirement": "Invented CV", "posting_evidence": "Python", "cv_evidence": "invented experience", "assessment": "match"}]}
        with patch.object(jp, 'ask', return_value=json.dumps(analysis())), \
             patch.object(jp, 'ask_ai', return_value=json.dumps(response)):
            result = jp.score_job('Python developer', self.job)
        self.assertEqual(len(result['evidence']), 1)
        self.assertEqual(result['evidence'][0]['requirement'], 'Python')

    def test_shortlist_draft_and_tracking(self):
        with patch.object(jp, 'OUT', self.root / 'output'), patch.object(jp, 'DB_PATH', self.root / 'jobs.db'), \
             patch.object(jp, 'ask', side_effect=[json.dumps(analysis()), '## Cover letter\nDraft']):
            j, a, status, reason = jp.process('CV facts', self.job)
            self.assertEqual(status, 'shortlisted')
            self.assertTrue((jp.OUT / 'in-test' / 'application.md').exists())
            con = jp.db()
            jp.save(con, j, a['score'], status, a)
            jp.mark_applied(j['id'])
            jp.export_review(con)
            self.assertEqual(con.execute('select status from jobs').fetchone()[0], 'applied')
            self.assertIn('Suitable role', (jp.OUT / 'review.csv').read_text())
            con.close()

    def test_failures_remain_retryable_and_filters_skip(self):
        with patch.dict(jp.CFG, exclude_german_required=True), \
             patch.object(jp, 'ask', return_value=json.dumps(analysis(german_required=True))):
            self.assertEqual(jp.process('CV', self.job)[2], 'skipped')
        with patch.object(jp, 'ask', side_effect=RuntimeError('provider failed')):
            self.assertIsNone(jp.process('CV', self.job)[2])
        with patch.object(jp, 'ask', return_value=json.dumps(analysis(score=20))):
            self.assertEqual(jp.process('CV', self.job)[2], 'low_score')


if __name__ == '__main__':
    unittest.main()

class DedupTests(unittest.TestCase):
    def test_cross_source_identity_and_separate_locations(self):
        import dedup
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,title,company,location,url,status,found_at)')
        job = dict(id='one', title='Engineer', company='Example', location='Berlin',
                   url='https://example.com/jobs/1?utm_source=email', description='Python engineering requirements. ' * 15)
        jobs, counts = dedup.collect(con, [job, dict(job, id='two', url='https://board.example/job/2'),
                                          dict(job, id='three', location='London', url='https://board.example/job/3')])
        self.assertEqual(len(jobs), 2)
        self.assertEqual(counts['duplicates'], 1)
        self.assertEqual(con.execute('SELECT count(*) FROM job_sources').fetchone()[0], 3)
        con.execute("INSERT INTO jobs VALUES('one','Engineer','Example','Berlin',?,'applied','2026')", (job['url'],))
        con.commit()
        jobs, counts = dedup.collect(con, [dict(job, id='four', url='https://other.example/job/4')])
        self.assertEqual(jobs, [])
        self.assertEqual(counts['reused'], 1)

    def test_url_identifiers_and_short_descriptions(self):
        import dedup
        self.assertNotEqual(dedup.canonical('https://example.com/job?id=1'),
                            dedup.canonical('https://example.com/job?id=2'))
        self.assertEqual(dedup.canonical('https://example.com/job?id=1&utm_source=x#top'),
                         'https://example.com/job?id=1')
        self.assertIsNone(dedup.fingerprint(dict(company='Example',title='Engineer',location='Berlin',description='Short')))


class AgentTests(unittest.TestCase):
    def test_stage_routing_and_default(self):
        agent = dict(id='strict', name='Strict scorer', instructions='Be concise.',
                     provider='anthropic', model='test-model', version=3)
        cfg = dict(ai_provider='codex', agents=[agent], agent_assignments={'scoring': 'strict'})
        selected, chosen = ai.agent_config(cfg, 'scoring')
        self.assertEqual(selected['ai_provider'], 'anthropic')
        self.assertEqual(selected['anthropic_model'], 'test-model')
        self.assertEqual(ai.agent_stamp(cfg, 'scoring')['version'], 3)
        self.assertIsNone(ai.agent_config(cfg, 'drafting')[1])
        self.assertEqual(cfg['ai_provider'], 'codex')
        with self.assertRaises(ValueError):
            ai.validate_agents([agent, agent], {})


class DeviceLoginTests(unittest.TestCase):
    def test_complete_code_is_never_a_streaming_prefix(self):
        from codex_login import parse_device_code
        prefix = 'Open https://auth.openai.com/codex/device\n'
        for value in ('ABCD-12345', '123456789', 'ABCDE-1234', 'ABCD-1234'):
            for length in range(len(value) + 1):
                self.assertIsNone(parse_device_code(prefix + value[:length]))
            self.assertEqual(parse_device_code(prefix + value + '\n'), value)
        self.assertEqual(parse_device_code(prefix + '\x1b[32mABCD-12345\x1b[0m\n'), 'ABCD-12345')
        self.assertIsNone(parse_device_code('ABCD-12345\n'))


    def test_success_and_failure_redaction(self):
        import codex_login, time
        from io import StringIO
        def wait_done():
            deadline = time.monotonic() + 2
            while codex_login.snapshot()['state'] in ('starting', 'waiting') and time.monotonic() < deadline:
                time.sleep(.01)
        process = types.SimpleNamespace(stdout=StringIO('https://auth.openai.com/codex/device\nABCD-1234\n'),
                                        wait=lambda: 0)
        with patch('codex_login.subprocess.Popen', return_value=process):
            codex_login.start('codex', '.', lambda: True)
            wait_done()
        self.assertEqual(codex_login.snapshot()['state'], 'connected')
        self.assertIsNone(codex_login.snapshot()['code'])
        process = types.SimpleNamespace(stdout=StringIO('error sending request SECRET_VALUE'), wait=lambda: 1)
        with patch('codex_login.subprocess.Popen', return_value=process):
            codex_login.start('codex', '.', lambda: False)
            wait_done()
        self.assertEqual(codex_login.snapshot()['state'], 'failed')
        self.assertNotIn('SECRET_VALUE', str(codex_login.snapshot()))


class RescoreTests(unittest.TestCase):
    def test_replaces_analysis_preserves_history_and_failed_results(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'cv.md').write_text('Updated CV')
            request = root/'request.json'
            job = dict(id='one',title='Engineer',company='Example',location='Berlin',url='https://example.com',description='Python')
            request.write_text(json.dumps({'jobs':[job], 'cv_fingerprint':hashlib.sha256(b'Updated CV').hexdigest()}))
            with patch.object(jp,'ROOT',root), patch.object(jp,'DB_PATH',root/'jobs.db'), patch.object(jp,'OUT',root/'output'):
                con=jp.db()
                con.execute("INSERT INTO jobs(id,title,score,status,analysis,found_at) VALUES('one','Engineer',80,'shortlisted','{}','old-date')")
                con.commit();con.close()
                value=analysis(score=30)
                with patch.object(jp,'process',return_value=(job,value,'low_score',None)):
                    jp.rescore(request)
                con=jp.db()
                self.assertEqual(con.execute("SELECT score,found_at FROM jobs").fetchone(),(30,'old-date'))
                self.assertEqual(con.execute("SELECT score FROM analysis_history").fetchone()[0],80)
                request.write_text(json.dumps({'jobs':[job], 'cv_fingerprint':hashlib.sha256(b'Updated CV').hexdigest()}))
                with patch.object(jp,'process',return_value=(job,None,None,None)):
                    jp.rescore(request)
                self.assertEqual(con.execute("SELECT score FROM jobs").fetchone()[0],30)
                con.close()
