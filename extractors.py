"""
Heuristic CV field extraction: name, email, phone, years of experience,
education.

These are deliberately dependency-light regex/heuristic extractors — good
precision on well-formatted resumes, honest about their limits. True NER
(spaCy / transformers) is on the roadmap.
"""

import re

try:
    import ner            # module-level so Celery prefork children resolve it
except ImportError:       # pragma: no cover
    ner = None

try:
    from skills import TECH_SKILLS_DB
except ImportError:       # pragma: no cover
    TECH_SKILLS_DB = []

_SKILL_LEXICON = {s.lower() for s in TECH_SKILLS_DB}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(\+?\d[\d\s().\-]{6,}\d)")

_NAME_BLOCKLIST = (
    "resume", "curriculum", "vitae", "cv", "phone", "tel", "email",
    "address", "linkedin", "github", "portfolio", "objective", "summary",
    "profile", "page",
)
_YEAR_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs)\b", re.IGNORECASE)
_EDUCATION_KEYWORDS = (
    "phd", "ph.d", "msc", "m.sc", "master", "mba", "bsc", "b.sc",
    "bachelor", "beng", "b.eng", "hnd", "ond", "diploma", "degree",
    "university", "college", "polytechnic",
)


def _plausible_name(name) -> bool:
    """Sanity-check an NER-detected name. Small NER models love labelling
    tech terms ("Docker", "Kubernetes") as PERSON when the real name is
    unfamiliar to them — never let a known skill word pass as a name."""
    if not name:
        return False
    words = [w.lower().strip(".,") for w in str(name).split()]
    return not any(w in _SKILL_LEXICON for w in words)


def extract_email(text: str):
    m = EMAIL_RE.search(text or "")
    return m.group(0) if m else None


def extract_phone(text: str):
    for m in PHONE_RE.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(1))
        if 7 <= len(digits) <= 15:
            return m.group(1).strip()
    return None


def extract_name(text: str):
    """Heuristic: a candidate name is usually the first short line of
    Title-Case words that isn't contact info or a section header."""
    for raw in (text or "").splitlines()[:6]:
        line = raw.strip()
        if not line or len(line) > 60:
            continue
        lower = line.lower()
        if any(k in lower for k in _NAME_BLOCKLIST):
            continue
        if "@" in line or "http" in lower:
            continue
        words = line.split()
        if not 1 <= len(words) <= 4:
            continue
        # A known tech skill is never a person's name. Without this the regex
        # fallback happily returned "Docker"/"Python" as the candidate name --
        # including right after the NER guard had rejected exactly that value.
        if not _plausible_name(line):
            continue
        if all(w[0].isupper() for w in words if w and w[0].isalpha()):
            if not any(ch.isdigit() for ch in line):
                return line
    return None


def extract_experience_years(text: str):
    """Largest explicit 'X years' claim found, e.g. '8+ years experience'."""
    years = [int(m.group(1)) for m in _YEAR_RE.finditer(text or "")]
    years = [y for y in years if 0 < y <= 50]
    return max(years) if years else None


def extract_education(text: str):
    """Education-related lines/keywords found in the resume."""
    found = set()
    for kw in _EDUCATION_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", (text or "").lower()):
            found.add(kw.upper() if len(kw) <= 4 else kw.title())
    return sorted(found)


def extract_fields(text: str) -> dict:
    """All extracted fields as a JSON-serializable dict.

    Uses true NER (spaCy PERSON/ORG) when available — with a skill-lexicon
    sanity check on the name — otherwise the regex heuristics above.
    `extraction_method` says which one was used.
    """
    name = None
    organizations = []
    method = "regex-heuristic"
    if ner is not None and ner.ner_available():
        ner_name = ner.extract_name_ner(text)
        if ner_name:
            # an entity span can swallow the line under the name — keep the
            # first line only (resume header convention)
            ner_name = str(ner_name).splitlines()[0].strip() or None
        name = ner_name if _plausible_name(ner_name) else None
        organizations = ner.extract_organizations(text)
        method = "spacy-ner"
    if name is None:
        name = extract_name(text)
        if not organizations:
            method = "regex-heuristic"

    return {
        "name": name,
        "email": extract_email(text),
        "phone": extract_phone(text),
        "experience_years": extract_experience_years(text),
        "education": extract_education(text),
        "organizations": organizations,
        "extraction_method": method,
    }
