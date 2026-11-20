"""Local job screening and ranking using saved search preferences."""
from datetime import datetime, timezone
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


def evaluate(job, config):
    title = job["title"] or ""
    description = job["description"] or ""
    text = title + "\n" + description
    if matches(text, config["exclude_keywords"]):
        return "excluded keyword", 0
    roles = config.get("role_keywords", [])
    role_match = bool(matches(title, roles))
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
    title_skills = matches(title, skills)
    requirements = set()
    for section in REQUIREMENTS.finditer(description):
        requirements |= matches(section[1], skills)
    body_skills = matches(description, skills) - title_skills - requirements
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
        checks.append({"requirement": "Visa sponsorship", "assessment": "conflict" if refusal else "unknown",
                       "posting_evidence": refusal[0] if refusal else ""})
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
