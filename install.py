"""Native installer: isolated Python environment and project-local Codex CLI."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('codex', 'anthropic'), default='codex')
    args = parser.parse_args()
    if sys.version_info < (3, 10) or os.name != 'posix':
        parser.exit(1, 'Use Python 3.10+ on macOS/Linux/WSL 2, or use Docker on Windows.\n')
    try:
        if args.provider == 'codex':
            node, npm = shutil.which('node'), shutil.which('npm')
            if not node or not npm:
                raise ValueError('Install Node.js 22 LTS (including npm), reopen the terminal, then retry. Docker includes both.')
            major = int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0])
            if major < 22:
                raise ValueError('Use Node.js 22 or newer, then retry.')
        python = ROOT / '.venv' / 'bin' / 'python'
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
        print('Installing Python dependencies into .venv…', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
        if args.provider == 'codex':
            version = (ROOT / 'CODEX_VERSION').read_text().strip()
            if not re.fullmatch(r'\d+\.\d+\.\d+', version):
                raise ValueError('CODEX_VERSION must contain an exact stable version.')
            print(f'Installing Codex {version} locally. Its platform binary is a large download; allow several minutes on a slow connection.', flush=True)
            subprocess.run([npm, 'install', '--global', '--prefix', str(ROOT / '.tools'),
                            '--cache', str(ROOT / '.tools' / 'npm-cache'), '--include=optional',
                            '--no-audit', '--no-fund', '@openai/codex@' + version], check=True)
            subprocess.run([str(python), str(ROOT / 'runtime_support.py')], check=True)
        print('Installation complete. Start Jobpipe from this folder: .venv/bin/python server.py')
        print('Open http://localhost:8787 and connect your provider in Preferences.')
        if args.provider == 'anthropic':
            print('Set ANTHROPIC_API_KEY before starting; select Anthropic in Preferences.')
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Installation did not finish: {error}\nCheck the preceding error and retry. No saved CV or preferences were replaced.\n')


if __name__ == '__main__':
    main()
