"""Read-only Gmail job alerts and local review queue."""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import hashlib
from html.parser import HTMLParser
import json
import re
import secrets
import sqlite3
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN = "https://oauth2.googleapis.com/token"
SENDERS = ("linkedin.com", "glassdoor.com", "indeed.com", "stepstone.de", "stepstone.com")


@contextmanager
def database(root):
    folder = root / ".gmail"
    folder.mkdir(mode=0o700, exist_ok=True)
    con = sqlite3.connect(folder / "alerts.db", timeout=15)
    con.row_factory = sqlite3.Row
    try:
        with con:
            con.execute("CREATE TABLE IF NOT EXISTS accounts(email TEXT PRIMARY KEY, refresh TEXT NOT NULL, synced TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY, title TEXT, url TEXT, source TEXT, description TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS seen(email TEXT, message TEXT, PRIMARY KEY(email,message))")
            yield con
    finally:
        con.close()


def credentials(root):
    try:
        client = json.loads((root / "gmail-client.json").read_text())["installed"]
        return {key: client[key] for key in ("client_id", "client_secret")}
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Add a Google OAuth Desktop client file named gmail-client.json to the Jobpipe folder.") from None


def authorize(root, redirect, state, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": credentials(root)["client_id"], "redirect_uri": redirect,
        "scope": SCOPE, "response_type": "code", "access_type": "offline",
        "prompt": "consent select_account", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })


def request_json(url, *, token=None, data=None, params=None):
    try:
        if data is not None:
            result = requests.post(url, data=data, timeout=15, allow_redirects=False)
        else:
            result = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                                  params=params, timeout=15, allow_redirects=False)
        if result.status_code != 200:
            raise ValueError(f"Google returned HTTP {result.status_code}. Check access or reconnect the account.")
        return result.json()
    except requests.RequestException:
        raise ValueError("Could not reach Google. Try again.") from None


def connect_account(root, redirect, code, verifier):
    result = request_json(TOKEN, data=dict(credentials(root), grant_type="authorization_code",
                                          redirect_uri=redirect, code=code, code_verifier=verifier))
    refresh = result.get("refresh_token")
    if not refresh:
        raise ValueError("Google did not grant offline access. Reconnect the account.")
    email = request_json(API + "/profile", token=result["access_token"])["emailAddress"].lower()
    with database(root) as con:
        con.execute("INSERT INTO accounts(email,refresh) VALUES(?,?) "
                    "ON CONFLICT(email) DO UPDATE SET refresh=excluded.refresh", (email, refresh))


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data):
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.label)))
            self.href = None


def canonical(link):
    try:
        url = urlsplit(link)
        if url.scheme != "https" or url.username or url.password or url.port:
            return None
        host = url.hostname or ""
        query = parse_qs(url.query)
        for domain in SENDERS:
            if host != domain and not host.endswith("." + domain):
                continue
            if domain == "linkedin.com":
                match = re.fullmatch(r"/jobs/view/(?:[^/]*-)?(\d+)/?", url.path)
                if match:
                    return f"https://www.linkedin.com/jobs/view/{match[1]}/", "LinkedIn"
                if url.path.rstrip("/") == "/comm/jobs/view" and query.get("jobId", [""])[0].isdigit():
                    return f"https://www.linkedin.com/jobs/view/{query['jobId'][0]}/", "LinkedIn"
                match = re.fullmatch(r"/comm/jobs/view/(\d+)/?", url.path)
                if match:
                    return f"https://www.linkedin.com/jobs/view/{match[1]}/", "LinkedIn"
            if domain == "indeed.com" and url.path in ("/viewjob", "/rc/clk", "/pagead/clk"):
                key = (query.get("jk") or query.get("vjk") or [""])[0]
                if re.fullmatch(r"[a-fA-F0-9]{8,32}", key):
                    return f"https://www.indeed.com/viewjob?jk={key}", "Indeed"
            if domain == "glassdoor.com" and url.path.lower().startswith(("/job-listing/", "/partner/joblisting.htm")):
                key = (query.get("jobListingId") or query.get("jl") or [""])[0]
                if key.isdigit():
                    return f"https://www.glassdoor.com/partner/jobListing.htm?jobListingId={key}", "Glassdoor"
                if url.path.lower().startswith("/job-listing/"):
                    return "https://www.glassdoor.com" + url.path.rstrip("/"), "Glassdoor"
            if domain.startswith("stepstone.") and url.path.startswith("/stellenangebote--"):
                return f"https://www.{domain}{url.path.rstrip('/')}", "StepStone"
    except ValueError:
        pass
    return None


def parse_message(raw):
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    sender = parseaddr(msg.get("From", ""))[1].lower().rpartition("@")[2]
    if not any(sender == domain or sender.endswith("." + domain) for domain in SENDERS):
        return []
    plain, html = msg.get_body(preferencelist=("plain",)), msg.get_body(preferencelist=("html",))
    body = plain.get_content() if plain else ""
    parser = Anchors()
    if html:
        parser.feed(html.get_content())
    links = parser.links + [(x.rstrip(".,)"), "") for x in re.findall(r"https://[^\s<>\"]+", body)]
    leads = {}
    for link, label in links:
        normalized = canonical(link)
        if not normalized:
            continue
        url, source = normalized
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        title = " ".join(label.split())[:200]
        if not title or title.lower() in {"view job", "apply", "see job", "apply now"}:
            title = str(msg.get("Subject") or f"{source} job alert")[:200]
        leads.setdefault(key, [key, title, url, source, ""])
    # Only score a single listing with an explicitly identified description.
    if len(leads) == 1:
        match = re.search(r"(?im)^job description[ :]*\n([\s\S]+?)(?:\n(?:apply now|unsubscribe)\b|\Z)", body)
        if match and len(match[1].strip()) >= 250:
            next(iter(leads.values()))[4] = match[1].strip()[:12000]
    return list(leads.values())


def status(root):
    try:
        credentials(root)
        configured = True
    except ValueError:
        configured = False
    with database(root) as con:
        return {"configured": configured,
                "accounts": [dict(row) for row in con.execute("SELECT email,synced FROM accounts ORDER BY email")],
                "leads": [dict(row) for row in con.execute(
                    "SELECT id,title,url,source,description<>'' AS ready FROM leads ORDER BY rowid DESC LIMIT 100")]}


def sync(root):
    with database(root) as con:
        accounts = con.execute("SELECT * FROM accounts").fetchall()
    added, errors = 0, []
    for account in accounts:
        try:
            added += sync_account(root, account)
        except (ValueError, KeyError) as exc:
            errors.append(f"{account['email']}: {exc}")
    return {"added": added, "errors": errors}


def sync_account(root, account):
    token = request_json(TOKEN, data=dict(credentials(root), grant_type="refresh_token",
                                         refresh_token=account["refresh"]))["access_token"]
    query = "newer_than:14d {" + " ".join(f"from:{domain}" for domain in SENDERS) + "}"
    params = {"q": query, "maxResults": 50}
    added = 0
    while True:
        page = request_json(API + "/messages", token=token, params=params)
        for message in page.get("messages", []):
            with database(root) as con:
                if con.execute("SELECT 1 FROM seen WHERE email=? AND message=?",
                               (account["email"], message["id"])).fetchone():
                    continue
            raw = request_json(API + "/messages/" + message["id"], token=token, params={"format": "raw"})["raw"]
            leads = parse_message(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            with database(root) as con:
                current = con.execute("SELECT refresh FROM accounts WHERE email=?", (account["email"],)).fetchone()
                if not current or current["refresh"] != account["refresh"]:
                    return added
                for lead in leads:
                    added += con.execute("INSERT OR IGNORE INTO leads VALUES(?,?,?,?,?)", lead).rowcount
                    if lead[4]:
                        con.execute("UPDATE leads SET description=? WHERE id=? AND description=''", (lead[4], lead[0]))
                con.execute("INSERT OR IGNORE INTO seen VALUES(?,?)", (account["email"], message["id"]))
        if not page.get("nextPageToken"):
            break
        params["pageToken"] = page["nextPageToken"]
    with database(root) as con:
        con.execute("UPDATE accounts SET synced=? WHERE email=? AND refresh=?",
                    (datetime.now(timezone.utc).isoformat(), account["email"], account["refresh"]))
    return added


def postings(root):
    with database(root) as con:
        return [{"id": "mail-" + row["id"], "title": row["title"], "company": "",
                 "location": "", "url": row["url"], "description": row["description"]}
                for row in con.execute("SELECT * FROM leads WHERE description<>''")]
