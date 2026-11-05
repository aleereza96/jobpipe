"""Local job screening and ranking using saved search preferences."""
from datetime import datetime, timezone
import re

REQUIREMENTS = re.compile(
    r"\b(?:requirements|qualifications|what you bring|what you.ll need|must.have|"
    r"anforderungen|dein profil)\s*[:–—-]?\s*(.+?)(?=\b(?:benefits|"
    r"what we offer|about us|responsibilities)\s*[:–—-]|$)", re.I | re.S
)
NEGATION = re.compile(r"\b(?:no|not|without|unable to|cannot|can't|do not|don't)\b", re.I)


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
    location_match = bool(matches(location, locations))
    visa = relocation_signal(description, config.get("visa_keywords", []))
    if locations and not location_match and not (visa and config.get("include_relocation_outside_locations", False)):
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


def eligibility(job, config):
    """Only explicit conflicts exclude; absent evidence remains unknown."""
    text = (job.get("title", "") + "\n" + job.get("description", ""))
    checks = []
    for term in config.get("required_keywords", []):
        checks.append({"requirement": term, "assessment": "match" if matches(text, [term]) else "unknown"})
    if config.get("sponsorship_required"):
        refusal = re.search(r"(?:cannot|can't|do not|does not|unable to|no)\s+(?:offer\s+|provide\s+)?(?:visa\s+)?sponsor(?:ship)?\b|sponsorship\s+(?:is\s+)?not available", text, re.I)
        checks.append({"requirement": "Visa sponsorship", "assessment": "conflict" if refusal else "unknown",
                       "posting_evidence": refusal[0] if refusal else ""})
    if any(c["assessment"] == "conflict" for c in checks):
        status = "excluded"
    elif any(c["assessment"] == "unknown" for c in checks):
        status = "needs checking"
    else:
        status = "eligible"
    return {"status": status, "checks": checks}
