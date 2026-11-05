#!/usr/bin/env python3
"""Local Jobpipe dashboard. Standard library HTTP server; never submits applications."""
import argparse
from collections import deque
from contextlib import contextmanager
import csv
import io
import traceback
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
from socketserver import TCPServer
import threading
import time
import secrets

import gmail_alerts
import dedup
import cv_source
import sources
from urllib.parse import parse_qs, urlsplit
import uuid

APP = Path(__file__).resolve().parent
DATA = Path(os.environ.get('JOBPIPE_DATA_DIR', APP)).resolve()
WEB = APP / 'web'
LOCK = threading.RLock()
RUN = {'state': 'idle', 'started': None, 'finished': None, 'exit_code': None}
LOGS = deque(maxlen=500)
PROCESS = None
GMAIL_PENDING = {}
GMAIL_SYNC = threading.Lock()


def init_data():
    DATA.mkdir(parents=True, exist_ok=True)
    for name in ('config.json', 'cv.md'):
        dest = DATA / name
        if not dest.exists():
            dest.write_bytes((APP / 'defaults' / name).read_bytes())
    with connect() as con:
        con.execute("CREATE TABLE IF NOT EXISTS feedback(job_id TEXT PRIMARY KEY, decision TEXT NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL)")
    (DATA / 'inbox').mkdir(exist_ok=True)
    (DATA / 'output').mkdir(exist_ok=True)
    with connect() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, url TEXT,
            score INTEGER, status TEXT, analysis TEXT, found_at TEXT,
            applied_at TEXT, follow_up_at TEXT)''')
        dedup.init(con)


@contextmanager
def connect():
    con = sqlite3.connect(DATA / 'jobs.db', timeout=15)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def atomic_write(path, text):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def validate_config(changes):
    cfg = json.loads((DATA / 'config.json').read_text(encoding='utf-8'))
    numeric = {'min_score': (0, 100), 'min_salary_eur': (0, 1000000),
               'review_limit': (1, 100), 'min_relevance': (0, 23), 'max_llm_jobs_per_run': (1, 200), 'workers': (1, 8),
               'ai_timeout_seconds': (10, 1800), 'arbeitnow_pages': (1, 30)}
    arrays = {'required_keywords', 'include_keywords', 'exclude_keywords', 'location_keywords', 'visa_keywords', 'role_keywords'}
    strings = {'candidate_note', 'anthropic_model'}
    allowed = set(numeric) | arrays | strings | {'sponsorship_required', 'unknown_policy', 'ai_provider', 'codex_model', 'use_arbeitnow', 'boards', 'include_unknown_location', 'include_relocation_outside_locations', 'exclude_german_required'}
    if not isinstance(changes, dict) or set(changes) - allowed:
        raise ValueError('Unrecognized settings')
    for key, value in changes.items():
        if key in numeric:
            low, high = numeric[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{key} must be a whole number between {low} and {high}')
        elif key in arrays:
            if not isinstance(value, list) or len(value) > 100 or any(not isinstance(x, str) or not x.strip() or len(x) > 200 for x in value):
                raise ValueError(f'{key} must contain nonempty keywords')
        elif key in strings:
            if not isinstance(value, str) or len(value) > 6000:
                raise ValueError(f'Invalid {key}')
        elif key == 'unknown_policy' and value not in ('review', 'exclude'):
            raise ValueError('Invalid unknown policy')
        elif key == 'sponsorship_required' and type(value) is not bool:
            raise ValueError('Invalid sponsorship setting')
        elif key == 'ai_provider' and value not in ('codex', 'anthropic'):
            raise ValueError('Choose Codex or Anthropic')
        elif key == 'codex_model' and value is not None and (not isinstance(value, str) or len(value) > 100):
            raise ValueError('Invalid Codex model')
        elif key in ('use_arbeitnow', 'include_unknown_location', 'include_relocation_outside_locations', 'exclude_german_required') and type(value) is not bool:
            raise ValueError('Invalid source setting')
        elif key == 'boards':
            if not isinstance(value, dict) or set(value) != {'greenhouse', 'lever'}:
                raise ValueError('Both Greenhouse and Lever boards are required')
            if any(not isinstance(items, list) or len(items) > 100 or any(not isinstance(x, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', x) for x in items) for items in value.values()):
                raise ValueError('Board names may contain letters, numbers, underscores and hyphens')
    cfg.update(changes)
    return cfg


def watch(process):
    try:
        for line in process.stdout:
            with LOCK:
                if line.startswith('DEDUP_COUNTS '):
                    RUN['dedup'] = json.loads(line[len('DEDUP_COUNTS '):])
                if line.startswith('SEARCH_COUNTS '):
                    RUN['counts'] = json.loads(line[len('SEARCH_COUNTS '):])
                else:
                    LOGS.append(line.rstrip()[:2000])
        code = process.wait()
        with LOCK:
            RUN.update(state=('stopped' if RUN['state'] == 'stopping' else 'completed' if code == 0 else 'failed'),
                       exit_code=code, finished=datetime.now().isoformat())
    except Exception as exc:
        with LOCK:
            LOGS.append(f'Could not read progress: {exc}')
            RUN.update(state='failed', finished=datetime.now().isoformat())


def start_run():
    global PROCESS
    with LOCK:
        if RUN['state'] in ('running', 'stopping'):
            raise ValueError('A search is already running')
        config = json.loads((DATA / 'config.json').read_text())
        if config.get('ai_provider', 'codex') == 'codex':
            status = auth_status()
            if not status['ready']:
                raise ValueError(status['message'])
        env = dict(os.environ, JOBPIPE_DATA_DIR=str(DATA), PYTHONUNBUFFERED='1', PYTHONUTF8='1')
        PROCESS = subprocess.Popen([sys.executable, '-u', str(APP / 'jobpipe.py'), 'run'],
                                   cwd=APP, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                   start_new_session=True)
        LOGS.clear()
        RUN.update(counts=None, state='running', started=datetime.now().isoformat(), finished=None, exit_code=None)
        threading.Thread(target=watch, args=(PROCESS,), daemon=True).start()


def stop_run():
    with LOCK:
        if PROCESS is not None and PROCESS.poll() is None:
            RUN['state'] = 'stopping'
            try:
                if os.name == 'posix':
                    os.killpg(PROCESS.pid, signal.SIGTERM)
                else:
                    PROCESS.terminate()
            except ProcessLookupError:
                pass


def auth_status():
    config = json.loads((DATA / 'config.json').read_text())
    try:
        result = subprocess.run([config.get('codex_command', 'codex'), 'login', 'status'],
                                capture_output=True, text=True, encoding='utf-8', timeout=10)
        ready = result.returncode == 0
        return {'ready': ready, 'message': 'Codex is connected' if ready else 'Connect Codex in Settings before starting a search.'}
    except FileNotFoundError:
        return {'ready': False, 'message': 'Codex CLI is not installed. Use the Docker setup or install the CLI.'}
    except subprocess.TimeoutExpired:
        return {'ready': False, 'message': 'Codex status check timed out. Try again.'}


def job_rows(query):
    conditions, params = ["id NOT IN (SELECT duplicate_id FROM duplicate_links)", "id NOT IN (SELECT job_id FROM feedback WHERE decision='dismissed')"], []
    if query.get('status', [''])[0] in ('shortlisted', 'applied', 'skipped', 'low_score'):
        conditions.append('status=?'); params.append(query['status'][0])
    if query.get('due', [''])[0] == '1':
        conditions.append("status='applied' AND follow_up_at<=?")
        params.append(datetime.now().isoformat(timespec='seconds'))
    search = query.get('q', [''])[0][:200]
    if search:
        conditions.append('(title LIKE ? OR company LIKE ? OR location LIKE ?)')
        params.extend(['%' + search + '%'] * 3)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    offset = max(0, min(100000, int(query.get('offset', ['0'])[0])))
    config = json.loads((DATA / 'config.json').read_text())
    limit = config.get('review_limit', 10) if query.get('review', ['0'])[0] == '1' else 100
    with connect() as con:
        total = con.execute('SELECT count(*) FROM jobs' + where, params).fetchone()[0]
        rows = con.execute('SELECT id,title,company,location,url,score,status,analysis,found_at,applied_at,follow_up_at FROM jobs' + where + ' ORDER BY score DESC, found_at DESC LIMIT ? OFFSET ?', [*params, limit, offset]).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item['analysis'] = json.loads(item['analysis'] or '{}')
        except json.JSONDecodeError:
            item['analysis'] = {}
        with connect() as con:
            item['sources'] = [dict(r) for r in con.execute(
                'SELECT source_id,url FROM job_sources WHERE job_id=?', (item['id'],))]
        result.append(item)
    return {'jobs': result, 'total': total, 'limit': limit, 'offset': offset}


class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        # A loopback dashboard doesn't need reverse DNS; broken host DNS must not delay startup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value, status=200, content_type='application/json; charset=utf-8', filename=None):
        body = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, (dict, list)) else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        self.end_headers()
        self.wfile.write(body)

    def guard(self, mutate=False):
        host = self.headers.get('Host', '')
        hostname = host.split(':')[0]
        if hostname not in ('localhost', '127.0.0.1'):
            self.reply({'error': 'Open this dashboard using localhost.'}, 403); return False
        if mutate and (self.headers.get('X-Jobpipe') != '1' or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
            self.reply({'error': 'Invalid dashboard request'}, 403); return False
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host:
            self.reply({'error': 'Requests must come from this dashboard'}, 403); return False
        return True

    def do_GET(self):
        if not self.guard(): return
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == '/api/boards':
                config = json.loads((DATA / 'config.json').read_text())
                return self.reply(config.get('boards', {}))
            if parsed.path == '/api/gmail':
                return self.reply(gmail_alerts.status(DATA))
            if parsed.path == '/api/gmail/callback':
                state = query.get('state', [''])[0]
                with LOCK:
                    pending = GMAIL_PENDING.pop(state, None)
                if not pending or time.monotonic() > pending[2]:
                    raise ValueError('Google sign-in expired. Start again from Job alerts.')
                redirect, verifier, _ = pending
                if redirect != 'http://' + self.headers['Host'] + parsed.path:
                    raise ValueError('Google sign-in returned to a different dashboard address.')
                code = query.get('code', [''])[0]
                if not code:
                    raise ValueError('Google sign-in was canceled. Return to Job alerts to retry.')
                gmail_alerts.connect_account(DATA, redirect, code, verifier)
                self.send_response(303)
                self.send_header('Location', '/#alerts')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return
            if parsed.path == '/api/health':
                return self.reply({'ok': True})
            if parsed.path == '/api/jobs':
                return self.reply(job_rows(query))
            if parsed.path == '/api/stats':
                with connect() as con:
                    counts = {r[0]: r[1] for r in con.execute('SELECT status,count(*) FROM jobs GROUP BY status')}
                    due = con.execute("SELECT count(*) FROM jobs WHERE status='applied' AND follow_up_at<=?", (datetime.now().isoformat(),)).fetchone()[0]
                return self.reply({'counts': counts, 'due': due, 'total': sum(counts.values())})
            if parsed.path == '/api/run':
                with LOCK: snapshot = dict(RUN, logs=list(LOGS))
                return self.reply(snapshot)
            if parsed.path == '/api/auth':
                return self.reply(auth_status())
            if parsed.path == '/api/settings':
                cv = cv_source.load(DATA)
                return self.reply({'config': json.loads((DATA / 'config.json').read_text()),
                                   'cv': cv['source'], 'cv_format': cv['format']})
            if parsed.path == '/api/draft':
                job_id = query.get('id', [''])[0]
                with connect() as con:
                    if not con.execute('SELECT id FROM jobs WHERE id=?', (job_id,)).fetchone():
                        raise FileNotFoundError('Job not found')
                name = re.sub(r'[^a-zA-Z0-9_-]+', '-', job_id)[:80]
                target = DATA / 'output' / name / 'application.md'
                text = target.read_text(encoding='utf-8') if target.is_file() else ''
                return self.reply({'text': text})
            if parsed.path == '/api/export':
                stream = io.StringIO(newline='')
                writer = csv.writer(stream)
                writer.writerow(['id', 'score', 'title', 'company', 'url', 'status', 'visa_in_posting', 'summary', 'gaps'])
                with connect() as con:
                    rows = con.execute("SELECT * FROM jobs WHERE status IN ('shortlisted','applied') ORDER BY score DESC").fetchall()
                for row in rows:
                    a = json.loads(row['analysis'] or '{}')
                    writer.writerow([row['id'], row['score'], row['title'], row['company'], row['url'], row['status'], a.get('visa_hint', ''), a.get('summary', ''), '; '.join(a.get('gaps', []))])
                return self.reply(stream.getvalue().encode('utf-8'), content_type='text/csv; charset=utf-8', filename='review.csv')
            static = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}.get(parsed.path)
            if static:
                return self.reply((WEB / static).read_bytes(), content_type=mimetypes.guess_type(static)[0] + '; charset=utf-8')
            self.reply({'error': 'Not found'}, 404)
        except FileNotFoundError as exc:
            self.reply({'error': str(exc)}, 404)
        except (ValueError, TypeError) as exc:
            self.reply({'error': str(exc)}, 400)
        except Exception:
            traceback.print_exc()
            self.reply({'error': 'Could not read local data. Check the dashboard logs.'}, 500)

    def do_POST(self):
        if not self.guard(mutate=True): return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 700000: raise ValueError('Request is empty or too large')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict): raise ValueError('Expected an object')
            path = urlsplit(self.path).path
            if path == '/api/feedback':
                job_id, decision, reason = body.get('id'), body.get('decision'), body.get('reason', '')
                if not isinstance(job_id, str) or decision not in ('interested', 'dismissed', 'clear') or not isinstance(reason, str) or len(reason) > 500:
                    raise ValueError('Invalid feedback')
                with connect() as con:
                    if not con.execute('SELECT 1 FROM jobs WHERE id=?', (job_id,)).fetchone():
                        raise ValueError('Job not found')
                    if decision == 'clear':
                        con.execute('DELETE FROM feedback WHERE job_id=?', (job_id,))
                    else:
                        con.execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?,?)',
                                    (job_id, decision, reason, datetime.now().isoformat()))
                return self.reply({'ok': True})
            if path == '/api/cv/review':
                from cv_review import review
                config = json.loads((DATA / 'config.json').read_text(encoding='utf-8'))
                try:
                    result = review(config, body.get('action'), body.get('cv'), body.get('format'), body.get('prompt'))
                except (RuntimeError, OSError) as exc:
                    return self.reply({'error': str(exc)}, 502)
                return self.reply(result)
            if path == '/api/cv/pdf':
                job_id = body.get('id')
                if not isinstance(job_id, str):
                    raise ValueError('Choose a job first.')
                with connect() as con:
                    if not con.execute('SELECT id FROM jobs WHERE id=?', (job_id,)).fetchone():
                        return self.reply({'error': 'Job not found'}, 404)
                name = re.sub(r'[^a-zA-Z0-9_-]+', '-', job_id)[:80]
                target = DATA / 'output' / name / 'application.md'
                if not target.is_file():
                    return self.reply({'error': 'This job has no tailored draft yet.'}, 404)
                from cv_pdf import render
                pdf = render(cv_source.active_markdown(DATA),
                             target.read_text(encoding='utf-8'))
                return self.reply(pdf, content_type='application/pdf',
                                  filename=f'tailored-cv-{name}.pdf')
            if path in ('/api/boards/preview', '/api/boards/save', '/api/boards/remove'):
                link = body.get('url')
                if not isinstance(link, str) or len(link) > 2048:
                    raise ValueError('Enter a job board URL.')
                kind, slug = sources.parse_board(link)
                if path.endswith('/remove'):
                    with LOCK:
                        config = json.loads((DATA / 'config.json').read_text())
                        boards = config.setdefault('boards', {})
                        boards[kind] = [item for item in boards.get(kind, []) if item != slug]
                        atomic_write(DATA / 'config.json', json.dumps(config, indent=2) + '\n')
                    return self.reply({'ok': True})
                try:
                    jobs = getattr(sources, kind)(slug, [''])
                except Exception:
                    raise ValueError('Could not load this public board. Check its URL or use Add a posting.') from None
                if path.endswith('/save'):
                    with LOCK:
                        config = json.loads((DATA / 'config.json').read_text())
                        boards = config.setdefault('boards', {})
                        items = boards.setdefault(kind, [])
                        if slug not in items:
                            items.append(slug)
                            atomic_write(DATA / 'config.json', json.dumps(config, indent=2) + '\n')
                return self.reply({'count': len(jobs), 'jobs': [
                    {'title': job['title'], 'location': job['location']} for job in jobs[:10]
                ]})
            if path == '/api/gmail/setup':
                client = body.get('client')
                installed = client.get('installed') if isinstance(client, dict) else None
                if not isinstance(installed, dict) or any(
                    not isinstance(installed.get(key), str) or not installed[key].strip() or len(installed[key]) > 2000
                    for key in ('client_id', 'client_secret')):
                    raise ValueError('Upload the JSON downloaded for a Google OAuth Desktop app.')
                if not installed['client_id'].endswith('.apps.googleusercontent.com'):
                    raise ValueError('Invalid Google client ID.')
                with LOCK:
                    with gmail_alerts.database(DATA) as con:
                        if con.execute('SELECT 1 FROM accounts LIMIT 1').fetchone():
                            raise ValueError('Disconnect existing Gmail accounts before replacing the Google app.')
                    target = DATA / 'gmail-client.json'
                    temp = target.with_suffix('.json.tmp')
                    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, 'w') as stream:
                        json.dump({'installed': {key: installed[key] for key in ('client_id', 'client_secret')}}, stream)
                    os.chmod(temp, 0o600)
                    temp.replace(target)
                    GMAIL_PENDING.clear()
                return self.reply({'ok': True})
            if path == '/api/gmail/connect':
                redirect = 'http://' + self.headers['Host'] + '/api/gmail/callback'
                state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
                url = gmail_alerts.authorize(DATA, redirect, state, verifier)
                with LOCK:
                    now = time.monotonic()
                    for key in list(GMAIL_PENDING):
                        if GMAIL_PENDING[key][2] < now:
                            del GMAIL_PENDING[key]
                    GMAIL_PENDING[state] = (redirect, verifier, now + 600)
                return self.reply({'url': url})
            if path == '/api/gmail/sync':
                if not GMAIL_SYNC.acquire(blocking=False):
                    raise ValueError('An alert import is already running.')
                try:
                    return self.reply(gmail_alerts.sync(DATA))
                finally:
                    GMAIL_SYNC.release()
            if path == '/api/gmail/disconnect':
                with gmail_alerts.database(DATA) as con:
                    con.execute('DELETE FROM accounts WHERE email=?', (body.get('email'),))
                return self.reply({'ok': True})
            if path == '/api/gmail/description':
                description = body.get('description')
                if not isinstance(description, str) or not description.strip() or len(description) > 12000:
                    raise ValueError('Enter a job description of up to 12,000 characters.')
                with gmail_alerts.database(DATA) as con:
                    changed = con.execute("UPDATE leads SET description=? WHERE id=? AND description=''",
                                          (description.strip(), body.get('id'))).rowcount
                if not changed:
                    raise ValueError('This alert is already ready or was removed.')
                return self.reply({'ok': True})
            if path == '/api/run/start':
                start_run(); return self.reply({'ok': True}, 202)
            if path == '/api/run/stop':
                stop_run(); return self.reply({'ok': True})
            if path == '/api/settings':
                with LOCK:
                    if RUN['state'] in ('running', 'stopping'): raise ValueError('Wait for the search to finish before changing settings')
                    cfg = validate_config(body.get('config', {}))
                    cv = body.get('cv')
                    cv_format = body.get('cv_format', 'md')
                    if cv is not None:
                        cv_source.as_markdown(cv, cv_format)
                    if 'config' in body:
                        atomic_write(DATA / 'config.json', json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
                    if cv is not None:
                        atomic_write(DATA / 'cv-source.json', json.dumps(
                            {'format': cv_format, 'source': cv}, ensure_ascii=False) + '\n')
                return self.reply({'ok': True})
            if path == '/api/inbox':
                fields = {}
                for key in ('title', 'company', 'url', 'description'):
                    value = body.get(key, '')
                    if not isinstance(value, str): raise ValueError('Posting fields must be text')
                    fields[key] = value.strip()
                if not fields['title'] or not fields['description']: raise ValueError('Add a title and job description')
                if fields['url'] and urlsplit(fields['url']).scheme not in ('http', 'https'): raise ValueError('Use an http or https posting link')
                if any('\n' in fields[key] or '|' in fields[key] for key in ('title', 'company', 'url')): raise ValueError('Title, company and link must each fit on one line without |')
                file = DATA / 'inbox' / (uuid.uuid4().hex + '.txt')
                atomic_write(file, f"{fields['title']} | {fields['company']} | {fields['url']}\n{fields['description']}\n")
                return self.reply({'ok': True}, 201)
            if path == '/api/applied':
                job_id = body.get('id')
                if not isinstance(job_id, str): raise ValueError('Choose a job')
                now = datetime.now()
                with LOCK, connect() as con:
                    row = con.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
                    if not row: raise ValueError('Job not found')
                    if row['status'] not in ('shortlisted', 'applied'): raise ValueError('Only shortlisted jobs can be marked applied')
                    if row['status'] != 'applied':
                        con.execute("UPDATE jobs SET status='applied',applied_at=?,follow_up_at=? WHERE id=?", (now.isoformat(timespec='seconds'), (now + timedelta(days=7)).isoformat(timespec='seconds'), job_id))
                return self.reply({'ok': True})
            self.reply({'error': 'Not found'}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.reply({'error': str(exc)}, 400)
        except Exception:
            traceback.print_exc()
            self.reply({'error': 'Could not save this change. Check the dashboard logs.'}, 500)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    init_data()
    server = LocalServer((args.host, args.port), Handler)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f'Jobpipe dashboard: http://localhost:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_run()
        server.server_close()
