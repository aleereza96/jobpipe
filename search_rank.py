"""Local job screening and ranking using saved search preferences."""
from datetime import datetime, timezone
import hashlib
import json
import unicodedata
import re

REQUIREMENTS = re.compile(
    r"\b(?:requirements|qualifications|what you bring|what you.ll need|must.have|"
    r"anforderungen|dein profil)\s*[:–—-]?\s*(.+?)(?=\b(?:benefits|"
    r"what we offer|about us|responsibilities)\s*[:–—-]|$)", re.I | re.S
)
NEGATION = re.compile(r"\b(?:no|not|without|unable to|cannot|can't|do not|don't)\b", re.I)

# Geographic reference data, activated only by the user's country selections.
COUNTRIES = {
    'de': {'name': 'Germany', 'aliases': ['Germany', 'Deutschland', 'Berlin', 'Hamburg', 'Munich', 'München', 'Frankfurt', 'Cologne', 'Köln', 'Düsseldorf', 'Dusseldorf', 'Stuttgart', 'Leipzig', 'Dresden', 'Bonn', 'Dortmund', 'Nuremberg', 'Nürnberg', 'Hannover', 'Hanover', 'Karlsruhe']},
    'nl': {'name': 'Netherlands', 'aliases': ['Netherlands', 'Nederland', 'Holland', 'Amsterdam', 'Rotterdam', 'Utrecht', 'Eindhoven', 'The Hague', 'Den Haag', 'Groningen', 'Delft', 'Leiden', 'Haarlem', 'Almere', 'Amersfoort', 'Arnhem', 'Nijmegen', 'Enschede', 'Breda', 'Tilburg', 'Maastricht', 'Zwolle', 'Den Bosch', "'s-Hertogenbosch", 'Apeldoorn', 'Hilversum', 'Hoofddorp']},
}


def location_matches(location, config):
    if matches(location, config.get('location_keywords', [])):
        return True
    return any(matches(location, COUNTRIES[code]['aliases']) or
               re.search(r'(?<!\w)' + code.upper() + r'(?!\w)', location)
               for code in config.get('target_countries', []) if code in COUNTRIES)


def language_assessment(job):
    """Conservative, explicit language evidence; ad language alone proves nothing."""
    text = (job.get('title') or '') + '. ' + (job.get('description') or '')
    patterns = {
        'German': r'\b(?:German\s*(?::|\()?\s*(?:[BC][12]|native)|(?:fluent|native|excellent|good|strong|business[- ]level)\s+(?:in\s+)?German|German\s+(?:(?:language\s+)?skills\s+)?(?:(?:is|are)\s+)?(?:required|mandatory|essential|a must|[BC][12])|(?:fließend(?:e[rsn]?)?|verhandlungssicher(?:e[rsn]?)?)\s+(?:in\s+)?Deutsch(?:kenntnisse)?|Deutschkenntnisse.{0,35}(?:erforderlich|vorausgesetzt|zwingend))\b',
        'Dutch': r'\b(?:Dutch\s*(?::|\()?\s*(?:[BC][12]|native)|(?:fluent|native|excellent|good|strong|business[- ]level)\s+(?:in\s+)?Dutch|Dutch\s+(?:(?:language\s+)?skills\s+)?(?:(?:is|are)\s+)?(?:required|mandatory|essential|a must|[BC][12])|vloeiend\s+Nederlands|Nederlands.{0,25}(?:vereist|verplicht)|beheersing van de Nederlandse taal)\b',
    }
    required, evidence = [], []
    for language, pattern in patterns.items():
        title_match = re.search(r'(?<!non-)' + language + r'[- ]speaking', job.get('title') or '', re.I)
        if title_match:
            required.append(language); evidence.append(title_match[0]); continue
        for clause in re.split(r'[.;\n]', text):
            for match in re.finditer(pattern, clause, re.I):
                before, after = clause[max(0, match.start()-25):match.start()], clause[match.end():match.end()+35]
                if re.search(r'\b(?:no|not|without)(?:\s+(?:need\s+(?:for|to)|be|necessarily|to|speak|have)){0,4}\s*$', before, re.I) or re.match(r'\s*(?:(?:is|are|would be)\s+)?(?:not (?:a requirement|required|necessary|needed|essential|mandatory)|optional|preferred|helpful|beneficial|desirable|a plus|a bonus|nice to have|an advantage|an asset)', after, re.I):
                    continue
                required.append(language); evidence.append(match[0]); break
            if language in required:
                break
    english_pattern = r'\b(?:(?:fluent|excellent|strong|good)\s+(?:in\s+)?English|English\s+(?:(?:language\s+)?skills\s+)?(?:(?:is|are)\s+)?(?:required|mandatory|essential)|(?:working|company|business) language\s+(?:is\s+)?English|English\s+is\s+(?:our|the)\s+(?:working|company|business)\s+language)\b'
    english = None
    for match in re.finditer(english_pattern, text, re.I):
        before, after = text[max(0, match.start()-25):match.start()], text[match.end():match.end()+35]
        if re.search(r'\b(?:no|not|without)(?:\s+(?:need\s+(?:for|to)|be|necessarily|to|speak|have)){0,4}\s*$', before, re.I) or re.match(r'\s*(?:(?:is|are|would be)\s+)?(?:not (?:a requirement|required|necessary|needed|essential|mandatory)|optional|preferred|helpful|beneficial|desirable|a plus|a bonus|nice to have|an advantage|an asset)', after, re.I):
            continue
        english = match; break
    return {'required_languages': required, 'evidence': evidence,
            'english': 'explicit evidence' if english else 'unknown',
            'english_evidence': english[0] if english else ''}


def language_reason(job, config):
    assessment = language_assessment(job)
    for language, key in (('German', 'exclude_german_required'), ('Dutch', 'exclude_dutch_required')):
        if language in assessment['required_languages'] and (config.get('english_only') or config.get(key)):
            return language + ' required'
    if config.get('english_only') and assessment['english'] == 'unknown' and config.get('language_unknown_policy', 'review') == 'exclude':
        return 'English working language unconfirmed'
    return None


def matches(text, terms):
    """Return distinct whole terms, preserving punctuation in names like C++."""
    found = set()
    for term in terms:
        normalized = term.strip().casefold()
        if normalized and re.search(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)", text.casefold()):
            found.add(normalized)
    return found


def relocation_signal(description, terms):
    for sentence in re.split(r"[.!?;\n]", description):
        if matches(sentence, terms) and not NEGATION.search(sentence):
            return True
    return False


def recency(job):
    value = job.get("posted_at")
    try:
        if isinstance(value, (int, float)):
            return value / 1000 if value > 10_000_000_000 else value
        if isinstance(value, str):
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, OverflowError):
        pass
    return 0


SCREEN_VERSION = 2
SCREEN_KEYS = ('include_keywords', 'exclude_keywords', 'role_keywords', 'location_keywords',
               'target_countries', 'visa_keywords', 'required_keywords', 'min_relevance',
               'include_unknown_location', 'include_relocation_outside_locations',
               'sponsorship_required', 'unknown_policy', 'english_only',
               'language_unknown_policy', 'exclude_german_required', 'exclude_dutch_required',
               'current_country', 'authorized_countries', 'relocation_required')


def screening_signature(config):
    return hashlib.sha256(json.dumps([SCREEN_VERSION, {k: config.get(k) for k in SCREEN_KEYS}],
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def normalized_title(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    for pattern, replacement in ((r'front[\s\-‐‑–]*end', 'frontend'),
                                 (r'back[\s\-‐‑–]*end', 'backend'),
                                 (r'full[\s\-‐‑–]*stack', 'fullstack'),
                                 (r'\b(?:engineer|entwickler(?:in)?|ontwikkelaar)\b', 'developer'),
                                 (r'\bsr\.?\b', 'senior')):
        value = re.sub(pattern, replacement, value)
    value = re.sub(r'[-‐‑–]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


SKILL_ALIASES = {
    'javascript': ('javascript', 'java script', 'js'),
    'typescript': ('typescript', 'type script', 'ts'),
    'node.js': ('node.js', 'nodejs', 'node js'),
    'next': ('next.js', 'nextjs'), 'next.js': ('next.js', 'nextjs'),
    'nestjs': ('nestjs', 'nest.js'), 'react': ('react', 'reactjs', 'react.js'),
    'vue': ('vue', 'vuejs', 'vue.js'), 'nuxt': ('nuxt', 'nuxtjs', 'nuxt.js'),
}


def skill_matches(text, terms):
    normalized = normalized_title(text)
    return {normalized_title(term) for term in terms
            if matches(text, SKILL_ALIASES.get(term.casefold().strip(), (term,))) or
            matches(normalized, [normalized_title(term)]) and term.casefold().strip() != 'next'}


def role_matches(title, config, description=''):
    roles = config.get('role_keywords', [])
    normalized = normalized_title(title)
    preferred = [normalized_title(role) for role in roles]
    if matches(normalized, preferred) or any('developer' in role.split() and all(matches(normalized, [word]) for word in role.split()) for role in preferred):
        return True
    # A preferred software developer also includes stack-specific software titles.
    # Do not expand into sales, hardware, management, recruiting or other families.
    software = bool(re.search(r'\b(?:frontend|backend|fullstack|software|web|product)\s+developer\b', normalized))
    stack_title = bool(skill_matches(title, config.get('include_keywords', []))) and bool(re.search(r'\bdeveloper\b', normalized))
    generic = any(re.search(r'\bsoftware developer\b', role) for role in preferred)
    if generic and (software or stack_title):
        # Preserve an explicitly senior-only search; no hidden junior/senior expansion.
        return any(not re.search(r'\b(?:senior|junior|lead|principal|staff)\b', role) or
                   any(word in normalized.split() for word in role.split() if word in ('senior', 'junior', 'lead', 'principal', 'staff'))
                   for role in preferred if 'software developer' in role)
    return False


JOB_TYPES = {
    'internship': ('internship', 'intern', 'praktikum', 'praktikant', 'praktikantin'),
    'werkstudent': ('werkstudent', 'werkstudentin', 'werkstudenten', 'working student'),
    'ausbildung': ('ausbildung', 'auszubildende', 'ausbildungsplatz', 'apprenticeship', 'apprentice'),
    'unpaid': ('unpaid', 'unbezahlt'),
}


def excluded_reason(job, config):
    title, description = job.get('title') or '', job.get('description') or ''
    for term in config.get('exclude_keywords', []):
        selected = term.casefold().strip()
        family = next((words for words in JOB_TYPES.values() if selected in words), None)
        if family:
            if matches(title, family) or matches(str(job.get('employment_type') or ''), family):
                return f'excluded job type: {term}'
            for word in family:
                pattern = r'\b(?:this|the|our|diese[rsm]?)\s+(?:role|position|job|stelle)\s+(?:is|ist)\s+(?:an?\s+)?(?:paid\s+)?' + re.escape(word) + r'\b'
                intro = r'\b(?:we are looking for|we are hiring|we seek|wir suchen)\s+(?:(?:a|an|eine[nrms]?)\s+)?(?:(?:software|frontend|backend|engineering)\s+)?' + re.escape(word) + r'\b'
                if re.search(pattern, description, re.I) or re.search(intro, description[:500], re.I):
                    return f'excluded job type: {term}'
            continue
        for match in re.finditer(r'(?<!\w)' + re.escape(selected) + r'(?!\w)', title + '\n' + description, re.I):
            if selected == 'security clearance':
                text = title + '\n' + description
                before, after = text[max(0, match.start()-25):match.start()], text[match.end():match.end()+35]
                if re.search(r'\b(?:no|not|without)\s+(?:active\s+)?$', before, re.I) or re.match(r'\s*(?:is\s+)?(?:not required|not needed|not necessary|optional|preferred|a plus|a bonus|nice to have)', after, re.I):
                    continue
            return f'excluded keyword: {term}'
    return None


def screen(job, config):
    reason = language_reason(job, config)
    if reason:
        return reason, 0
    result = eligibility(job, config, include_language=False)
    if result['status'] == 'excluded':
        conflict = next(c['requirement'] for c in result['checks'] if c['assessment'] == 'conflict')
        return 'eligibility conflict: ' + conflict, 0
    if result['status'] == 'needs checking' and config.get('unknown_policy') == 'exclude':
        return 'eligibility information unconfirmed', 0
    return evaluate(job, config)


def local_analysis(job, config, reason):
    return {'skip': reason, 'screening_stage': 'local', 'screening_signature': screening_signature(config),
            'eligibility': eligibility(job, config)}


def reconsider(con, config):
    """Recheck only local rejections; never automatically repeat AI or dismissals."""
    con.execute('CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = {'checked': 0, 'requeued': 0, 'still_rejected': 0, 'unavailable': 0}
    if 'job_sources' not in tables:
        return result
    dismissed = {row[0] for row in con.execute("SELECT job_id FROM feedback WHERE decision='dismissed'")} if 'feedback' in tables else set()
    duplicates = {row[0] for row in con.execute('SELECT duplicate_id FROM duplicate_links')} if 'duplicate_links' in tables else set()
    signature = screening_signature(config)
    for identity, raw in con.execute("SELECT id,analysis FROM jobs WHERE status='skipped' AND score=0").fetchall():
        try:
            analysis = json.loads(raw or '{}')
        except ValueError:
            continue
        is_local = analysis.get('screening_stage') == 'local' or set(analysis) == {'skip'}
        if not is_local or analysis.get('screening_signature') == signature or identity in dismissed or identity in duplicates:
            continue
        payloads = []
        for row in con.execute('SELECT payload FROM job_sources WHERE job_id=?', (identity,)):
            try:
                job = json.loads(row[0])
                if isinstance(job, dict) and isinstance(job.get('description'), str) and job['description'].strip():
                    payloads.append(job)
            except ValueError:
                pass
        if not payloads:
            result['unavailable'] += 1
            continue
        job = dict(max(payloads, key=lambda j: len(j['description'])), id=identity)
        reason, _ = screen(job, config)
        result['checked'] += 1
        if reason:
            con.execute('UPDATE jobs SET analysis=? WHERE id=?', (json.dumps(local_analysis(job, config, reason)), identity))
            result['still_rejected'] += 1
        else:
            con.execute('INSERT OR REPLACE INTO candidates VALUES(?,?)', (identity, json.dumps(job)))
            con.execute('DELETE FROM jobs WHERE id=?', (identity,))
            result['requeued'] += 1
    return result


def evaluate(job, config):
    title = job["title"] or ""
    description = job["description"] or ""
    text = title + "\n" + description
    excluded = excluded_reason(job, config)
    if excluded:
        return excluded, 0
    roles = config.get("role_keywords", [])
    role_match = role_matches(title, config, description)
    if roles and not role_match:
        return "title outside preferred roles", 0
    locations = config.get("location_keywords", [])
    location = (job.get("location") or "").strip()
    if not location:
        stated = re.search(r"^\s*location\s*:\s*([^\n]+)", description, re.I | re.M)
        location = stated[1].strip() if stated else ""
    location_match = bool(location_matches(location, config))
    visa = relocation_signal(description, config.get("visa_keywords", []))
    if (locations or config.get('target_countries')) and not location_match and not (visa and config.get("include_relocation_outside_locations", False)):
        if location or not config.get("include_unknown_location", True):
            return "location outside preferences or unconfirmed", 0

    skills = config["include_keywords"]
    title_skills = skill_matches(title, skills)
    requirements = set()
    for section in REQUIREMENTS.finditer(description):
        requirements |= skill_matches(section[1], skills)
    body_skills = skill_matches(description, skills) - title_skills - requirements
    if skills and not (title_skills or requirements or body_skills):
        return "no preferred skill", 0
    # Geography and relocation only break ties. They cannot clear the fit cutoff.
    fit = (4 * role_match + min(8, 4 * len(title_skills)) +
           min(8, 4 * len(requirements - title_skills)) + min(3, len(body_skills)))
    if not roles and not skills:
        fit = config.get("min_relevance", 4)
    if fit < config.get("min_relevance", 4):
        return "below local relevance cutoff", 0
    return None, (fit, int(location_match), int(visa), recency(job))


def eligibility(job, config, include_language=True):
    """Only explicit conflicts exclude; absent evidence remains unknown."""
    text = (job.get("title", "") + "\n" + job.get("description", ""))
    checks = []
    for term in config.get("required_keywords", []):
        checks.append({"requirement": term, "assessment": "match" if matches(text, [term]) else "unknown"})
    if config.get("sponsorship_required"):
        refusal = re.search(r"(?:cannot|can't|do not|does not|unable to|no)\s+(?:offer\s+|provide\s+)?(?:visa\s+)?sponsor(?:ship)?\b|sponsorship\s+(?:is\s+)?not available", text, re.I)
        support = re.search(r'\b(?:we\s+(?:offer|provide)|offering|providing)\s+(?:visa\s+)?sponsorship\b|\b(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|provided|offered)\b', text, re.I)
        checks.append({"requirement": "Visa sponsorship", "assessment": "conflict" if refusal else "match" if support else "unknown",
                       "posting_evidence": refusal[0] if refusal else support[0] if support else ""})
    country_pattern = r'(?:the\s+)?(Netherlands|Nederland|Germany|Deutschland)\b'
    seen_residency = set()
    for sentence in re.split(r'[.;\n]', text):
        patterns = [r'\b(?:already|currently)\s+(?:be\s+)?(?:based|living|resident|residing)\s+in\s+' + country_pattern,
                    r'\b(?:you|candidates?|applicants?)\s+(?:must|need to|have to)\s+(?:be\s+)?(?:based|living|resident|residing|reside|live)\s+in\s+' + country_pattern,
                    r'\bonly\s+(?:consider|accept|hire)\s+.{0,45}?(?:based|living|resident|residing)\s+in\s+' + country_pattern]
        for pattern in patterns:
            for requirement in re.finditer(pattern, sentence, re.I):
                prefix = sentence[max(0, requirement.start()-100):requirement.start()]
                if not re.search(r'\b(?:you|candidate|candidates|applicant|applicants|must|only)\b', prefix + requirement[0], re.I):
                    continue
                if re.search(r'(?:not required|do not require|don.t need).{0,25}$', prefix, re.I):
                    continue
                country = country_id(requirement[1])
                if country in seen_residency:
                    continue
                seen_residency.add(country)
                current = country_id(config.get('current_country', ''))
                checks.append({'requirement': 'Already resident in ' + requirement[1],
                    'assessment': 'unknown' if not current else 'match' if current == country else 'conflict',
                    'posting_evidence': sentence.strip(), 'profile_evidence': config.get('current_country', '')})
    for requirement in re.finditer(r'\b(?:right to work|work authori[sz]ation|work permit)\s+in\s+' + country_pattern, text, re.I):
        if re.match(r'\s*(?:is\s+)?(?:not required|not needed|optional)', text[requirement.end():requirement.end()+30], re.I):
            continue
        authorized = {country_id(value) for value in config.get('authorized_countries', [])}
        checks.append({'requirement': 'Existing work authorization in ' + requirement[1],
            'assessment': 'match' if country_id(requirement[1]) in authorized else 'unknown',
            'posting_evidence': requirement[0]})
    if config.get('relocation_required'):
        refusal = re.search(r'\b(?:no|cannot|can.t|do not|don.t|unable to)\s+(?:offer\s+|provide\s+|support\s+)?relocation\b|\brelocation\s+(?:support\s+)?(?:is\s+)?not\s+(?:available|offered|provided|supported)\b', text, re.I)
        support = re.search(r'\bwe\s+(?:offer|provide)\s+relocation\s+(?:support|assistance|packages?)\b|\brelocation\s+(?:support|assistance)\s+(?:is\s+)?(?:provided|offered|available)\b', text, re.I)
        checks.append({'requirement': 'Employer relocation support',
            'assessment': 'conflict' if refusal else 'match' if support else 'unknown',
            'posting_evidence': refusal[0] if refusal else support[0] if support else ''})
    if include_language and config.get('english_only'):
        language = language_assessment(job)
        checks.append({'requirement': 'English working language',
            'assessment': 'conflict' if language['required_languages'] else 'match' if language['english'] != 'unknown' else 'unknown',
            'posting_evidence': '; '.join(language['evidence']) or language['english_evidence']})
    if any(c["assessment"] == "conflict" for c in checks):
        status = "excluded"
    elif any(c["assessment"] == "unknown" for c in checks):
        status = "needs checking"
    else:
        status = "eligible"
    return {"status": status, "checks": checks}


def country_id(value):
    normalized = str(value or '').strip().casefold()
    for code, aliases in (('nl', ('nl', 'netherlands', 'the netherlands', 'nederland', 'holland')),
                          ('de', ('de', 'germany', 'deutschland'))):
        if normalized in aliases:
            return code
    return normalized
