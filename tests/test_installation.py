import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import runtime_support as runtime


class InstallationTests(unittest.TestCase):
    def test_executable_resolution_survives_other_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            tool = root / '.tools' / 'bin' / 'codex'
            tool.parent.mkdir(parents=True)
            tool.touch()
            with patch.object(runtime, 'APP', root), patch.dict(os.environ, {'JOBPIPE_CODEX_COMMAND': ''}):
                self.assertEqual(runtime.codex_command({}), str(tool))
                self.assertEqual(runtime.codex_command({'codex_command': './custom/codex'}), str(root / 'custom' / 'codex'))
                with patch.dict(os.environ, {'JOBPIPE_CODEX_COMMAND': '/opt/custom/codex'}):
                    self.assertEqual(runtime.codex_command({'codex_command': '/old-machine/codex'}), '/opt/custom/codex')

    def test_cli_features_and_broken_install(self):
        version = subprocess.CompletedProcess([], 0, stdout='codex-cli 0.169.0\n')
        execution = subprocess.CompletedProcess([], 0, stdout='--ephemeral --skip-git-repo-check --output-schema --output-last-message --sandbox')
        login = subprocess.CompletedProcess([], 0, stdout='--device-auth')
        with patch.object(runtime.subprocess, 'run', side_effect=[version, execution, login]):
            self.assertTrue(runtime.cli_check({})['ok'])
        with patch.object(runtime.subprocess, 'run', side_effect=[version, execution, subprocess.CompletedProcess([], 0, stdout='old CLI')]):
            self.assertIn('missing required features', runtime.cli_check({})['message'])
        with patch.object(runtime.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertFalse(runtime.cli_check({})['ok'])
        with patch.object(runtime.subprocess, 'run', side_effect=PermissionError):
            self.assertFalse(runtime.cli_check({})['ok'])

    def test_legacy_import_is_non_destructive_and_one_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, legacy = root / 'data', root / 'legacy'
            data.mkdir(); legacy.mkdir()
            (legacy / 'config.json').write_text(json.dumps({'location_keywords': ['Berlin']}))
            (legacy / 'cv-source.json').write_text(json.dumps({'format': 'md', 'source': 'My saved CV'}))
            (legacy / '.gmail').mkdir()
            (legacy / '.gmail' / 'token.json').write_text('private-example')
            (legacy / 'server.py').write_text('Do not copy code')
            with sqlite3.connect(legacy / 'jobs.db') as con:
                con.execute('CREATE TABLE example(value TEXT)')
                con.execute("INSERT INTO example VALUES('saved job')")
            self.assertTrue(runtime.migrate_legacy(data, legacy))
            self.assertFalse((data / 'server.py').exists())
            self.assertEqual((legacy / '.gmail' / 'token.json').read_text(), 'private-example')
            with sqlite3.connect(data / 'jobs.db') as con:
                self.assertEqual(con.execute('SELECT value FROM example').fetchone()[0], 'saved job')
            (data / 'cv-source.json').write_text('New CV')
            self.assertFalse(runtime.migrate_legacy(data, legacy))
            self.assertEqual((data / 'cv-source.json').read_text(), 'New CV')

    def test_legacy_import_does_not_overwrite_unrelated_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, legacy = root / 'data', root / 'legacy'
            data.mkdir(); legacy.mkdir()
            (legacy / 'config.json').write_text('{}')
            (data / 'cv.md').write_text('Existing CV')
            self.assertFalse(runtime.migrate_legacy(data, legacy))
            self.assertEqual((data / 'cv.md').read_text(), 'Existing CV')
