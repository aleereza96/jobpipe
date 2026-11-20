"""Bounded imports from explicitly supported public job websites. No AI calls."""
from itertools import islice
import http.client
import ipaddress
import socket
import ssl
import hashlib
import json
import re
import time
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from sources import clean
from search_rank import COUNTRIES

SITES = {
    'germantechjobs': dict(name='GermanTechJobs', url='https://germantechjobs.de/en', feed='https://germantechjobs.de/rss'),
    'devjobs': dict(name='DEVjobs Germany', url='https://en.devjobs.de/', listing='https://en.devjobs.de/jobs/search'),
    'nextleveljobs': dict(name='Next Level Jobs · selected countries', url='https://nextleveljobs.eu/', listing='https://nextleveljobs.eu/country/de'),
    'berlinstartupjobs': dict(name='Berlin Startup Jobs · Engineering', url='https://berlinstartupjobs.com/engineering/', feed='https://berlinstartupjobs.com/engineering/feed/'),
}
MAX_DETAILS = 30
MAX_ITEMS = 100
MAX_BYTES = 5_000_000


class AccessRestricted(ValueError):
    pass


def safe_url(url, base):
    """Only same-host HTTPS links; never follow arbitrary feed URLs or redirects."""
    full = urljoin(base, url)
    p = urlsplit(full)
    if p.scheme != 'https' or p.hostname != urlsplit(base).hostname or p.username or p.password or p.port:
        raise ValueError('Source returned an unsupported job link')
    return urlunsplit((p.scheme, p.netloc, p.path, '', ''))


def read(url):
    with requests.get(url, timeout=(5, 15), allow_redirects=False, stream=True,
                      headers={'User-Agent': 'Jobpipe/1.0 (personal job search)'}) as response:
        if response.status_code in (401, 403, 429) or 300 <= response.status_code < 400:
            raise AccessRestricted('Website restricted automated access. Open it in your browser or use Add a posting.')
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('Source response exceeded the import size limit')
            chunks.append(chunk)
        text = b''.join(chunks).decode('utf-8', 'replace')
        if '_cf_chl_opt' in text or 'challenge-platform' in text:
            raise AccessRestricted('Website requires browser verification. Use Add a posting for now.')
        return text


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links, self.structured, self.feeds = [], [], []
        self.script = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and 'alternate' in attrs.get('rel', '').split() and attrs.get('type') in ('application/rss+xml', 'application/atom+xml') and attrs.get('href'):
            self.feeds.append(attrs['href'])
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.script = ''

    def handle_data(self, text):
        if self.script is not None:
            self.script += text

    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            try:
                self.structured.append(json.loads(self.script))
            except ValueError:
                pass
            self.script = None


def postings(value):
    if isinstance(value, list):
        for item in value:
            yield from postings(item)
    elif isinstance(value, dict):
        types = value.get('@type') or []
        if 'JobPosting' in ([types] if isinstance(types, str) else types):
            yield value
        for key in ('@graph', 'itemListElement', 'item'):
            yield from postings(value.get(key))


def normalize(post, url, site):
    title, description = clean(post.get('title')), clean(post.get('description'))
    org = post.get('hiringOrganization') or {}
    company = clean(org.get('name')) if isinstance(org, dict) else ''
    if not title or not company or len(description) < 150:
        raise ValueError('Listing has no complete public job description')
    expires = post.get('validThrough')
    if expires:
        try:
            expiry = datetime.fromisoformat(expires.replace('Z', '+00:00'))
            if (expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry) < datetime.now(timezone.utc):
                return None
        except (ValueError, TypeError, AttributeError):
            pass
    locations = post.get('jobLocation') or []
    locations = locations if isinstance(locations, list) else [locations]
    names = []
    for place in locations:
        address = place.get('address', {}) if isinstance(place, dict) else {}
        if isinstance(address, str):
            names.append(address)
        elif isinstance(address, dict):
            parts = []
            for key in ('addressLocality', 'addressRegion', 'addressCountry'):
                part = address.get(key)
                if isinstance(part, dict):
                    part = part.get('name')
                if isinstance(part, str) and part:
                    parts.append(part)
            names.append(', '.join(parts))
    if post.get('jobLocationType') == 'TELECOMMUTE':
        names.append('Remote')
        eligible = post.get('applicantLocationRequirements') or []
        for place in eligible if isinstance(eligible, list) else [eligible]:
            if isinstance(place, dict) and isinstance(place.get('name'), str):
                names.append('Eligible country: ' + place['name'])
    return dict(id=site + '-' + hashlib.sha256(url.encode()).hexdigest()[:24],
                title=title, company=company, description=description,
                location='; '.join(dict.fromkeys(x for x in names if x)),
                url=url, posted_at=post.get('datePosted'))


def detail(url, site, cache, base=None, reader=None):
    reader = reader or read
    base = base or SITES[site]['url']
    target = Path(cache) / (hashlib.sha256(url.encode()).hexdigest() + '.json') if cache else None
    if target:
        try:
            if time.time() - target.stat().st_mtime < 21600:
                job = normalize(json.loads(target.read_text()), url, site)
                if job is None:
                    raise ValueError('Cached listing expired')
                return job
        except (OSError, ValueError):
            pass
    linker = custom_link if site.startswith('custom-') else safe_url
    for post in postings(Page(reader(url)).structured):
        # Reject recommendations embedded beside the requested job.
        if post.get('url') and linker(post['url'], base) != url:
            continue
        job = normalize(post, url, site)
        if job is None:
            raise ValueError('Listing has expired')
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False, encoding='utf-8') as output:
                output.write(json.dumps(post))
            Path(output.name).replace(target)
        return job
    raise ValueError('No complete public structured job description found')


def _fetch(site, cache=None, limit=MAX_DETAILS, listing=None, deadline=None):
    spec = dict(SITES[site])
    if listing:
        spec["listing"] = listing
    started = time.monotonic()
    jobs, links, warnings = [], [], []
    if 'feed' in spec:
        root = ET.fromstring(read(spec['feed']))
        for item in root.findall('./channel/item')[:MAX_ITEMS]:
            link = item.findtext('link', '')
            if not link:
                continue
            url = safe_url(link, spec['url'])
            if site == 'germantechjobs':
                title, sep, company = item.findtext('title', '').rpartition(' @ ')
                if not sep:
                    continue
                company = re.sub(r'\s*\[[^\]]*\]\s*$', '', company)
                try:
                    posted = parsedate_to_datetime(item.findtext('pubDate', '')).isoformat()
                except (ValueError, TypeError):
                    posted = None
                jobs.append(normalize(dict(title=title, hiringOrganization={'name': company},
                    description=item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or item.findtext('description'),
                    datePosted=posted), url, site))
            else:
                links.append(url)
    else:
        page = Page(read(spec['listing']))
        pattern = r'/job/[a-zA-Z0-9_-]+/?' if site == 'devjobs' else r'/companies/[^/]+/jobs/[a-zA-Z0-9_-]+/?'
        for link in page.links:
            try:
                url = safe_url(link, spec['url'])
            except ValueError:
                continue
            if re.fullmatch(pattern, urlsplit(url).path):
                links.append(url)
    for url in list(dict.fromkeys(links))[:min(limit, MAX_DETAILS)]:
        if time.monotonic() > (deadline if deadline is not None else started + 90):
            warnings.append('Import time limit reached; only a bounded sample was checked.')
            break
        try:
            jobs.append(detail(url, site, cache))
        except AccessRestricted as error:
            warnings.append(str(error))
            break
        except (ValueError, requests.RequestException) as error:
            warnings.append(str(error))
        time.sleep(1)
    if not jobs:
        raise ValueError(warnings[0] if warnings else 'No public listings found. The website may have changed or restricted access.')
    return jobs, warnings


def fetch(site, cache=None, limit=MAX_DETAILS, countries=None):
    if site != 'nextleveljobs' or not countries:
        return _fetch(site, cache, limit)
    selected = list(dict.fromkeys(code for code in countries if code in COUNTRIES))
    if not selected:
        raise ValueError('Choose a supported country in Preferences.')
    jobs, warnings = {}, []
    deadline = time.monotonic() + 90
    # Share the existing detail allowance across countries, rather than multiplying it.
    for index, code in enumerate(selected):
        allowance = limit // len(selected) + int(index < limit % len(selected))
        if not allowance:
            continue
        if time.monotonic() > deadline:
            warnings.append('Import time limit reached before all selected countries could be checked.')
            break
        try:
            found, notes = _fetch(site, cache, allowance, 'https://nextleveljobs.eu/country/' + code, deadline=deadline)
            for job in found:
                jobs[job['id']] = job
            warnings.extend(notes)
        except (ValueError, requests.RequestException) as error:
            warnings.append(COUNTRIES[code]['name'] + ': ' + str(error))
    if not jobs:
        raise ValueError('; '.join(warnings) or 'No public jobs found in selected countries.')
    return list(jobs.values()), warnings


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) <= 32 for c in value):
        raise ValueError('Enter a public HTTPS source URL.')
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port or p.fragment:
        raise ValueError('Use HTTPS without a login, port or fragment.')
    host = p.hostname.encode('idna').decode('ascii').lower()
    if '.' not in host or host.endswith(('.local', '.localhost', '.internal')):
        raise ValueError('Only public internet sources are supported.')
    return urlunsplit(('https', host, p.path or '/', p.query, ''))


def custom_link(link, base):
    safe_url(link, base)
    return public_url(urljoin(base, link))


class PublicConnection(http.client.HTTPSConnection):
    """Connect to a vetted DNS address while retaining TLS hostname verification."""
    def connect(self):
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global or ipaddress.ip_address(entry[4][0]).is_multicast for entry in addresses):
            raise ValueError('Source URLs must resolve only to public internet addresses.')
        family, kind, proto, _, address = addresses[0]
        raw = socket.socket(family, kind, proto)
        raw.settimeout(self.timeout)
        try:
            raw.connect(address)
            self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def read_public(url):
    # Each redirect gets fresh validation and a pinned connection. No proxy or cookies.
    for _ in range(4):
        url = public_url(url)
        p = urlsplit(url)
        connection = PublicConnection(p.hostname, timeout=15)
        try:
            connection.request('GET', urlunsplit(('', '', p.path, p.query, '')),
                               headers={'User-Agent': 'Jobpipe/1.0 (personal job search)', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader('Location', ''))
                continue
            if response.status != 200:
                raise AccessRestricted(f'Website returned HTTP {response.status}. Try its RSS feed or Add a posting.')
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('Source response exceeded the import size limit')
            text = data.decode('utf-8-sig', 'replace')
            if '_cf_chl_opt' in text or 'challenge-platform' in text:
                raise AccessRestricted('Website requires browser verification. Use Add a posting for now.')
            return text
        finally:
            connection.close()
    raise ValueError('Source redirected too many times.')


def custom_spec(name, url):
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError('Enter a source name of up to 100 characters.')
    url = public_url(url.strip() if isinstance(url, str) else url)
    return dict(id='custom-' + hashlib.sha256(url.encode()).hexdigest()[:20],
                name=name.strip(), url=url, enabled=True)


def structured_links(value):
    if isinstance(value, list):
        for item in value:
            yield from structured_links(item)
    elif isinstance(value, dict):
        for key in ('url', 'item'):
            if isinstance(value.get(key), str):
                yield value[key]
        for key in ('@graph', 'itemListElement', 'item'):
            yield from structured_links(value.get(key))


def fetch_custom(spec, cache=None, limit=MAX_DETAILS):
    spec = custom_spec(spec.get('name'), spec.get('url'))
    base, site = spec['url'], spec['id']
    started = time.monotonic()
    text = read_public(base)
    jobs, links, warnings = [], [], []
    try:
        root = ET.fromstring(text)
        if root.tag not in ('rss', '{http://www.w3.org/2005/Atom}feed'):
            root = None
    except ET.ParseError:
        root = None
    if root is None:
        page = Page(text)
        for post in islice(postings(page.structured), min(limit, MAX_ITEMS)):
            try:
                url = custom_link(post.get('url') or base, base)
                job = normalize(post, url, site)
                if job:
                    jobs.append(job)
            except (ValueError, TypeError, AttributeError):
                warnings.append('Skipped an incomplete structured listing.')
        links = list(structured_links(page.structured))
        links += [link for link in page.links if re.search(r'/(?:jobs?|careers?|positions?|vacancies|engineering)/.+', urlsplit(link).path)]
        if not jobs and not links and page.feeds:
            feed = custom_link(page.feeds[0], base)
            root = ET.fromstring(read_public(feed))
    if root is not None:
        atom = '{http://www.w3.org/2005/Atom}'
        items = root.findall('./channel/item') + root.findall(atom + 'entry')
        for item in items[:MAX_ITEMS]:
            link = item.findtext('link')
            if not link:
                link = next((node.get('href') for node in item.findall(atom + 'link')
                             if node.get('rel', 'alternate') == 'alternate'), None)
            if link:
                # Only an explicit full-content feed field is eligible for direct import.
                content = item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded')
                title = item.findtext('title', '')
                company = item.findtext('company', '')
                for separator in (' @ ', ' // '):
                    if not company and separator in title:
                        title, company = title.rsplit(separator, 1)
                if content and company:
                    company = re.sub(r'\s*\[[^\]]*(?:€|EUR)[^\]]*\]\s*$', '', company)
                    try:
                        job = normalize(dict(title=title, description=content,
                            hiringOrganization={'name': company}, datePosted=item.findtext('pubDate')),
                            custom_link(link, base), site)
                        if job:
                            jobs.append(job)
                            continue
                    except (ValueError, TypeError):
                        pass
                links.append(link)
    seen = {job['url'] for job in jobs}
    checked = 0
    for link in dict.fromkeys(links):
        if checked >= min(limit, MAX_DETAILS) or time.monotonic() - started > 90:
            break
        try:
            url = custom_link(link, base)
            if url in seen or url == base:
                continue
            seen.add(url)
            checked += 1
            jobs.append(detail(url, site, cache, base=base, reader=read_public))
        except AccessRestricted as error:
            warnings.append(str(error))
            break
        except (ValueError, OSError, http.client.HTTPException, TypeError, AttributeError):
            warnings.append('Skipped a link without an accessible, complete structured job description.')
        time.sleep(1)
    if not jobs:
        raise ValueError('No complete structured jobs found. Try a direct RSS feed or job-detail URL. Sites with excerpts, external clickouts, login requirements or browser verification may need a dedicated connector; you can use Add a posting.')
    unique = {job['url']: job for job in jobs}
    return list(unique.values())[:MAX_ITEMS], warnings
