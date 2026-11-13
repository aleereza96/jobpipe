"""Portable executable discovery and offline installation checks."""
import importlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

APP = Path(__file__).resolve().parent


def codex_command(config):
    override = os.environ.get('JOBPIPE_CODEX_COMMAND') or config.get('codex_command')
    if override and override != 'codex':
        path = Path(override).expanduser()
        return str((APP / path).resolve()) if '/' in override or '\\' in override else override
    local = APP / '.tools' / 'bin' / 'codex'
    if local.is_file():
        return str(local)
    return shutil.which('codex') or 'codex'


def cli_check(config):
    try:
        command = codex_command(config)
        result = subprocess.run([command, '--version'], capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise ValueError('Codex cannot start. Re-run install.py or rebuild the Docker image.')
        version = result.stdout.strip()
        if not version.startswith('codex-cli ') or len(version) > 120:
            raise ValueError('The selected command is not a compatible Codex CLI.')
        execution = subprocess.run([command, 'exec', '--help'], capture_output=True, text=True, timeout=10)
        login = subprocess.run([command, 'login', '--help'], capture_output=True, text=True, timeout=10)
        required = ('--ephemeral', '--skip-git-repo-check', '--output-schema', '--output-last-message', '--sandbox')
        if execution.returncode or login.returncode or any(flag not in execution.stdout for flag in required) or '--device-auth' not in login.stdout:
            raise ValueError('Codex is missing required features. Re-run install.py or rebuild the Docker image.')
        return {'ok': True, 'message': version + ' · required features available'}
    except FileNotFoundError:
        return {'ok': False, 'message': 'Codex CLI was not found. Run python3 install.py for native setup, or rebuild the Docker image.'}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'message': 'Codex startup timed out. First launch may need OS verification; retry Installation checks, then reinstall if it repeats.'}
    except (OSError, ValueError) as error:
        return {'ok': False, 'message': str(error) if isinstance(error, ValueError) else 'Codex could not start. Check executable permissions, architecture and installation.'}


def diagnostics(data, config):
    checks = [{'name': 'Python', 'ok': sys.version_info >= (3, 10) and os.name == 'posix',
               'message': f'Python {sys.version.split()[0]} on {sys.platform}. Requires Python 3.10+ and macOS/Linux/WSL; use Docker on Windows.'}]
    for module in ('requests', 'reportlab', 'anthropic'):
        try:
            importlib.import_module(module)
            checks.append({'name': module, 'ok': True, 'message': f'{module}: imports successfully'})
        except Exception:
            checks.append({'name': module, 'ok': False, 'message': 'Reinstall requirements.txt using the Python environment that starts Jobpipe.'})
    try:
        data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.jobpipe-check-', dir=data) as directory:
            con = sqlite3.connect(Path(directory) / 'check.db')
            try:
                con.execute('CREATE TABLE check_write(value TEXT)')
                con.commit()
            finally:
                con.close()
        checks.append({'name': 'Data storage', 'ok': True, 'message': 'Data directory and SQLite are writable.'})
    except OSError:
        checks.append({'name': 'Data storage', 'ok': False, 'message': 'Data folder is not writable. Use the default Docker volume or a writable JOBPIPE_DATA_DIR.'})
    except sqlite3.Error:
        checks.append({'name': 'Data storage', 'ok': False, 'message': 'SQLite could not create a database in the data folder.'})
    if config.get('ai_provider', 'codex') == 'codex' or any(a.get('provider') == 'codex' for a in config.get('agents', [])):
        checks.append(dict(name='Codex CLI', **cli_check(config)))
    return {'ok': all(check['ok'] for check in checks), 'checks': checks,
            'message': 'Installation checks only; sign-in and a successful AI request must be verified separately.'}


def migrate_legacy(data, legacy):
    """Import the former project-folder mount once, leaving the original untouched."""
    if not legacy or not (legacy / 'config.json').is_file() or (data / 'config.json').exists():
        return False
    marker = data / '.legacy-importing'
    if any(data.iterdir()) and not marker.exists():
        return False
    marker.touch(mode=0o600)
    names = ('cv.md', 'cv-source.json', 'gmail-client.json', 'inbox', 'output', '.gmail', 'jobs.db', 'config.json')
    for name in names:
        source, dest = legacy / name, data / name
        if not source.exists():
            continue
        if source.is_symlink() or (source.is_dir() and any(path.is_symlink() for path in source.rglob('*'))):
            raise ValueError('Legacy data contains symlinks. Copy your data to a dedicated folder and use JOBPIPE_DATA_PATH.')
        if name == 'jobs.db':
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(dest) as target:
                src.backup(target)
        elif source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            shutil.copyfile(source, dest)
            dest.chmod(0o600)
    marker.unlink()
    return True


if __name__ == '__main__':
    data = Path(os.environ.get('JOBPIPE_DATA_DIR', APP))
    config = data / 'config.json'
    result = diagnostics(data, json.loads((config if config.exists() else APP / 'defaults' / 'config.json').read_text()))
    for check in result['checks']:
        print(('OK' if check['ok'] else 'FAIL') + ' · ' + check['name'] + ': ' + check['message'])
    print(result['message'])
    raise SystemExit(0 if result['ok'] else 1)
