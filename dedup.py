"""Conservative local identity matching. No network requests or AI calls."""
import hashlib
import html
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize(value):
    value = re.sub(r"<[^>]*>", " ", html.unescape(value or ""))
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def canonical(value):
    try:
        url = urlsplit(value or "")
        if url.scheme not in ("http", "https") or not url.hostname or url.username:
            return ""
        # Preserve unknown query parameters: some are vacancy identifiers.
        query = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in
                 ("fbclid", "gclid", "mc_cid", "mc_eid")]
        host = url.netloc.lower()
        return urlunsplit(("https", host, url.path.rstrip("/") or "/", urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def fingerprint(job):
    fields = [normalize(job.get(k)) for k in ("company", "title", "location", "description")]
    # Short descriptions and unspecified locations are weak evidence.
    if any(not x for x in fields) or len(fields[-1]) < 200:
        return None
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS job_sources(
        source_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, url TEXT NOT NULL,
        fingerprint TEXT, payload TEXT NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS sources_url ON job_sources(url)")
    con.execute("CREATE INDEX IF NOT EXISTS sources_fingerprint ON job_sources(fingerprint)")
    con.execute("""CREATE TABLE IF NOT EXISTS duplicate_links(
        duplicate_id TEXT PRIMARY KEY, job_id TEXT NOT NULL)""")
    # Legacy jobs lack descriptions: only source identity or exact URL is safe.
    for row in con.execute("SELECT id,title,company,location,url FROM jobs").fetchall():
        job = dict(zip(("id", "title", "company", "location", "url"), row))
        con.execute("INSERT OR IGNORE INTO job_sources VALUES(?,?,?,?,?)",
                    (job["id"], job["id"], canonical(job["url"]), None, json.dumps(job)))


def collect(con, jobs):
    """Persist all provenance and return one unprocessed candidate per identity."""
    init(con)
    completed = {r[0] for r in con.execute("SELECT id FROM jobs")}
    selected = {}
    merged = reused = 0
    for job in jobs:
        url, digest = canonical(job.get("url")), fingerprint(job)
        match = con.execute("SELECT job_id FROM job_sources WHERE source_id=?", (job["id"],)).fetchone()
        if not match and url:
            match = con.execute("SELECT job_id FROM job_sources WHERE url=? LIMIT 1", (url,)).fetchone()
        if not match and digest:
            match = con.execute("SELECT job_id FROM job_sources WHERE fingerprint=? LIMIT 1", (digest,)).fetchone()
        identity = match[0] if match else job["id"]
        if identity != job["id"]:
            merged += 1
        con.execute("INSERT OR REPLACE INTO job_sources VALUES(?,?,?,?,?)",
                    (job["id"], identity, url, digest, json.dumps(job)))
        if identity in completed:
            reused += 1
            continue
        candidate = dict(job, id=identity)
        if identity not in selected or len(candidate.get("description", "")) > len(selected[identity].get("description", "")):
            selected[identity] = candidate
    # Existing exact-URL duplicates can be hidden without deleting history or drafts.
    for identity, url in con.execute("SELECT id,url FROM jobs").fetchall():
        key = canonical(url)
        if not key:
            continue
        peers = con.execute("""SELECT j.id FROM jobs j JOIN job_sources s ON s.source_id=j.id
            WHERE s.url=? ORDER BY CASE j.status WHEN 'applied' THEN 0 ELSE 1 END,
            j.found_at,j.id""", (key,)).fetchall()
        if peers and identity != peers[0][0]:
            con.execute("INSERT OR REPLACE INTO duplicate_links VALUES(?,?)", (identity, peers[0][0]))
    con.commit()
    return list(selected.values()), {"duplicates": merged, "reused": reused}
