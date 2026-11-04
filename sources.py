"""Extra job sources: Greenhouse + Lever company boards, and email alerts via IMAP."""
import email
import html
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header

from urllib.parse import urlsplit

import requests

TAG = re.compile(r"<[^>]+>")


def clean(raw):
    return re.sub(r"\s+", " ", TAG.sub(" ", html.unescape(raw or ""))).strip()


def loc_ok(location, keywords):
    loc = (location or "").lower()
    return any(k in loc for k in keywords)


def greenhouse(slug, loc_keywords):
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                     params={"content": "true"}, timeout=30)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        if loc_ok(loc, loc_keywords):
            out.append({"id": f"gh-{slug}-{j['id']}", "title": j.get("title", ""),
                        "company": slug, "location": loc,
                        "url": j.get("absolute_url", ""),
                        "description": clean(j.get("content"))})
    return out


def lever(slug, loc_keywords):
    """Tries the global Lever API, then the EU one (many German firms use it)."""
    for host in ("api.lever.co", "api.eu.lever.co"):
        r = requests.get(f"https://{host}/v0/postings/{slug}",
                         params={"mode": "json"}, timeout=30)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        out = []
        for j in r.json():
            loc = (j.get("categories") or {}).get("location", "")
            if loc_ok(loc, loc_keywords):
                out.append({"id": f"lv-{slug}-{j['id']}", "title": j.get("text", ""),
                            "company": slug, "location": loc,
                            "url": j.get("hostedUrl", ""),
                            "posted_at": j.get("createdAt"),
                            "description": clean(j.get("descriptionPlain")
                                                 or j.get("description"))})
        return out
    raise requests.HTTPError("404 on both Lever hosts")


def parse_board(link):
    """Resolve public board URLs without requesting the user-supplied host."""
    url = urlsplit(link.strip())
    hosts = {
        "boards.greenhouse.io": "greenhouse",
        "job-boards.greenhouse.io": "greenhouse",
        "jobs.lever.co": "lever",
        "jobs.eu.lever.co": "lever",
    }
    kind = hosts.get(url.hostname)
    slug = url.path.strip("/").split("/")[0]
    if url.scheme != "https" or not kind or url.username or url.password or url.port or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", slug):
        raise ValueError("Use a public Greenhouse or Lever board URL. For other sites, use Add a posting.")
    return kind, slug.lower()


def check(kind, slug):
    """For the `boards` command: is this slug a real board, and how many jobs?"""
    try:
        n = len((greenhouse if kind == "greenhouse" else lever)(slug, [""]))
        return f"OK ({n} jobs)"
    except Exception as e:
        return f"FAIL ({e})"


def alerts(days, senders):
    """Read job-alert emails (LinkedIn, StepStone...) and return [(subject, [links])].
    Needs GMAIL_ADDRESS and GMAIL_APP_PASSWORD (a Google app password, not your login)."""
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    m.select("INBOX", readonly=True)
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    link_re = re.compile(r'https?://[^\s"<>)]*(?:jobs/view|stellenangebote)[^\s"<>)]*')
    seen, leads = set(), []
    for sender in senders:
        _, data = m.search(None, f'(SINCE {since} FROM "{sender}")')
        for num in data[0].split():
            _, msg_data = m.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = str(make_header(decode_header(msg["Subject"] or "")))
            body = ""
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    body += (part.get_payload(decode=True) or b"").decode(
                        part.get_content_charset() or "utf-8", "ignore")
            links = []
            for link in link_re.findall(html.unescape(body)):
                link = link.split("?")[0]
                if link not in seen:
                    seen.add(link)
                    links.append(link)
            if links:
                leads.append((subject, links))
    m.logout()
    return leads
