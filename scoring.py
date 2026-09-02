"""
Shared scoring logic — single source of truth used by the API, the Celery
worker and the Streamlit dashboard (so they can never disagree again).

WHY THIS WAS REWRITTEN
-----------------------------
The original implementation was:

    jd_words = set(tokens(jd))
    resume_words = set(tokens(resume))
    score = 100 * len(jd_words & resume_words) / len(jd_words)

Three compounding problems made every candidate score roughly the same
"generic" number, which is exactly the symptom users reported:

1. STOPWORDS COUNTED AS MATCHES. "and", "in", "of", "with", "the", plus
   recruiter boilerplate like "experience", "years", "team", "role", all
   intersect on virtually any resume. Measured on the real demo JD, a resume
   containing ZERO relevant skills still scored 14% — the same as the genuine
   data analyst — and a string of pure stopwords scored 12%. That is the
   floor everyone was being dragged toward.

2. THE DENOMINATOR WAS EVERY JD WORD. A 300-word JD has maybe 25 meaningful
   requirements. Dividing by 300 crushes the dynamic range: even a perfect
   candidate struggles past ~45%, so all results bunch into a narrow band and
   look interchangeable.

3. SET SEMANTICS IGNORED EMPHASIS. A JD naming "Airflow" five times weighted
   it the same as a word mentioned once in a footer.

The rewrite scores against the JD's *meaningful* vocabulary only, weights
terms by how central they are to the JD, and gives explicit credit for known
technical skills. Results spread across the full 0-100 range and rank
candidates in a defensible order.

Backwards compatibility: overlap_score() keeps its exact
(score:int, matched:list[str]) signature. score_details() exposes the full
breakdown for the UI and for match_details.
"""

import math
import re
from collections import Counter

# Keep internal tech punctuation (c++, ci/cd, node.js, .net) but never let a
# trailing sentence period/comma stick to the token — "bigquery." must match
# "bigquery", otherwise real requirements silently count as unmet.
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?)/-"

# Generic English + recruiter boilerplate. These words appear in nearly every
# JD *and* nearly every resume, so counting them rewards no real signal.
STOPWORDS = frozenset("""
a an the and or but if then else so than that this these those there here
of in on at by for to from with without within into onto up down over under
is are was were be been being am do does did doing have has had having
i you he she it we they me him her us them my your his its our their
as not no nor only own same too very can will just should now
what which who whom whose when where why how all any both each few more most
other some such via per across about after before during between against
work works working worked experience experienced experiences year years
role roles responsibility responsibilities responsible skill skills
team teams teamwork ability abilities strong excellent good great proven
knowledge understanding familiar familiarity proficient proficiency expert
new using use used uses well plus plus's must nice preferred required
require requires requirement requirements looking hiring hire candidate
candidates applicant applicants job position opportunity company
environment environments fast paced dynamic exciting join joining
you'll we're we'll etc e.g i.e including include includes included
help helping support supporting build building built develop developing
developed deliver delivery delivering ensure ensuring maintain maintaining
manage managing management lead leading led drive driving own owning
collaborate collaboration communicate communication written verbal
degree bachelor bachelors master masters bsc msc phd university college
b.sc m.sc b.eng b.tech hnd ond diploma
lagos abuja nigeria nigerian remote-first hybrid onsite city state country
please apply application send email contact cv resume reference references
available request salary benefits remote hybrid onsite office location
""".split())

# Very short tokens are almost never meaningful requirements on their own,
# with a few well-known exceptions.
_SHORT_ALLOW = frozenset({"go", "r", "c", "c++", "c#", "ai", "ml", "bi",
                          "qa", "ci", "cd", "js", "ts", "db", "aws", "gcp",
                          "sql", "etl", "elt", "api", "ui", "ux", "ci/cd"})


def tokenize(text: str) -> list[str]:
    """Lowercased tokens, keeping tech punctuation (c++, ci/cd, node.js)."""
    if not text:
        return []
    out = []
    for raw in TOKEN_RE.findall(text):
        tok = raw.lower().rstrip(_TRAILING_PUNCT)
        # Preserve tokens that legitimately end in punctuation (c++, c#).
        if not tok:
            tok = raw.lower()
        if tok:
            out.append(tok)
    return out


def is_meaningful(token: str) -> bool:
    """Does this token carry hiring signal?"""
    if token in STOPWORDS:
        return False
    if token.isdigit():
        return False
    if len(token) < 3 and token not in _SHORT_ALLOW:
        return False
    return True


def meaningful_terms(text: str) -> list[str]:
    return [t for t in tokenize(text) if is_meaningful(t)]


def _skill_vocabulary() -> set:
    """Known technical skills, lowercased. Imported lazily so scoring.py has
    no hard dependency on skills.py (keeps the module import-safe)."""
    try:
        from skills import TECH_SKILLS_DB
        return {s.lower() for s in TECH_SKILLS_DB}
    except Exception:                              # pragma: no cover
        return set()


def score_details(resume_text: str, jd: str) -> dict:
    """Full, explainable match breakdown.

    Weighting model
    ---------------
    * Only the JD's MEANINGFUL terms form the denominator, so the score
      measures real requirement coverage rather than English grammar.
    * Each JD term is weighted by sub-linear frequency (1 + ln(count)):
      a requirement repeated throughout the JD matters more than a passing
      mention, without letting one word dominate.
    * Terms that are known technical skills get a 2x multiplier — missing
      "Airflow" should cost far more than missing "stakeholder".
    * The headline score is weighted coverage of the JD's requirements.
    """
    jd_tokens = [t for t in tokenize(jd) if is_meaningful(t)]
    resume_tokens = set(tokenize(resume_text))

    if not jd_tokens:
        return {
            "score": 0, "matched": [], "missing": [],
            "matched_skills": [], "missing_skills": [],
            "jd_terms": 0, "coverage": 0.0,
            "algorithm": "weighted-keyword-coverage",
        }

    skill_vocab = _skill_vocabulary()
    counts = Counter(jd_tokens)

    total_weight = 0.0
    hit_weight = 0.0
    matched, missing = [], []
    matched_skills, missing_skills = [], []

    for term, n in counts.items():
        weight = 1.0 + math.log(n)
        if term in skill_vocab:
            weight *= 2.0
        total_weight += weight

        if term in resume_tokens:
            hit_weight += weight
            matched.append(term)
            if term in skill_vocab:
                matched_skills.append(term)
        else:
            missing.append(term)
            if term in skill_vocab:
                missing_skills.append(term)

    coverage = hit_weight / total_weight if total_weight else 0.0
    score = int(round(100 * coverage))
    score = max(0, min(100, score))

    # Rank the most important misses first so the UI can show useful gaps.
    missing.sort(key=lambda t: -(1.0 + math.log(counts[t])) *
                 (2.0 if t in skill_vocab else 1.0))

    return {
        "score": score,
        "matched": sorted(matched),
        "missing": missing[:25],
        "matched_skills": sorted(matched_skills),
        "missing_skills": sorted(missing_skills),
        "jd_terms": len(counts),
        "coverage": round(coverage, 4),
        "algorithm": "weighted-keyword-coverage",
    }


def overlap_score(resume_text: str, jd: str):
    """(score_percent, matched_terms) — stable signature used everywhere.

    Only MEANINGFUL matched terms are returned, so the UI's "Matched Keywords"
    column and the skill cloud stop being a wall of "and / of / the".
    """
    d = score_details(resume_text, jd)
    return d["score"], d["matched"]
