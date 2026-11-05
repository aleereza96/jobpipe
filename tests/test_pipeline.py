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
